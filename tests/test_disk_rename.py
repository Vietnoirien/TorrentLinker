import threading

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget

from tests.test_utorrent_unit import WebUI, api_for
from tests.torrents import make_torrent
from torrentlinker.disk_rename import (
    DiskRenameError,
    apply_disk_renames,
    journal_path,
    plan_disk_renames,
    undo_disk_renames,
)
from torrentlinker.domain import LocalItem, PathMapping
from torrentlinker.gui.reseed_consent import DiskRenameDialog, ReseedConsent
from torrentlinker.matching import Match
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.reseed import ReseedAborted, check_verifications, start_reseed
from torrentlinker.store import SavedUpload, Store
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.upload import PreparedUpload, UploadFile, seed_upload


def fixture(tmp_path, multi=False):
    library = tmp_path / "Library"
    library.mkdir()
    scene = tmp_path / "torrent"
    scene.mkdir()
    if multi:
        scene = scene / "Release"
        scene.mkdir()
    (scene / "Scene.epub").write_bytes(b"book" * 15000)
    meta = read_torrent(make_torrent(scene if multi else scene / "Scene.epub"))
    local = library / "My book.epub"
    local.write_bytes(b"book" * 15000)
    item = LocalItem(local, {local.name: local.stat().st_size})
    match = Match({next(iter(meta.files)): local.name})
    web = WebUI()
    mapped = MappedQbit(api_for(web), PathMapper([PathMapping(str(library), "C:\\Downloads")]))
    return item, meta, match, web, mapped, Store(tmp_path / "s.db")


@pytest.mark.parametrize("approval", [None, lambda _: False])
def test_cancel_or_missing_approval_never_renames_or_adds(tmp_path, approval):
    item, meta, match, web, client, store = fixture(tmp_path)
    with pytest.raises(ReseedAborted, match="cancelled"):
        start_reseed(client, store, item, meta, match, "candidate", approve_disk_renames=approval)
    assert item.path.read_bytes() == b"book" * 15000
    assert not (item.save_path / meta.name).exists()
    assert not any(c.get("action") == "add-file" for c in web.calls)
    assert not journal_path(tmp_path, meta.infohash).exists()


@pytest.mark.parametrize("multi", [False, True])
def test_approved_upload_renames_then_seeds_and_cleans_journal(tmp_path, multi):
    item, meta, match, web, client, store = fixture(tmp_path, multi)
    before = item.path.stat()
    prepared = PreparedUpload(
        SavedUpload(item.path, meta.name, meta.infohash, 123, 0),
        meta,
        [UploadFile(t, local, meta.files[t]) for t, local in match.pairs.items()],
    )
    seen = []
    h = seed_upload(
        client, store, item, prepared, approve_disk_renames=lambda plan: seen.append(plan) or True
    )
    assert len(seen) == 1
    target = item.save_path / next(iter(meta.files))
    assert not item.path.exists() and target.read_bytes() == b"book" * 15000
    assert target.stat().st_ino == before.st_ino and target.stat().st_mtime_ns == before.st_mtime_ns
    assert not any(c.get("action") == "start" for c in web.calls)
    assert journal_path(tmp_path, h).exists()
    web.jobs[h][4] = 1000
    web.file_rows[h][0][2] = web.file_rows[h][0][1]
    assert check_verifications(client, store)[0].started
    assert not journal_path(tmp_path, h).exists()
    assert target.exists() and not item.path.exists()


def test_bad_local_hash_leaves_original_name_and_no_job(tmp_path):
    item, meta, match, web, client, store = fixture(tmp_path)
    item.path.write_bytes(b"evil" * 15000)
    with pytest.raises(DiskRenameError, match="do not match"):
        start_reseed(
            client, store, item, meta, match, "candidate", approve_disk_renames=lambda p: True
        )
    assert item.path.read_bytes() == b"evil" * 15000
    assert not any(c.get("action") == "add-file" for c in web.calls)


def test_occupied_target_and_symlink_are_refused(tmp_path):
    item, meta, match, _, _, _ = fixture(tmp_path)
    target = item.save_path / meta.name
    target.write_bytes(b"unrelated")
    with pytest.raises(DiskRenameError, match="already exists"):
        plan_disk_renames(item, meta, match)
    assert target.read_bytes() == b"unrelated"
    target.unlink()
    original = item.path.with_suffix(".original")
    item.path.rename(original)
    item.path.symlink_to(original)
    with pytest.raises(DiskRenameError, match="symbolic"):
        plan_disk_renames(item, meta, match)


def test_failed_setup_and_failed_client_check_restore_original_names(tmp_path):
    item, meta, match, web, client, store = fixture(tmp_path)
    web.settings["append_incomplete"] = "true"
    with pytest.raises(Exception, match="Disable"):
        start_reseed(
            client, store, item, meta, match, "candidate", approve_disk_renames=lambda p: True
        )
    assert item.path.exists() and not (item.save_path / meta.name).exists()
    web.settings["append_incomplete"] = "false"
    h = start_reseed(
        client, store, item, meta, match, "candidate", approve_disk_renames=lambda p: True
    )
    outcome = check_verifications(client, store, now=lambda: 1e12)[0]
    assert not outcome.verified and h not in web.jobs
    assert item.path.read_bytes() == b"book" * 15000
    assert not (item.save_path / meta.name).exists()
    assert not journal_path(tmp_path, h).exists()


def test_recovery_before_add_and_after_interrupted_verification_is_client_specific(tmp_path):
    item, meta, match, web, client, store = fixture(tmp_path)
    apply_disk_renames(tmp_path, plan_disk_renames(item, meta, match), client.reseed_client_id)
    other = MappedQbit(api_for(web, "http://other:8081"), PathMapper([]))
    check_verifications(other, store)
    assert not item.path.exists()
    check_verifications(client, store)
    assert item.path.exists() and not journal_path(tmp_path, meta.infohash).exists()
    h = start_reseed(
        client, store, item, meta, match, "candidate", approve_disk_renames=lambda p: True
    )
    store.end_verification(h)
    check_verifications(client, store)
    assert item.path.exists() and h not in web.jobs


def test_undo_never_overwrites_new_file_at_old_name(tmp_path):
    item, meta, match, _, client, _ = fixture(tmp_path)
    plan = plan_disk_renames(item, meta, match)
    apply_disk_renames(tmp_path, plan, client.reseed_client_id)
    item.path.write_bytes(b"unrelated new file")
    with pytest.raises(DiskRenameError, match="occupied"):
        undo_disk_renames(tmp_path, meta.infohash)
    assert item.path.read_bytes() == b"unrelated new file"
    assert plan.moves[0].target.read_bytes() == b"book" * 15000
    assert journal_path(tmp_path, meta.infohash).exists()


def test_rename_race_does_not_overwrite_destination(tmp_path, monkeypatch):
    from torrentlinker import disk_rename

    item, meta, match, _, client, _ = fixture(tmp_path)
    plan = plan_disk_renames(item, meta, match)
    real = disk_rename._rename_noreplace

    def race(source, target):
        target.write_bytes(b"racing file")
        real(source, target)

    monkeypatch.setattr(disk_rename, "_rename_noreplace", race)
    with pytest.raises(FileExistsError):
        apply_disk_renames(tmp_path, plan, client.reseed_client_id)
    assert item.path.exists() and plan.moves[0].target.read_bytes() == b"racing file"


def test_dialog_lists_moves_and_cancel_is_default(qtbot, tmp_path):
    item, meta, match, _, _, _ = fixture(tmp_path)
    dialog = DiskRenameDialog(plan_disk_renames(item, meta, match))
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.files.item(0, 0).text() == str(item.path)
    assert dialog.files.item(0, 1).text() == str(item.save_path / meta.name)
    assert dialog.cancel_button.isDefault() and not dialog.rename_button.isDefault()
    qtbot.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
    assert dialog.result() == 0 and item.path.exists()


def test_worker_confirmation_and_shutdown(qtbot, tmp_path):
    item, meta, match, _, _, _ = fixture(tmp_path)
    window = QWidget()
    qtbot.addWidget(window)
    broker = ReseedConsent(window)
    result = []
    plan = plan_disk_renames(item, meta, match)
    worker = threading.Thread(target=lambda: result.append(broker.approve(plan)))
    QTimer.singleShot(100, broker.cancel)
    worker.start()
    qtbot.waitUntil(lambda: bool(result))
    worker.join(1)
    assert result == [False]
