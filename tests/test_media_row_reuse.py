"""One Media page asks for a dozen listings of the same library; it builds their rows once."""

import json
import types

from torrentlinker.media import ROWS_HELD, MediaLibrary


def library(tmp_path, count, clock):
    agent = types.SimpleNamespace(setup=types.SimpleNamespace(path=tmp_path / "settings.json"))
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
