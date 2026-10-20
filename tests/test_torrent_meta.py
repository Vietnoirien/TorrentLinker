from pathlib import Path

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
