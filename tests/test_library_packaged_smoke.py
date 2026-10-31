"""The packaged rescan probe remains independent of real clients and credentials."""


def test_packaged_library_probe_scans_without_network_or_real_keyring(qapp, monkeypatch, capsys):
    import socket

    import keyring

    from torrentlinker.gui import tasks
    from torrentlinker.library_smoke import library_smoke_checks

    def forbidden(*args, **kwargs):
        raise AssertionError("Packaged Library probe reached a real connection or credential")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    original = keyring.get_keyring()
    monkeypatch.setattr(original, "get_password", forbidden)
    monkeypatch.setattr(original, "set_password", forbidden)
    monkeypatch.setattr(original, "delete_password", forbidden)
    library_smoke_checks()
    assert keyring.get_keyring() is original
    assert "10 scans, 25 items" in capsys.readouterr().out
    assert not tasks._alive


def test_packaged_library_probe_reports_worker_failure_and_restores_keyring(qapp, monkeypatch):
    import keyring
    import pytest

    from torrentlinker.gui import main_window, tasks
    from torrentlinker.library_smoke import library_smoke_checks

    def fail(*args, **kwargs):
        raise RuntimeError("controlled scan failure")

    original = keyring.get_keyring()
    monkeypatch.setattr(main_window, "build_library", fail)
    with pytest.raises(AssertionError, match="controlled scan failure"):
        library_smoke_checks()
    assert keyring.get_keyring() is original
    assert not tasks._alive
