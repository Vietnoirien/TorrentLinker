import threading
from dataclasses import replace

import httpx

from tests.fake_qbit import FakeQbit
from tests.test_send import release
from torrentlinker.category_tags import CATEGORY_TAG_PREFIX
from torrentlinker.download_queue import SEARCH_TAG, enqueue, entries, run_queue
from torrentlinker.downloads import IndexerCategory
from torrentlinker.indexer import Candidate, Indexer, KeyRefused, RateLimited
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent


def setup_queue(tmp_path):
    store = Store(tmp_path / "state.db")
    data = release(tmp_path)
    meta = read_torrent(data)
    client = FakeQbit()
    indexer = Indexer(
        "https://example.test/api",
        "private-key",
        http=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data))
        ),
    )
    candidate = Candidate(
        meta.name,
        5001,
        "https://example.test/get?apikey=private-key",
        3,
        meta.infohash,
        categories=(2000, 2010),
    )
    folder = tmp_path / "downloads"
    folder.mkdir()
    enqueue(store, indexer, candidate, folder)
    return store, indexer, client, candidate, data, folder


def process(store, indexer, client, **kwargs):
    return run_queue(
        store,
        indexer,
        client,
        {2000: IndexerCategory("Movies"), 2010: IndexerCategory("HD", 2000)},
        kwargs.pop("stop", threading.Event()),
        kwargs.pop("progress", lambda p: None),
        **kwargs,
    )


def test_queue_survives_restart_without_persisting_keys_or_duplicate_entries(tmp_path):
    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    assert not enqueue(store, indexer, replace(c, download_url=c.download_url + "&extra=1"), folder)
    restored = Store(tmp_path / "state.db")
    assert len(entries(restored)) == 1
    assert "private-key" not in str(restored.queued_downloads())
    assert b"private-key" not in (tmp_path / "state.db").read_bytes()
    report = process(restored, indexer, client)
    assert report.added == [c.title]
    assert client.downloads == [c.infohash]
    torrent = client.torrent(c.infohash)
    assert torrent.save_path == folder
    assert torrent.tags == {SEARCH_TAG, CATEGORY_TAG_PREFIX + "Movies / HD"}
    assert entries(restored) == []
    assert process(restored, indexer, client).handled == 0


def test_existing_client_torrent_is_skipped_without_fetching(tmp_path, monkeypatch):
    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    client.download(data, str(folder), ["personal"])
    monkeypatch.setattr(
        indexer,
        "fetch_torrent",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    assert process(store, indexer, client).refused
    assert entries(store)[0].status == "refused"
    assert client.torrent(c.infohash).tags == {"personal"}


def test_queue_preserves_existing_files(tmp_path):
    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    target = folder / c.title / "film.nfo"
    target.parent.mkdir()
    target.write_bytes(b"my file")
    assert process(store, indexer, client).refused
    assert not client.downloads
    assert target.read_bytes() == b"my file"


def test_pause_during_rate_limit_leaves_item_queued_and_resume_sends_once(tmp_path, monkeypatch):
    store, indexer, client, c, data, folder = setup_queue(tmp_path)

    def refused(*a, **kw):
        raise RateLimited(120)

    monkeypatch.setattr(indexer, "fetch_torrent", refused)
    progress, waits = [], []
    report = process(
        store,
        indexer,
        client,
        progress=progress.append,
        wait=lambda seconds: waits.append(seconds) or True,
    )
    assert report.stopped and not client.downloads
    assert waits == [120]
    assert progress[-1].retry_at is not None
    assert entries(store)[0].status == "queued"
    monkeypatch.setattr(indexer, "fetch_torrent", lambda *a, **kw: data)
    assert process(store, indexer, client).added == [c.title]
    assert client.downloads == [c.infohash]


def test_pause_after_one_send_leaves_remaining_items_queued(tmp_path):
    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    enqueue(store, indexer, replace(c, infohash="b" * 40, title="second"), folder)
    stop = threading.Event()

    def progress(p):
        if p.done == 1:
            stop.set()

    report = process(store, indexer, client, stop=stop, progress=progress)
    assert report.stopped and len(report.added) == 1
    assert [e.status for e in entries(store)] == ["queued"]


def test_wrong_hash_and_changed_indexer_are_refused(tmp_path, monkeypatch):
    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    other = release(tmp_path, "Other")
    monkeypatch.setattr(indexer, "fetch_torrent", lambda *a, **kw: other)
    assert process(store, indexer, client).refused
    assert not client.downloads
    key = entries(store)[0].key
    store.download_outcome(key, "queued")
    indexer.url = "https://different.test/api"
    assert process(store, indexer, client).refused
    assert not client.downloads


def test_auth_failure_stops_remaining_queue_and_redacts_errors(tmp_path, monkeypatch):
    store, indexer, client, c, data, folder = setup_queue(tmp_path)
    enqueue(store, indexer, replace(c, infohash="b" * 40, title="second"), folder)

    def refused(*a, **kw):
        raise KeyRefused(403)

    monkeypatch.setattr(indexer, "fetch_torrent", refused)
    report = process(store, indexer, client)
    assert report.stopped and len(report.failed) == 1
    assert [e.status for e in entries(store)] == ["failed", "queued"]
    store.download_outcome(entries(store)[0].key, "queued")

    def failed(*a, **kw):
        raise RuntimeError("URL with private-key")

    monkeypatch.setattr(indexer, "fetch_torrent", failed)
    process(store, indexer, client)
    assert "private-key" not in str(store.queued_downloads())


def test_successful_send_clears_queue_immediately_and_after_restart(tmp_path):
    store, indexer, client, candidate, data, folder = setup_queue(tmp_path)
    observed = []
    report = process(store, indexer, client, progress=lambda p: observed.append(entries(store)))
    assert report.added == [candidate.title]
    assert client.downloads == [candidate.infohash]
    assert observed[-1] == []
    assert entries(Store(tmp_path / "state.db")) == []
    assert process(store, indexer, client).handled == 0
    assert client.downloads == [candidate.infohash]


def test_restart_clears_legacy_sent_rows_but_preserves_pending_and_problem_rows(tmp_path):
    store, indexer, client, candidate, data, folder = setup_queue(tmp_path)
    store.download_outcome(entries(store)[0].key, "sent")
    expected = ["queued", "failed", "refused", "uncertain"]
    for number, status in enumerate(expected, 1):
        other = replace(candidate, title=status, infohash=f"{number:040x}")
        enqueue(store, indexer, other, folder)
        store.download_outcome(entries(store)[-1].key, status)
    assert [e.status for e in entries(Store(tmp_path / "state.db"))] == expected
    assert client.downloads == []


def test_successful_send_keeps_other_clients_queue(tmp_path):
    store, indexer, client, candidate, data, folder = setup_queue(tmp_path)
    other = store.for_client("other")
    enqueue(other, indexer, candidate, folder)
    process(store, indexer, client)
    assert entries(store) == []
    assert len(entries(other)) == 1
    assert entries(other)[0].status == "queued"


def test_uncertain_handoff_stays_visible_and_is_not_retried(tmp_path, monkeypatch):
    store, indexer, client, candidate, data, folder = setup_queue(tmp_path)
    download = client.download

    def accepted_then_disconnected(*args, **kwargs):
        download(*args, **kwargs)
        raise RuntimeError("Connection lost after handoff")

    monkeypatch.setattr(client, "download", accepted_then_disconnected)
    report = process(store, indexer, client)
    assert report.failed
    assert entries(store)[0].status == "uncertain"
    assert process(store, indexer, client).handled == 0
    assert client.downloads == [candidate.infohash]


def _exit_after_download_handoff(directory):
    import json
    import os
    from pathlib import Path

    store, indexer, client, candidate, data, folder = setup_queue(directory)
    enqueue(store.for_client("other"), indexer, candidate, folder)

    def accept_then_exit(data, folder, tags):
        # Durable stand-in for a Torrent Client accepting the request before the
        # app receives its response. No finally blocks or graceful shutdown run.
        Path(directory / "accepted.json").write_text(
            json.dumps({"hash": read_torrent(data).infohash, "folder": folder})
        )
        os._exit(0)

    client.download = accept_then_exit
    process(store, indexer, client)


def test_process_exit_after_handoff_preserves_uncertainty_and_client_scope(tmp_path):
    import json
    import multiprocessing

    child = multiprocessing.get_context("spawn").Process(
        target=_exit_after_download_handoff, args=(tmp_path,)
    )
    child.start()
    try:
        child.join(10)
        assert child.exitcode == 0
        accepted = json.loads((tmp_path / "accepted.json").read_text())
        store = Store(tmp_path / "state.db")
        try:
            recovered = entries(store)
            assert len(recovered) == 1
            entry = recovered[0]
            assert entry.status == "uncertain" and not entry.retry_safe
            assert entry.candidate.infohash == accepted["hash"]
            assert str(entry.folder) == accepted["folder"]
            assert entry.client_id == "default"
            assert "Check the Torrent Client" in entry.reason
            other = entries(store.for_client("other"))
            assert len(other) == 1 and other[0].status == "queued"
            assert other[0].client_id == "other"
            client = FakeQbit()
            with httpx.Client(
                transport=httpx.MockTransport(lambda request: httpx.Response(500))
            ) as http:
                indexer = Indexer("https://example.test/api", "private-key", http=http)
                assert process(store, indexer, client).handled == 0
            assert client.downloads == []
            assert (tmp_path / "elsewhere" / entry.candidate.title / "film.mkv").read_bytes() == (
                b"x" * 5000
            )
        finally:
            store._db.close()
    finally:
        if child.is_alive():
            child.kill()
            child.join()
