"""Desktop UI and MCP transport acceptance tests use an isolated workspace."""

import json
import os
import socket
import subprocess
import sys
import threading
import time

import httpx
import uvicorn

from torrentlinker.agent.desktop import DesktopSetup
from torrentlinker.config import Settings
from torrentlinker.gui.agent_access import AgentDialog
from torrentlinker.store import Store
from torrentlinker.web.app import create_app


def test_desktop_owner_can_revoke_and_default_to_proposals(qtbot, tmp_path):
    setup = DesktopSetup(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    app = create_app(
        tmp_path, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    dialog = AgentDialog(app.state.agent_service, "http://127.0.0.1:8790/mcp/")
    qtbot.addWidget(dialog)
    assert dialog.mode.currentData() == "propose"
    assert not dialog.enabled.isChecked()
    assert all(not c.isEnabled() for _, c in dialog.permissions)
    dialog.mode.setCurrentIndex(1)
    assert all(c.isEnabled() for _, c in dialog.permissions)
    from torrentlinker.agent.access import Grant

    grant = app.state.agent_service.access.create(Grant(name="Owner test", clients=["default"]))
    dialog.refresh()
    dialog.items.setCurrentRow(0)
    dialog.revoke.click()
    assert app.state.agent_service.access.snapshot()["connections"][0]["revoked"]
    assert grant["token"] not in dialog.details.toPlainText()
    app.state.agent_service.jobs.close()


def test_stdio_bridge_uses_running_server_and_only_outputs_protocol(tmp_path):
    app = create_app(tmp_path, password="test-password-long")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", headers={"X-TorrentLinker": "1"}
        ) as owner:
            assert (
                owner.post("/api/login", json={"password": "test-password-long"}).status_code == 200
            )
            token = owner.post(
                "/api/agents", json={"name": "stdio", "clients": ["default"]}
            ).json()["token"]
            owner.put("/api/agents", json={"enabled": True})
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "overview", "arguments": {}},
            },
        ]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "torrentlinker.agent.stdio",
                "--url",
                f"http://127.0.0.1:{port}/mcp/",
            ],
            input="\n".join(json.dumps(m) for m in messages) + "\n",
            env={**os.environ, "TL_MCP_TOKEN": token},
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        output = [json.loads(line) for line in result.stdout.splitlines()]
        assert [m["id"] for m in output] == [1, 2, 3]
        assert output[0]["result"]["serverInfo"]["name"] == "TorrentLinker"
        assert "propose_action" in {t["name"] for t in output[1]["result"]["tools"]}
        assert output[2]["result"]["structuredContent"]["mode"] == "propose"
        assert token not in result.stdout + result.stderr
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()


def test_desktop_client_switch_resets_agent_connections_and_blocks_settings_races(tmp_path):
    from fastapi.testclient import TestClient

    from tests.test_agent_access import call
    from tests.test_web_jobs import Client, finished, login
    from torrentlinker.agent.desktop import DesktopServer
    from torrentlinker.domain import TorrentClient

    settings = Settings()
    settings.ensure_profiles()
    settings.qbit.host = "http://first.example"
    settings.capture_client()
    second = settings.add_client("Second box", TorrentClient.QBITTORRENT)
    second.host = "http://second.example"
    first_client, second_client = Client(), Client()
    first_client.release.set()
    second_client.release.set()
    runtime = DesktopServer(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    runtime.setup.connector = lambda kind, host, *args: (
        second_client if host == "http://second.example" else first_client
    )
    runtime.app = create_app(
        tmp_path,
        password="test-password-long",
        service_override=runtime.setup,
        monitor_verifications=False,
    )
    with TestClient(runtime.app) as browser:
        login(browser)
        grant = browser.post(
            "/api/agents",
            json={
                "name": "Switch test",
                "clients": ["default", second.id],
                "mode": "execute",
                "permissions": ["controls"],
            },
        ).json()
        browser.put("/api/agents", json={"enabled": True})

        def pause(identifier, key):
            return call(
                browser,
                grant["token"],
                "propose_action",
                {
                    "request_id": key,
                    "operation": {
                        "kind": "manage",
                        "action": "pause",
                        "hashes": ["a" * 40],
                        "client_id": identifier,
                    },
                },
            )["structuredContent"]

        job = pause("default", "first")
        assert finished(browser, job["job_id"])["status"] == "completed"
        with runtime.editing_settings():
            assert "error" in pause(second.id, "while-editing")
            runtime.reset(settings.for_client(second.id))
        job = pause(second.id, "second")
        assert finished(browser, job["job_id"])["status"] == "completed"
        assert first_client.paused == ["a" * 40]
        assert second_client.paused == ["a" * 40]
        # Ordinary desktop mutations cannot change an in-flight agent's settings snapshot.
        settings.qbit.host = "http://changed.example"
        assert runtime.setup.settings.qbit.host == "http://second.example"


def test_failed_server_start_does_not_block_ordinary_settings(qtbot, tmp_path):
    from types import SimpleNamespace

    import pytest

    from torrentlinker.agent.desktop import DesktopServer, agent_settings_change

    runtime = DesktopServer(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 8790))
        occupied.listen()
        with pytest.raises(OSError):
            runtime.start()
    calls = []

    @agent_settings_change
    def edit(window):
        calls.append("settings opened")

    edit(SimpleNamespace(agent_runtime=runtime))
    assert calls == ["settings opened"]
    runtime.close()


def test_main_window_settings_stay_available_after_mcp_port_failure(qtbot, tmp_path, monkeypatch):
    from torrentlinker.gui import main_window

    window = main_window.MainWindow(
        Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db")
    )
    qtbot.addWidget(window)
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: None)
    opened = []
    monkeypatch.setattr(main_window.SettingsDialog, "exec", lambda self: opened.append(True) or 0)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 8790))
        occupied.listen()
        window.open_agent_access()
    assert window.agent_runtime is None
    window.open_settings()
    assert opened == [True]


def test_desktop_agent_timer_does_not_wait_for_busy_job_lock(tmp_path):
    from torrentlinker.agent.desktop import DesktopServer

    settings = Settings()
    runtime = DesktopServer(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    runtime.app = create_app(
        tmp_path,
        password="test-password-long",
        service_override=runtime.setup,
        monitor_verifications=False,
    )
    locked, release = threading.Event(), threading.Event()

    def worker():
        with runtime.service.jobs.lock:
            locked.set()
            release.wait(3)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert locked.wait(1)
        settings.uploads += 1
        before = time.monotonic()
        runtime.sync(settings)
        assert runtime.busy()
        assert time.monotonic() - before < 0.25
        assert runtime.setup.settings.uploads != settings.uploads
    finally:
        release.set()
        thread.join(3)
    runtime.sync(settings)
    assert runtime.setup.settings.uploads == settings.uploads
    runtime.service.jobs.close()
