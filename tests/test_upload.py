import base64
import io
from pathlib import Path

import pytest
import torf

from tests.fake_qbit import FakeQbit
from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.indexer import Candidate, SearchQuery
from torrentlinker.matching import IgnoreList
from torrentlinker.reseed import TAG, VERIFYING, start_reseed
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.upload import (
    CATEGORY_3D,
    PROFILES,
    ExistingQuery,
    Judgement,
    MiB,
    Model3DProfile,
    Problem,
    Refusal,
    Subcategory3D,
    UploadRequest,
    UploadStopped,
    UploadWarning,
    bencode,
    category_name,
    default_category,
    draft_body,
    find_existing,
    make_torrent,
    nfo_3d,
    piece_size,
    profile_for,
    seed_match,
    upload_files,
)

IGNORE = IgnoreList.default()
PROFILE = Model3DProfile()
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
    item, objects, pack = vise(tmp_path), Subcategory3D.OBJECTS, Subcategory3D.PACK

    assert PROFILE.suggested_name(item, IGNORE, "", objects) == "Petit.Etau.De.Bureau.NOTAG.3MF"
    assert (
        PROFILE.suggested_name(item, IGNORE, "Printables", objects)
        == "Petit.Etau.De.Bureau.Printables.3MF"
    )
    assert (
        PROFILE.suggested_name(dragon_pack(tmp_path), IGNORE, "My Mini Factory", pack)
        == "Dragon.De.Feu.My.Mini.Factory.[PACK].STL"
    )


def test_archives_and_folders_without_a_3d_file_are_refused(tmp_path: Path) -> None:
    archive = tmp_path / "Model.rar"
    archive.write_bytes(b"r" * 10)
    assert PROFILE.refusals(scan_item(archive), IGNORE) == [
        Refusal(Problem.ARCHIVE, "rar"),
        Refusal(Problem.NO_3D_FILE),
    ]
    assert PROFILE.refusals(vise(tmp_path), IGNORE) == []


def test_3d_judgement_rules_are_warnings_never_refusals(tmp_path: Path) -> None:
    objects, pack = Subcategory3D.OBJECTS, Subcategory3D.PACK
    paid = UploadWarning(Judgement.PAID_CREATORS)
    theme = UploadWarning(Judgement.PACK_THEME)

    assert PROFILE.warnings(vise(tmp_path), IGNORE, objects) == [paid]
    dragons = dragon_pack(tmp_path)
    assert PROFILE.warnings(dragons, IGNORE, pack) == [paid, theme]
    assert PROFILE.refusals(dragons, IGNORE) == []  # they do not block


def test_profiles_are_keyed_by_c411_category_and_a_kind_only_proposes_one(tmp_path: Path) -> None:
    assert isinstance(PROFILES[CATEGORY_3D], Model3DProfile)
    assert PROFILES[CATEGORY_3D].category == CATEGORY_3D == 10
    assert all(p.category == c for c, p in PROFILES.items())
    assert {k: default_category(k) for k in ContentKind} == {
        ContentKind.MOVIE: 1,
        ContentKind.SERIES: 1,
        ContentKind.EBOOK: 2,
        ContentKind.MUSIC: 3,
        ContentKind.GAME: 5,
        ContentKind.MODEL_3D: 10,
        ContentKind.OTHER: None,
    }
    assert isinstance(profile_for(ContentKind.MODEL_3D), Model3DProfile)
    assert profile_for(ContentKind.MOVIE) is None  # category 1 has no profile yet
    assert profile_for(ContentKind.OTHER) is None
    assert category_name(1) == "Films & Vidéos" and category_name(6) == "Emulation"
    assert category_name(10) == "Imprimante 3D" and category_name(99) == "99"
    assert PROFILE.default_subcategory(vise(tmp_path), IGNORE) == Subcategory3D.OBJECTS
    assert PROFILE.default_subcategory(dragon_pack(tmp_path), IGNORE) == Subcategory3D.PACK


def test_the_description_shows_the_image_the_facts_and_a_packs_files(tmp_path: Path) -> None:
    files = upload_files(dragon_pack(tmp_path), "Dragon.NOTAG.[PACK].STL", IGNORE)

    text = PROFILE.description("Dragon.NOTAG.[PACK].STL", files, "", "https://i.example/d.png")

    assert text.startswith("[center][img]https://i.example/d.png[/img][/center]")
    assert "[b]Source :[/b] Inconnue" in text and "[b]Formats :[/b] STL" in text
    assert "[spoiler=Contenu][list]" in text and "[*]Tetes/tete.ouverte.stl" in text
    assert "[img]" not in PROFILE.description("T", files, "", "")


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

    title = "Petit.Etau.De.Bureau.NOTAG.3MF"
    files = upload_files(item, title, IGNORE)
    request = UploadRequest(item, title, files, "my nfo", "my description", 10, 51)
    prepared = create_upload(
        request, ANNOUNCE, tmp_path / "uploads", save_draft, store, now=lambda: 50.0
    )
    h = seed_upload(qbit, store, item, prepared)

    assert (tmp_path / "uploads" / "Petit.Etau.De.Bureau.NOTAG.3MF.torrent").exists()
    assert (tmp_path / "uploads" / "Petit.Etau.De.Bureau.NOTAG.3MF.nfo").exists()
    assert sorted(p.name for p in item.path.parent.iterdir()) == ["Petit étau de bureau.3mf"]
    assert sent[0]["categoryId"] == 10 and sent[0]["subcategoryId"] == 51
    assert sent[0]["description"] == "my description"
    assert base64.b64decode(sent[0]["nfoFileData"]) == b"my nfo"  # type: ignore[arg-type]
    assert store.uploads()[0].draft_id == 128232
    assert h == prepared.meta.infohash
    t = qbit.torrent(h)
    assert t is not None and set(t.files) == {"Petit étau de bureau.3mf"}


def test_no_announce_url_means_no_upload(tmp_path: Path) -> None:
    from torrentlinker.upload import create_upload

    with pytest.raises(ValueError, match="Announce URL"):
        item = vise(tmp_path)
        request = UploadRequest(item, "T", upload_files(item, "T", IGNORE), "n", "d", 10, 51)
        create_upload(request, "", tmp_path / "uploads", lambda body: 1, Store(tmp_path / "s.db"))


def test_a_profile_queries_c411_by_the_title_words_of_its_item(tmp_path: Path) -> None:
    query = PROFILE.existing_query(vise(tmp_path), IGNORE)

    assert query == ExistingQuery("Petit étau de bureau")
    assert query.ids == {}


def test_existing_releases_are_searched_in_the_category_by_name() -> None:
    asked: list[SearchQuery] = []
    found = [Candidate("Vise.NOTAG.STL", 10, "d", seeders=1), Candidate("Vise.Pro.STL", 5, "d", 9)]

    def search(q: SearchQuery) -> list[Candidate]:
        asked.append(q)
        return found

    result = find_existing(search, ExistingQuery("Vise"), CATEGORY_3D)

    assert [q.params()["q"] for q in asked] == ["Vise"]
    assert asked[0].categories == (8010,)  # c411's 3D category, as Torznab numbers it
    assert [c.title for c in result] == ["Vise.Pro.STL", "Vise.NOTAG.STL"]  # most seeded first


def test_an_ids_query_goes_to_the_ids_lookup_when_there_is_one() -> None:
    def never(q: SearchQuery) -> list[Candidate]:
        raise AssertionError("searched by name")

    query = ExistingQuery("Dune", {"tmdbId": "438631", "tmdbType": "movie"})
    seen: list[dict[str, str]] = []

    def by_ids(ids: dict[str, str]) -> list[Candidate]:
        seen.append(ids)
        return [Candidate("Dune.2021", 1, "d")]

    assert [c.title for c in find_existing(never, query, 1, by_ids)] == ["Dune.2021"]
    assert seen == [query.ids]


def test_an_ids_query_without_a_lookup_falls_back_to_its_name() -> None:
    asked: list[SearchQuery] = []

    def search(q: SearchQuery) -> list[Candidate]:
        asked.append(q)
        return []

    find_existing(search, ExistingQuery("Dune", {"tmdbId": "1"}), 1)

    assert asked[0].params()["q"] == "Dune"
