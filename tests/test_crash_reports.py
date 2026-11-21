"""Crash drafts contain code locations, never exception text, source lines or locals."""

import json
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from tests.test_members_signin import member, sign_in
from tests.test_web_jobs import login
from tests.test_web_plan_execution import prepared
from torrentlinker import crash_reports
from torrentlinker.web.app import create_app
from torrentlinker.web.jobs import Jobs


def test_trace_drops_private_messages_paths_names_hashes_and_source(monkeypatch):
    secret = (
        "PrivatePerson /home/PrivatePerson/film c411 https://private.test/?key=secret " + "a" * 40
    )
    source = str(crash_reports.ROOT / "web" / "app.py")
    try:
        exec(compile("raise RuntimeError(private)", source, "exec"), {"private": secret})
    except RuntimeError as error:
        draft = crash_reports.exception_draft(error)
    assert "web/app.py:1" in draft["body"]
    assert "PrivatePerson" not in json.dumps(draft)
    for private in ["c411", "private.test", "secret", "a" * 40, "/home/", "raise RuntimeError"]:
        assert private not in json.dumps(draft)
    parsed = urlsplit(draft["url"])
    assert parsed.netloc == "github.com"
    assert parse_qs(parsed.query)["body"] == [draft["body"]]
    assert "OS:" in draft["body"] and "TorrentLinker:" in draft["body"]


def test_browser_frames_are_allowlisted_and_bounded():
    stack = """TypeError: PrivatePerson c411 /home/person/secret
at private (https://box.test/static/app.js:227:3)
at private (https://box.test/static/../../secret.js:1:2)
at unknown (https://evil.test/private.js:2:3)
"""
    draft = crash_reports.browser_draft(stack * 200)
    assert draft["body"].count("web/static/app.js:227") == 20
    assert all(
        s not in draft["body"] for s in ["box.test", "PrivatePerson", "c411", "secret", "evil.test"]
    )
    assert len(draft["url"]) < 8000


def test_owner_can_review_api_crash_but_members_cannot(tmp_path):
    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )

    @app.get("/api/test-crash")
    def crash():
        raise RuntimeError("private URL and account name")

    with TestClient(app, raise_server_exceptions=False) as browser:
        login(browser)
        response = browser.get("/api/test-crash")
        assert response.status_code == 502
        assert "report" in response.json()
        assert "private URL" not in json.dumps(response.json()["report"])
        draft = browser.post(
            "/api/crash-report", json={"stack": "https://private/static/app.js:1:2"}
        )
        assert draft.status_code == 200 and "web/static/app.js:1" in draft.json()["body"]
        member(app, "lea")
        sign_in(browser, "lea")
        assert browser.post("/api/crash-report", json={"stack": "anything"}).status_code == 403


def test_failed_job_keeps_only_a_sanitized_in_memory_draft(tmp_path):
    jobs = Jobs(tmp_path)
    try:

        def work(stop, report):
            raise RuntimeError("private-user and password")

        identifier = jobs.submit("refresh", work)
        jobs.executor.shutdown(wait=True)
        jobs.interactive_executor.shutdown(wait=True)
        result = jobs.get(identifier)
        assert result["status"] == "failed"
        assert "report" in result
        assert "private-user" not in json.dumps(result["report"])
        assert not crash_reports.unexpected(ValueError("bad input"))
        assert not crash_reports.unexpected(OSError("network"))
    finally:
        jobs.close()
