import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from tests.fake_qbit import FakeQbit
from tests.torrents import make_torrent
from torrentlinker.archives import ArchiveError, unpack, unpacked
from torrentlinker.domain import LocalItem
from torrentlinker.indexer import Candidate
from torrentlinker.matching import IgnoreList, MatchRules
from torrentlinker.review import check_candidates, unpack_and_reseed
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent

RULES = MatchRules(0.02, 0.5, IgnoreList.default())


def release(root: Path) -> Path:
    """An STL release as a torrent holds it: a folder of models and renders."""
    (root / "STL").mkdir(parents=True)
    (root / "RENDERS").mkdir()
    (root / "STL" / "head.stl").write_bytes(b"solid head " * 4000)
    (root / "STL" / "body.stl").write_bytes(b"solid body " * 9000)
    (root / "RENDERS" / "front.png").write_bytes(bytes(range(256)) * 50)
    return root


def zipped(folder: Path, archive: Path, top: bool = True) -> Path:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                name = f.relative_to(folder.parent if top else folder).as_posix()
                z.write(f, name)
    return archive


def item_of(archive: Path) -> LocalItem:
    return LocalItem(archive, {archive.name: archive.stat().st_size})


class Torrents:
    """An Indexer serving .torrent files, counting what it was asked for."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.fetched: list[str] = []

    def fetch_torrent(self, candidate: Candidate) -> bytes:
        self.fetched.append(candidate.title)
        return self.files[candidate.download_url]


def test_a_zip_is_listed_with_the_sizes_of_what_it_holds(tmp_path: Path) -> None:
    folder = release(tmp_path / "src" / "Kaneda")
    (tmp_path / "lib").mkdir()
    archive = zipped(folder, tmp_path / "lib" / "CA3D - Kaneda.zip")

    inside = unpacked(item_of(archive))

    assert inside is not None
    # The zip's single top folder becomes the new folder, next to the archive.
    assert inside.item.path == tmp_path / "lib" / "Kaneda"
    assert inside.item.files["Kaneda/STL/body.stl"] == (folder / "STL" / "body.stl").stat().st_size
    assert inside.size == sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
    assert inside.size > archive.stat().st_size  # compressed


def test_a_zip_without_a_top_folder_unpacks_into_a_folder_named_after_it(tmp_path: Path) -> None:
    folder = release(tmp_path / "src" / "Kaneda")
    (tmp_path / "lib").mkdir()
    archive = zipped(folder, tmp_path / "lib" / "Kaneda Akira.zip", top=False)

    inside = unpacked(item_of(archive))

    assert inside is not None and inside.item.path == tmp_path / "lib" / "Kaneda Akira"
    assert "Kaneda Akira/STL/head.stl" in inside.item.files


def test_an_archive_escaping_its_folder_is_not_trusted(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../outside.txt", "no")

    assert unpacked(item_of(archive)) is None


def test_a_torrent_of_the_unpacked_folder_matches_the_archive(tmp_path: Path) -> None:
    folder = release(tmp_path / "src" / "Kaneda")
    (tmp_path / "lib").mkdir()
    archive = zipped(folder, tmp_path / "lib" / "CA3D - Kaneda.zip")
    data = make_torrent(folder)
    unpacked_size = sum(read_torrent(data).files.values())
    candidate = Candidate("CA3D.Studios.Kaneda.AKIRA[STL]", unpacked_size, "u1")
    film = Candidate("Kaneda.1988.1080p", 10**9, "u2")  # far off any size: never fetched
    indexer = Torrents({"u1": data})

    [kaneda, other] = check_candidates(indexer, item_of(archive), [candidate, film], RULES)  # type: ignore[arg-type]

    assert indexer.fetched == ["CA3D.Studios.Kaneda.AKIRA[STL]"]
    assert kaneda.match is not None and kaneda.match.is_full
    assert kaneda.unpack is not None and kaneda.unpack.archive == archive
    assert not other.compared


def test_unpack_then_reseed_seeds_the_new_folder_and_keeps_the_archive(tmp_path: Path) -> None:
    folder = release(tmp_path / "src" / "Kaneda")
    (tmp_path / "lib").mkdir()
    archive = zipped(folder, tmp_path / "lib" / "CA3D - Kaneda.zip")
    data = make_torrent(folder)
    candidate = Candidate("Kaneda", sum(read_torrent(data).files.values()), "u1")
    [checked] = check_candidates(Torrents({"u1": data}), item_of(archive), [candidate], RULES)  # type: ignore[arg-type]
    qbit, store, seen = FakeQbit(), Store(tmp_path / "s.db"), []

    h, local = unpack_and_reseed(qbit, store, checked, RULES, lambda d, t: seen.append((d, t)))

    assert local.path == tmp_path / "lib" / "Kaneda"
    assert (local.path / "STL" / "head.stl").read_bytes() == (
        folder / "STL" / "head.stl"
    ).read_bytes()
    assert archive.exists()  # kept until the user decides, after Verification
    assert store.take_unpacked(local.path) == archive
    assert store.take_unpacked(local.path) is None  # asked once
    t = qbit.torrent(h)
    assert t is not None and t.save_path == tmp_path / "lib"
    assert seen[-1] == (checked.unpack.size, checked.unpack.size)  # type: ignore[union-attr]


def test_unpacking_never_writes_over_an_existing_folder(tmp_path: Path) -> None:
    folder = release(tmp_path / "src" / "Kaneda")
    (tmp_path / "lib" / "Kaneda").mkdir(parents=True)
    (tmp_path / "lib" / "Kaneda" / "mine.txt").write_text("mine")
    archive = zipped(folder, tmp_path / "lib" / "CA3D - Kaneda.zip")
    target = unpacked(item_of(archive))
    assert target is not None

    with pytest.raises(ArchiveError):
        unpack(target)

    assert [p.name for p in (tmp_path / "lib" / "Kaneda").iterdir()] == ["mine.txt"]


def test_a_failed_unpack_removes_only_the_folder_it_was_creating(tmp_path: Path) -> None:
    folder = release(tmp_path / "src" / "Kaneda")
    (tmp_path / "lib").mkdir()
    archive = zipped(folder, tmp_path / "lib" / "CA3D - Kaneda.zip")
    target = unpacked(item_of(archive))
    assert target is not None

    def stop(done: int, total: int) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError):
        unpack(target, stop)

    assert sorted(p.name for p in (tmp_path / "lib").iterdir()) == ["CA3D - Kaneda.zip"]


@pytest.mark.skipif(shutil.which("7z") is None, reason="7-Zip is not installed")
def test_a_7z_archive_is_listed_and_unpacked_with_7_zip(tmp_path: Path) -> None:
    folder = release(tmp_path / "src" / "Kaneda")
    (tmp_path / "lib").mkdir()
    archive = tmp_path / "lib" / "Kaneda.7z"
    subprocess.run(["7z", "a", "-bd", str(archive), str(folder)], check=True, capture_output=True)
    target = unpacked(item_of(archive))
    assert target is not None and target.item.path == tmp_path / "lib" / "Kaneda"

    unpack(target)

    assert (tmp_path / "lib" / "Kaneda" / "STL" / "body.stl").stat().st_size == (
        folder / "STL" / "body.stl"
    ).stat().st_size


@pytest.mark.skipif(shutil.which("7z") is None, reason="7-Zip is not installed")
def test_when_a_tool_cannot_unpack_the_next_one_gets_a_clean_try(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from torrentlinker import archives

    folder = release(tmp_path / "src" / "Kaneda")
    (tmp_path / "lib").mkdir()
    archive = tmp_path / "lib" / "Kaneda.7z"
    subprocess.run(["7z", "a", "-bd", str(archive), str(folder)], check=True, capture_output=True)
    target = unpacked(item_of(archive))
    assert target is not None
    real = archives._unpack_commands
    # Like Debian's 7-Zip with RAR5: it starts writing, then fails on every entry.
    broken = [
        "sh",
        "-c",
        'mkdir -p "$0/Kaneda" && touch "$0/Kaneda/half" && exit 2',
        str(target.into),
    ]
    monkeypatch.setattr(archives, "_unpack_commands", lambda a, i: [broken, *real(a, i)])

    unpack(target)

    assert not (tmp_path / "lib" / "Kaneda" / "half").exists()
    assert (tmp_path / "lib" / "Kaneda" / "STL" / "head.stl").is_file()


def test_a_tool_reporting_every_file_is_cut_to_a_few_lines() -> None:
    from torrentlinker.archives import _shortened

    text = "\n".join(f"ERROR: Unsupported Method : Kaneda/bike1-{i}.stl" for i in range(200))

    short = _shortened(text)

    assert short.count("\n") == 3 and short.endswith("… and 197 more lines")
