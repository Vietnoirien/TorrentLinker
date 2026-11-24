import hashlib
from pathlib import Path

import pytest
import torf

from tests.torrents import make_torrent
from torrentlinker.torrent_meta import read_torrent


def test_single_file_torrent_lists_its_file_under_the_torrent_name(tmp_path: Path) -> None:
    f = tmp_path / "Le.Joueur.D'echecs.Stefan.Zweig.2013.FR.[EPUB]-NOTAG.epub"
    f.write_bytes(b"x" * 67163)

    meta = read_torrent(make_torrent(f))

    assert meta.name == f.name
    assert meta.files == {f.name: 67163}
    assert len(meta.infohash) == 40


def test_multi_file_torrent_paths_include_the_root_folder(tmp_path: Path) -> None:
    root = tmp_path / "Show.S01"
    (root / "Subs").mkdir(parents=True)
    (root / "e01.mkv").write_bytes(b"a" * 1000)
    (root / "Subs" / "e01.srt").write_bytes(b"b" * 10)

    meta = read_torrent(make_torrent(root))

    assert meta.files == {"Show.S01/e01.mkv": 1000, "Show.S01/Subs/e01.srt": 10}


def test_v1_torrent_with_nonstandard_positive_piece_length_can_be_reseeded(tmp_path: Path) -> None:
    content = b"film" * 2500
    file = tmp_path / "Film.mkv"
    file.write_bytes(content)
    torrent = torf.Torrent.read_stream(make_torrent(file), validate=False)
    torrent.metainfo["info"]["piece length"] = 3_876_307
    torrent.metainfo["info"]["pieces"] = hashlib.sha1(content).digest()
    data = torrent.dump(validate=False)

    meta = read_torrent(data)

    assert meta.name == file.name
    assert meta.files == {file.name: len(content)}
    assert meta.piece_length == 3_876_307
    assert (
        meta.infohash
        == hashlib.sha1(torf._flatbencode.encode(torrent.convert()[b"info"])).hexdigest()
    )


def test_nonstandard_piece_length_still_requires_consistent_piece_hashes(tmp_path: Path) -> None:
    file = tmp_path / "Film.mkv"
    file.write_bytes(b"film" * 2500)
    torrent = torf.Torrent.read_stream(make_torrent(file), validate=False)
    torrent.metainfo["info"]["piece length"] = 3_876_307
    torrent.metainfo["info"]["pieces"] = b""
    with pytest.raises(torf.MetainfoError):
        read_torrent(torrent.dump(validate=False))


def test_v2_torrent_does_not_use_v1_piece_length_fallback(tmp_path: Path) -> None:
    file = tmp_path / "Film.mkv"
    file.write_bytes(b"film" * 2500)
    torrent = torf.Torrent.read_stream(make_torrent(file), validate=False)
    torrent.metainfo["info"]["piece length"] = 3_876_307
    torrent.metainfo["info"]["meta version"] = 2

    with pytest.raises(torf.MetainfoError, match="piece length"):
        read_torrent(torrent.dump(validate=False))
