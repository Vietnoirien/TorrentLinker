"""One Media page asks for a dozen listings of the same library; it builds their rows once."""

import json
import types

from torrentlinker.media import ROWS_HELD, SETUP_HELD, MediaLibrary


def library(tmp_path, count, clock):
    agent = types.SimpleNamespace(
        setup=types.SimpleNamespace(path=tmp_path / "settings.json"),
        # What `incomplete_paths` asks for: the Torrent Client's observed torrents.
        for_client=lambda client_id: types.SimpleNamespace(
            observed=[],
            setup=types.SimpleNamespace(settings=types.SimpleNamespace(path_mappings=[])),
        ),
    )
    media = MediaLibrary(agent, clock=clock)
    with media.db:
        for number in range(count):
            body = {
                "kind": "video",
                "title": f"Film {number}",
                "year": "2020",
                "series": "",
                "description": "",
                "identity_source": "filename",
                "content_id": str(number),
                "artwork": "",
            }
            media.db.execute(
                "INSERT INTO media_items VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(number),
                    "default",
                    f"/films/{number}.mkv",
                    "/films",
                    1,
                    1,
                    0,
                    json.dumps(body),
                ),
            )
    folder = types.SimpleNamespace(path=types.SimpleNamespace(absolute=lambda: "/films"), kind=None)
    settings = types.SimpleNamespace(
        library_folders=[folder], adult_content=False, client="qbittorrent", path_mappings=[]
    )
    media.setup = lambda client_id: types.SimpleNamespace(settings=settings)
    media.visibility = lambda client_id, actor: lambda record: True
    return media


def counted(media):
    """Count the rows built, without changing what `row` returns."""
    built = []
    original = media.row

    def row(record, **kwargs):
        built.append(record["id"])
        return original(record, **kwargs)

    media.row = row
    return built


def test_listings_of_one_library_share_the_rows_they_built(tmp_path):
    now = [100.0]
    count = 40
    media = library(tmp_path, count, lambda: now[0])
    built = counted(media)

    media.listing("default", kind="", view="all", limit=5)
    assert len(built) >= count, "the first listing builds a row for every record"

    # A warm listing costs what its page shows, not what the library holds: the page reads
    # each row it displays again, and one alternative release for an unavailable one.
    built.clear()
    media.listing("default", kind="video", view="all", limit=5)
    media.listing("default", kind="video", view="films", limit=5)
    assert 0 < len(built) < count, f"a warm listing rebuilt {len(built)} of {count} rows"

    # The window is short because the player writes a position every second.
    built.clear()
    now[0] += ROWS_HELD + 0.1
    media.listing("default", kind="video", view="all", limit=5)
    assert len(built) >= count, "past the window the rows are built again"


def test_a_changed_library_is_not_served_from_the_kept_rows(tmp_path):
    now = [100.0]
    media = library(tmp_path, 4, lambda: now[0])
    assert media.listing("default", kind="", view="all", limit=50)["total"] == 4
    with media.db:
        media.db.execute(
            "INSERT INTO media_items VALUES (?,?,?,?,?,?,?,?)",
            (
                "99",
                "default",
                "/films/99.mkv",
                "/films",
                1,
                1,
                0,
                json.dumps(
                    {
                        "kind": "video",
                        "title": "Film 99",
                        "year": "2021",
                        "series": "",
                        "description": "",
                        "identity_source": "filename",
                        "content_id": "99",
                        "artwork": "",
                    }
                ),
            ),
        )
    # Within the window, but a new record is a different set of rows.
    assert media.listing("default", kind="", view="all", limit=50)["total"] == 5


def test_a_listing_does_not_copy_the_settings_once_per_item(tmp_path):
    """`row` reads which Torrent Client this is, and `Settings.for_client` deep-copies the
    whole settings object. Asking once per item cost a listing of 873 items 2.8 s of its
    3.1 s, so the copy is kept for the page that needs it."""
    now = [100.0]
    media = library(tmp_path, 30, lambda: now[0])
    copies = []

    settings = types.SimpleNamespace(
        library_folders=[
            types.SimpleNamespace(path=types.SimpleNamespace(absolute=lambda: "/films"), kind=None)
        ],
        adult_content=False,
        client="qbittorrent",
        path_mappings=[],
        default_client_id="default",
    )
    settings.profile = lambda client_id: None
    media.agent = types.SimpleNamespace(
        setup=types.SimpleNamespace(settings=settings),
        for_client=lambda client_id: (
            copies.append(client_id)
            or types.SimpleNamespace(setup=types.SimpleNamespace(settings=settings), observed=[])
        ),
    )
    del media.setup  # use the real one again, not the fixture's stub
    media._setups.clear()

    # A listing asks for this client twice however many items it holds: once for the Settings
    # copy, kept for SETUP_HELD, and once for the Torrent Client's observed torrents. What
    # matters is that neither is per item.
    media.listing("default", kind="", view="all", limit=5)
    first = len(copies)
    assert first <= 2, f"asked for the client {first} times for 30 items"

    media.listing("default", kind="video", view="all", limit=5)
    assert len(copies) <= first + 1, "a second listing reuses the Settings copy"

    before = len(copies)
    now[0] += SETUP_HELD + 0.1
    media.listing("default", kind="video", view="all", limit=5)
    assert len(copies) > before, "past the window Settings is read again"


def test_stored_png_posters_are_re_encoded_after_an_update(tmp_path):
    """Posters became WebP and readers take either suffix, so what is already stored is
    converted in the background rather than left for someone to run a script."""
    from io import BytesIO

    from PIL import Image

    media = library(tmp_path, 1, lambda: 100.0)
    picture = BytesIO()
    Image.new("RGB", (500, 750), (90, 120, 160)).save(picture, format="PNG")
    folder = tmp_path / "media-artwork"
    folder.mkdir()
    import hashlib

    digest = hashlib.sha256(picture.getvalue()).hexdigest()
    (folder / f"{digest}.png").write_bytes(picture.getvalue())
    with media.db:
        media.db.execute(
            "INSERT INTO media_options VALUES (?,?)",
            ("tracker-new:default:x", f'{{"artwork": "asset:{digest}.png"}}'),
        )
    media.agent = types.SimpleNamespace(setup=types.SimpleNamespace(path=tmp_path / "s.json"))

    assert media.convert_png_masters() == 1
    assert not (folder / f"{digest}.png").exists(), "the PNG goes once its replacement is in"
    assert (folder / f"{digest}.webp").is_file()
    body = media.db.execute(
        "SELECT body FROM media_options WHERE key='tracker-new:default:x'"
    ).fetchone()[0]
    assert f"asset:{digest}.webp" in body and ".png" not in body
    assert media.convert_png_masters() == 0, "nothing left to do on the next start"


def test_the_home_can_be_asked_for_the_library_without_the_tracker(tmp_path):
    """Reading what c411 has takes about as long as every library shelf together, so a page
    asks for the library first and for the tracker after."""
    media = library(tmp_path, 6, lambda: 100.0)
    asked = []
    media.tracker_rows = lambda client_id, setup: asked.append(client_id) or {}

    media.home_rows("default", kind="video", limit=5, scope="home", include="library")
    assert asked == [], "the library shelves must not wait on the tracker"

    media.home_rows("default", kind="video", limit=5, scope="home", include="tracker")
    assert asked == ["default"], "asked for on its own, once"

    media.home_rows("default", kind="video", limit=5, scope="home")
    assert asked == ["default", "default"], "one request for both still works"


def test_a_page_walks_the_clients_torrents_once_not_once_per_row(tmp_path):
    """`resolve` asks which files are unfinished, and a page resolves every row it shows plus
    an alternative for each unavailable one. That set is kept against the identity of the
    client's observed list, which a refresh replaces every fifteen seconds, so a page used to
    walk all of the client's torrents again and again — 30 ms at 11,766 of them."""
    now = [100.0]
    media = library(tmp_path, 8, lambda: now[0])
    walks = []

    class Counted(list):
        def __iter__(self):
            walks.append(1)
            return super().__iter__()

    media.agent = types.SimpleNamespace(
        setup=types.SimpleNamespace(path=tmp_path / "settings.json"),
        # A new list each time, as a refresh of the Torrent Client makes it.
        for_client=lambda client_id: types.SimpleNamespace(
            observed=Counted(),
            setup=types.SimpleNamespace(settings=types.SimpleNamespace(path_mappings=[])),
        ),
    )

    media.listing("default", kind="", view="all", limit=8)
    assert len(walks) == 1, f"a page walked the client's torrents {len(walks)} times"
