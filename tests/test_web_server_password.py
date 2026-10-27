from torrentlinker.web.server import resolve_password


def test_password_file_wins_over_environment(tmp_path):
    file = tmp_path / "pw"
    file.write_text("from-the-file-123\n")
    assert resolve_password(file, {"TL_WEB_PASSWORD": "from-env-1234567"}) == "from-the-file-123"


def test_environment_used_without_file():
    assert resolve_password(None, {"TL_WEB_PASSWORD": " from-env-1234567 "}) == "from-env-1234567"


def test_no_password_configured():
    assert resolve_password(None, {}) is None
    assert resolve_password(None, {"TL_WEB_PASSWORD": "  "}) is None
