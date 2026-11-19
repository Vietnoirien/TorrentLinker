"""Real SFTP on disposable internal Docker networks. No user credentials or files."""

import json
import os
import subprocess
import time
import uuid
from contextlib import contextmanager

import pytest

from tests.shell_support import shell_navigate
from tests.test_multi_client_docker import docker
from torrentlinker.remote_access import RemoteAccess
from torrentlinker.web.security import ServerSecrets

pytest_plugins = ["tests.test_multi_client_docker", "tests.test_enqueue_destinations"]

pytestmark = pytest.mark.skipif(
    os.getenv("TL_SEEDBOX_DOCKER") != "1", reason="set TL_SEEDBOX_DOCKER=1"
)


@contextmanager
def sftp_endpoint(data, client_root="/data", sftp_options="", authorized_key=""):
    from pathlib import Path

    network = "tl-seedbox-" + uuid.uuid4().hex[:10]
    data.mkdir(mode=0o777, exist_ok=True)
    data.chmod(0o777)
    (data / "films").mkdir(mode=0o777, exist_ok=True)
    (data / "films").chmod(0o777)
    sshdir = data.parent / (network + "-ssh")
    sshdir.mkdir(mode=0o755)
    (sshdir / "authorized_keys").write_text(authorized_key)
    (sshdir / "authorized_keys").chmod(0o644)
    sshconfig = data.parent / (network + ".conf")
    sshconfig.write_text(
        Path("tests/docker/seedbox/sshd_config")
        .read_text()
        .replace("internal-sftp", "internal-sftp " + sftp_options)
    )
    docker("network", "create", "--internal", network)
    try:
        docker(
            "run",
            "-d",
            "--name",
            network,
            "--network",
            network,
            "-v",
            f"{sshdir}:/home/seed/.ssh:ro",
            "-v",
            f"{sshconfig}:/etc/ssh/sshd_config:ro",
            "-v",
            f"{data}:/files",
            "torrentlinker-sftp-test:118",
        )
        address = json.loads(
            docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", network)
        )[network]["IPAddress"]
        import socket

        for _attempt in range(50):
            try:
                with socket.create_connection((address, 2222), timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        yield (
            {
                "host": address,
                "port": 2222,
                "username": "seed",
                "auth": "password",
                "client_root": client_root,
                "file_root": "/files",
            },
            data,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", network], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


@pytest.fixture
def seedbox(tmp_path, request):
    cluster = request.getfixturevalue("cluster") if "cluster" in request.fixturenames else None
    data = cluster.folder("qbit-b") if cluster else tmp_path / "files"
    with sftp_endpoint(data, "/data" if cluster else "/downloads") as endpoint:
        yield endpoint


def test_remote_access_requires_identity_confirmation_and_keeps_credentials_private(
    seedbox, tmp_path
):
    config, data = seedbox
    service = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
    for _attempt in range(30):
        try:
            identity = service.discover(config)
            break
        except OSError:
            time.sleep(0.2)
    else:
        pytest.fail("Disposable SSH server did not start")
    assert identity["fingerprint"].startswith("SHA256:")
    with pytest.raises(ValueError, match="identity"):
        service.save("seedbox", config, "disposable-test-password", "")
    service.save("seedbox", config, "disposable-test-password", identity["host_key"])
    checked = service.check("seedbox")
    assert checked["checked"] is True
    assert checked["free_bytes"] > 0
    assert "/downloads/films" in service.browse("seedbox", "/downloads")["folders"]
    from pathlib import PureWindowsPath

    # Client adapters use pathlib on Windows; SFTP keeps the server's POSIX namespace.
    assert service.path_for("seedbox", PureWindowsPath("/downloads/films")).is_dir()
    assert "disposable-test-password" not in json.dumps(service.snapshot("seedbox"))
    reopened = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
    assert reopened.check("seedbox")["checked"] is True
    service.close()
    reopened.close()


def test_transfer_copies_to_seedbox_verifies_and_recovers(cluster, seedbox, tmp_path):
    from tests.test_multi_client_docker import until
    from tests.torrents import make_torrent
    from torrentlinker.torrent_meta import read_torrent
    from torrentlinker.transfers import Transfers

    config, data_folder = seedbox
    access = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
    key = access.discover(config)["host_key"]
    access.save("qbit-b", config, "disposable-test-password", key)
    access.check("qbit-b")
    source = cluster.folder("qbit-a") / "remote-transfer.bin"
    source.write_bytes(os.urandom(2_500_000))
    data = make_torrent(source)
    infohash = read_torrent(data).infohash
    cluster.clients["qbit-a"].add(data, str(source.parent), [])
    cluster.clients["qbit-a"].recheck(infohash)
    until(lambda: cluster.clients["qbit-a"].torrent(infohash).progress == 1)
    clients = {**cluster.clients, "qbit-b": cluster.clients["qbit-b"]._inner}
    transfers = Transfers(tmp_path / "plans", clients.get, storage=access.path_for)
    plan = transfers.prepare(
        [{"client_id": "qbit-a", "hash": infohash, "folder": "/data/films"}], "qbit-b"
    )
    assert plan["can_start"], plan
    transfers.stop(plan["id"])
    assert transfers.run(plan["id"])["rows"][0]["status"] == "interrupted"
    reopened = Transfers(tmp_path / "plans", clients.get, storage=access.path_for)
    result = reopened.run(plan["id"])
    assert result["rows"][0]["status"] == "confirmed", result
    assert (data_folder / "films" / source.name).read_bytes() == source.read_bytes()
    assert source.exists()
    # Download from the seedbox, then explicitly remove only the source files.
    returning = Transfers(
        tmp_path / "return", clients.get, metadata=lambda cid, key: data, storage=access.path_for
    )
    target = cluster.folder("deluge") / "returned"
    target.mkdir()
    back = returning.prepare(
        [{"client_id": "qbit-b", "hash": infohash, "folder": str(target)}],
        "deluge",
        remove_files=True,
    )
    assert back["can_start"], back
    result = returning.run(back["id"])
    assert result["rows"][0]["status"] == "confirmed", result
    remote_source = data_folder / "films" / source.name
    before = remote_source.stat()
    remote_source.write_bytes(b"x" * before.st_size)
    os.utime(remote_source, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match="Source content"):
        returning.review_cleanup(back["id"], 0)
    remote_source.write_bytes(source.read_bytes())
    os.utime(remote_source, ns=(before.st_atime_ns, before.st_mtime_ns))
    review = returning.review_cleanup(back["id"], 0)
    returning.cleanup(back["id"], 0, review["token"])
    assert not (data_folder / "films" / source.name).exists()
    assert (target / source.name).read_bytes() == source.read_bytes()
    assert clients["qbit-b"].torrent(infohash) is not None
    access.close()


def test_changed_identity_and_unsafe_paths_block_access(seedbox, tmp_path):
    import asyncssh

    config, data = seedbox
    access = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
    identity = access.discover(config)
    wrong = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
    access.save("remote", config, "disposable-test-password", wrong)
    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        access.check("remote")
    assert access.snapshot("remote")["checked"] is False
    access.save("remote", config, "disposable-test-password", identity["host_key"])
    (data / "escape").symlink_to("/etc", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        access.browse("remote", "/downloads/escape")
    with pytest.raises(ValueError):
        access.browse("remote", "/downloads/../etc")
    access.close()


def test_shared_workspace_configures_remote_access_and_browses_client_paths(seedbox, operations):
    from tests.test_torrents_workspace import workspace

    config, _ = seedbox
    service = workspace(operations)
    identity = service.request(
        "transfer-access-discover", {"client_id": "default", "config": config}
    )
    service.request(
        "transfer-access-save",
        {
            "client_id": "default",
            "config": config,
            "credential": "disposable-test-password",
            "host_key": identity["host_key"],
        },
    )
    checked = service.request("transfer-access-check", {"client_id": "default"})
    assert checked["checked"]
    result = service.request(
        "transfer-remote-browse", {"client_id": "default", "path": "/downloads"}
    )
    assert "/downloads/films" in result["folders"]
    options = service.request("transfer-options", {"items": []})
    assert options["clients"][0]["access"]["checked"]


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="set TL_WEB_BROWSER=1")
def test_seedbox_dialog_access_mapping_and_progress(cluster, seedbox, tmp_path):
    import socket
    import threading

    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_multi_client_docker import until
    from tests.torrents import make_torrent
    from torrentlinker.torrent_meta import read_torrent
    from torrentlinker.web.app import create_app

    config, _ = seedbox
    source = cluster.folder("qbit-a") / "sftp-ui.bin"
    source.write_bytes(os.urandom(100_000))
    data = make_torrent(source)
    infohash = read_torrent(data).infohash
    client = cluster.clients["qbit-a"]
    client.add(data, str(source.parent), [])
    client.recheck(infohash)
    until(lambda: client.torrent(infohash).progress == 1)
    directory = tmp_path / "web"
    directory.mkdir()
    cluster.settings.save(directory / "settings.json")
    (directory / "client.ready").touch()
    ServerSecrets(directory).update(cluster.secrets)
    app = create_app(directory, password="test-password-long", roots=(cluster.root,))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    until(lambda: server.started)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "torrents")
            panel = page.frame_locator("#torrents-frame")
            panel.locator("#query").fill("sftp-ui")
            expect(panel.locator("tbody tr")).to_have_count(1)
            panel.locator("tbody input").first.check()
            panel.locator("#transfer-selection").click()
            panel.locator("#transfer-destination").select_option(cluster.ids["qbit-b"])
            panel.locator(f'[data-remote-edit="{cluster.ids["qbit-b"]}"]').click()
            panel.locator("#remote-host").fill(config["host"])
            panel.locator("#remote-port").fill(str(config["port"]))
            panel.locator("#remote-user").fill("seed")
            panel.locator("#remote-auth").select_option("password")
            panel.locator("#remote-credential").fill("disposable-test-password")
            panel.locator("#remote-client-root").fill("/data")
            panel.locator("#remote-file-root").fill("/files")
            panel.locator("#remote-test").click()
            expect(panel.locator("#remote-trust")).to_be_visible()
            panel.locator("#remote-trust").check()
            panel.locator("#remote-test").click()
            expect(panel.locator("#remote-result")).to_contain_text(
                "Access verified", timeout=20000
            )
            panel.locator("#remote-done").click()
            expect(panel.locator("#transfer-destination")).to_be_visible()
            panel.locator("[data-transfer-folder]").first.fill("/data/films")
            panel.locator("[data-transfer-folder]").first.press("Tab")
            panel.locator("#transfer-check").click()
            expect(panel.locator("#transfer-start")).to_be_enabled(timeout=20000)
            panel.locator("#transfer-start").click()
            expect(panel.locator(".transfer-item")).to_contain_text(
                "Seeding at destination", timeout=60000
            )
            assert source.exists()
            page.screenshot(
                path=os.getenv("TL_SEEDBOX_SCREENSHOT", str(tmp_path / "seedbox-web.png"))
            )
            panel.locator("#transfer-close").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("light")
            panel.locator("#transfer-history").click()
            panel.locator("[data-transfer-id]").first.click()
            expect(panel.locator(".transfer-heading")).to_contain_text(
                "Transférer vers un autre client"
            )
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(15)


def test_seedbox_relay_resumes_partial_copy_and_rejects_collision(cluster, seedbox, tmp_path):
    from tests.test_multi_client_docker import until
    from tests.torrents import make_torrent
    from torrentlinker.torrent_meta import read_torrent
    from torrentlinker.transfers import Transfers

    config, source_folder = seedbox
    with sftp_endpoint(cluster.folder("deluge")) as (destination_config, target_folder):
        access = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
        for identifier, cfg in [("qbit-b", config), ("deluge", destination_config)]:
            key = access.discover(cfg)["host_key"]
            access.save(identifier, cfg, "disposable-test-password", key)
            access.check(identifier)
        source = source_folder / "relay.bin"
        source.write_bytes(os.urandom(16 * 1024 * 1024))
        data = make_torrent(source)
        infohash = read_torrent(data).infohash
        cluster.clients["qbit-b"].add(data, str(source_folder), [])
        cluster.clients["qbit-b"].recheck(infohash)
        until(lambda: cluster.clients["qbit-b"].torrent(infohash).progress == 1)
        clients = {name: value._inner for name, value in cluster.clients.items()}
        service = Transfers(
            tmp_path / "plans", clients.get, metadata=lambda cid, key: data, storage=access.path_for
        )
        target = target_folder / "films" / source.name
        target.write_bytes(b"already exists")
        blocked = service.prepare(
            [{"client_id": "qbit-b", "hash": infohash, "folder": "/data/films"}], "deluge"
        )
        assert not blocked["can_start"]
        target.unlink()
        plan = service.prepare(
            [{"client_id": "qbit-b", "hash": infohash, "folder": "/data/films"}], "deluge"
        )
        assert plan["can_start"], plan
        service.start(plan["id"])
        until(lambda: service.get(plan["id"])["rows"][0]["bytes"] > 0)
        service.stop(plan["id"])
        until(lambda: service.get(plan["id"])["status"] != "running")
        assert service.get(plan["id"])["rows"][0]["status"] == "interrupted"
        resumed = Transfers(
            tmp_path / "plans", clients.get, metadata=lambda cid, key: data, storage=access.path_for
        )
        result = resumed.run(plan["id"])
        assert result["rows"][0]["status"] == "confirmed", result
        assert source.read_bytes() == target.read_bytes()
        access.close()


def test_ssh_key_authentication_and_unreported_capacity(tmp_path):
    import asyncssh

    key = asyncssh.generate_private_key("ssh-ed25519")
    with sftp_endpoint(
        tmp_path / "files",
        sftp_options="-P statvfs,fstatvfs",
        authorized_key=key.export_public_key().decode(),
    ) as (config, _):
        access = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
        config["auth"] = "key"
        identity = access.discover(config)
        access.save("remote", config, key.export_private_key().decode(), identity["host_key"])
        assert "/data/films" in access.browse("remote", "/data")["folders"]
        with pytest.raises(ValueError, match="available space"):
            access.check("remote")
        assert not access.snapshot("remote")["checked"]
        access.close()
