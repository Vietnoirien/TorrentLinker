import base64
import io
from pathlib import Path

import pytest
import torf

from tests.fake_qbit import FakeQbit
from torrentlinker.domain import LocalItem
from torrentlinker.matching import IgnoreList
from torrentlinker.reseed import TAG, VERIFYING, start_reseed
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.upload import (
    MiB,
    Subcategory3D,
    UploadStopped,
    bencode,
    draft_body,
    make_torrent,
    nfo_3d,
    piece_size,
    problems_3d,
    seed_match,
    suggested_name,
    upload_files,
)

IGNORE = IgnoreList.default()
ANNOUNCE = "https://c411.org/announce/secret"


def vise(tmp_path: Path) -> LocalItem:
    f = tmp_path / "STL" / "Petit étau de bureau.3mf"
    f.parent.mkdir()
    f.write_bytes(bytes(range(256)) * 9000)  # 2.2 Mo: three 1 MiB pieces
    return scan_item(f)


def dragon_pack(tmp_path: Path) -> LocalItem:
    root = tmp_path / "STL" / "Dragon de feu"
    (root / "Têtes").mkdir(parents=True)
    (root / "Corps entier.stl").write_bytes(b"c" * 1500)
    (root / "Têtes" / "tête ouverte.stl").write_bytes(b"t" * 700)
    (root / "Thumbs.db").write_bytes(b"ignored")
    return scan_item(root)


def test_a_release_name_has_dotted_words_without_accents_the_source_and_the_formats(
    tmp_path: Path,
) -> None:
    item = vise(tmp_path)

    assert suggested_name(item, IGNORE) == "Petit.Etau.De.Bureau.NOTAG.3MF"
    assert suggested_name(item, IGNORE, "Printables") == "Petit.Etau.De.Bureau.Printables.3MF"
    assert (
        suggested_name(dragon_pack(tmp_path), IGNORE, "My Mini Factory", pack=True)
        == "Dragon.De.Feu.My.Mini.Factory.[PACK].STL"
    )


def test_archives_and_folders_without_a_3d_file_are_refused(tmp_path: Path) -> None:
    archive = tmp_path / "Model.rar"
    archive.write_bytes(b"r" * 10)
    assert problems_3d(scan_item(archive), IGNORE) == [
        "Archives are refused: rar",
        "No 3D file (STL, 3MF, OBJ, STEP, GCODE…)",
    ]
    assert problems_3d(vise(tmp_path), IGNORE) == []


def test_a_single_file_is_named_the_release_title_plus_its_extension(tmp_path: Path) -> None:
    item = vise(tmp_path)

    (f,) = upload_files(item, "Petit.Etau.De.Bureau.NOTAG.3MF", IGNORE)

    assert f.torrent_path == "Petit.Etau.De.Bureau.NOTAG.3MF.3mf"
    assert f.local_path == "Petit étau de bureau.3mf"


def test_a_folder_becomes_the_release_title_and_names_below_lose_accents_and_spaces(
    tmp_path: Path,
) -> None:
    files = upload_files(dragon_pack(tmp_path), "Dragon.NOTAG.[PACK].STL", IGNORE)

    assert [(f.torrent_path, f.local_path) for f in files] == [
        ("Dragon.NOTAG.[PACK].STL/Corps.entier.stl", "Dragon de feu/Corps entier.stl"),
        ("Dragon.NOTAG.[PACK].STL/Tetes/tete.ouverte.stl", "Dragon de feu/Têtes/tête ouverte.stl"),
    ]


def test_piece_size_follows_c411s_table() -> None:
    assert piece_size(4_400_000) == 1 * MiB
    assert piece_size(1_500_000_000) == 2 * MiB
    assert piece_size(2_500_000_000) == 4 * MiB
    assert piece_size(5_000_000_000) == 8 * MiB
    assert piece_size(9_000_000_000) == 16 * MiB


def test_the_torrent_is_private_announces_to_the_user_and_hashes_the_local_data(
    tmp_path: Path,
) -> None:
    item = dragon_pack(tmp_path)
    files = upload_files(item, "Dragon.NOTAG.[PACK].STL", IGNORE)

    data = make_torrent(item, files, ANNOUNCE)

    t = torf.Torrent.read_stream(io.BytesIO(data))
    assert t.private and t.trackers == [[ANNOUNCE]]
    assert t.piece_size == MiB
    assert {"/".join(f.parts): f.size for f in t.files} == {
        "Dragon.NOTAG.[PACK].STL/Corps.entier.stl": 1500,
        "Dragon.NOTAG.[PACK].STL/Tetes/tete.ouverte.stl": 700,
    }
    # The same data under the compliant names hashes the same: the torrent verifies.
    copy = tmp_path / "copy" / "Dragon.NOTAG.[PACK].STL"
    (copy / "Tetes").mkdir(parents=True)
    (copy / "Corps.entier.stl").write_bytes(b"c" * 1500)
    (copy / "Tetes" / "tete.ouverte.stl").write_bytes(b"t" * 700)
    assert t.verify(copy)


def test_a_single_file_torrent_verifies_against_the_file_under_its_compliant_name(
    tmp_path: Path,
) -> None:
    item = vise(tmp_path)
    files = upload_files(item, "Petit.Etau.De.Bureau.NOTAG.3MF", IGNORE)

    t = torf.Torrent.read_stream(io.BytesIO(make_torrent(item, files, ANNOUNCE)))

    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "Petit.Etau.De.Bureau.NOTAG.3MF.3mf").write_bytes(item.path.read_bytes())
    assert t.verify(copy / "Petit.Etau.De.Bureau.NOTAG.3MF.3mf")


def test_making_the_torrent_reports_progress_and_can_be_stopped(tmp_path: Path) -> None:
    item = vise(tmp_path)
    files = upload_files(item, "V", IGNORE)
    seen: list[tuple[int, int]] = []

    make_torrent(item, files, ANNOUNCE, report=lambda d, t: seen.append((d, t)))

    assert seen[-1] == (item.size, item.size)
    with pytest.raises(UploadStopped):
        make_torrent(item, files, ANNOUNCE, stopped=lambda: True)


def test_the_upload_seeds_from_the_local_files_renamed_inside_the_client(tmp_path: Path) -> None:
    item = dragon_pack(tmp_path)
    files = upload_files(item, "Dragon.NOTAG.[PACK].STL", IGNORE)
    meta = read_torrent(make_torrent(item, files, ANNOUNCE))
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, seed_match(files), f"upload:{meta.infohash}")

    t = qbit.torrent(h)
    assert t is not None and t.save_path == item.save_path
    assert {TAG, VERIFYING} <= t.tags
    assert set(t.files) == {
        "Dragon de feu/Corps entier.stl",
        "Dragon de feu/Têtes/tête ouverte.stl",
    }
    assert (item.path / "Corps entier.stl").exists()  # the user's files keep their names


def test_the_nfo_lists_name_count_size_formats_and_every_file(tmp_path: Path) -> None:
    files = upload_files(dragon_pack(tmp_path), "Dragon.NOTAG.[PACK].STL", IGNORE)

    nfo = nfo_3d("Dragon.NOTAG.[PACK].STL", files)

    assert "Fichiers ....... : 2" in nfo
    assert "Taille totale .. : 2.1 Ko" in nfo
    assert "Format ......... : STL" in nfo
    assert "Tetes/tete.ouverte.stl" in nfo and "Corps.entier.stl" in nfo


def test_the_draft_carries_category_files_in_base64_and_empty_metadata() -> None:
    body = draft_body("T", "D", 10, Subcategory3D.PACK, b"d4:infoe", "nfo")

    assert body["categoryId"] == 10 and body["subcategoryId"] == 53
    assert base64.b64decode(body["torrentFileData"]) == b"d4:infoe"
    assert base64.b64decode(body["nfoFileData"]) == b"nfo"
    assert body["torrentFileName"] == "T.torrent" and body["nfoFileName"] == "T.nfo"
    assert body["options"] == {} and body["tmdbData"] is None


def test_bencode_sorts_dictionary_keys() -> None:
    assert bencode({"b": 1, "a": [b"x", "y"]}) == b"d1:al1:x1:ye1:bi1ee"


def test_an_upload_keeps_its_files_saves_the_draft_then_seeds(tmp_path: Path) -> None:
    from torrentlinker.upload import create_upload, seed_upload

    item = vise(tmp_path)
    store, qbit = Store(tmp_path / "s.db"), FakeQbit()
    sent: list[dict[str, object]] = []

    def save_draft(body: dict[str, object]) -> int:
        sent.append(body)
        return 128232

    prepared = create_upload(
        item,
        "Petit.Etau.De.Bureau.NOTAG.3MF",
        Subcategory3D.OBJECTS,
        ANNOUNCE,
        IGNORE,
        tmp_path / "uploads",
        save_draft,
        store,
        now=lambda: 50.0,
    )
    h = seed_upload(qbit, store, item, prepared)

    assert (tmp_path / "uploads" / "Petit.Etau.De.Bureau.NOTAG.3MF.torrent").exists()
    assert (tmp_path / "uploads" / "Petit.Etau.De.Bureau.NOTAG.3MF.nfo").exists()
    assert sorted(p.name for p in item.path.parent.iterdir()) == ["Petit étau de bureau.3mf"]
    assert sent[0]["categoryId"] == 10 and sent[0]["subcategoryId"] == 51
    assert store.uploads()[0].draft_id == 128232
    assert h == prepared.meta.infohash
    t = qbit.torrent(h)
    assert t is not None and set(t.files) == {"Petit étau de bureau.3mf"}


def test_no_announce_url_means_no_upload(tmp_path: Path) -> None:
    from torrentlinker.upload import create_upload

    with pytest.raises(ValueError, match="Announce URL"):
        create_upload(
            vise(tmp_path),
            "T",
            Subcategory3D.OBJECTS,
            "",
            IGNORE,
            tmp_path / "uploads",
            lambda body: 1,
            Store(tmp_path / "s.db"),
        )
