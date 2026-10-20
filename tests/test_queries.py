from pathlib import Path

from torrentlinker.domain import LocalItem
from torrentlinker.queries import name_query

EBOOK = LocalItem(
    Path("/windocs/E-Book/Le joueur d'echecs - Stefan Zweig.epub"),
    {"Le joueur d'echecs - Stefan Zweig.epub": 67163},
)


def test_name_query_drops_extension_and_separators() -> None:
    assert name_query(EBOOK) == "Le joueur d'echecs Stefan Zweig"


def test_name_query_turns_scene_dots_into_spaces_and_drops_bracket_tags() -> None:
    item = LocalItem(Path("/lib/Some.Movie.2020.1080p.[FR]-GRP"), {})
    assert name_query(item) == "Some Movie 2020 1080p GRP"


def test_name_query_keeps_a_year_written_in_parentheses() -> None:
    assert name_query(LocalItem(Path("/lib/Amélie (2001)"), {})) == "Amélie 2001"


# Content Kinds and IDs ------------------------------------------------------

from torrentlinker.domain import ContentKind  # noqa: E402
from torrentlinker.indexer import SearchQuery  # noqa: E402
from torrentlinker.queries import MediaIds, build_queries, find_ids  # noqa: E402

FULL_CAPS = {
    "search": {"q"},
    "movie": {"q", "imdbid", "tmdbid"},
    "tvsearch": {"q", "season", "ep", "imdbid", "tmdbid"},
    "book": {"q"},
    "music": {"q"},
}


def test_movie_with_an_imdb_id_is_searched_by_id_then_by_name() -> None:
    item = LocalItem(Path("/lib/Amélie (2001) {imdb-tt0211915}"), {})

    queries = build_queries(item, ContentKind.MOVIE, (2000,), find_ids(item), FULL_CAPS)

    assert queries == [
        SearchQuery(mode="movie", imdbid="0211915", categories=(2000,)),
        SearchQuery(q="Amélie 2001", mode="movie", categories=(2000,)),
    ]


def test_imdb_id_is_read_from_an_nfo_inside_the_item(tmp_path: Path) -> None:
    movie = tmp_path / "Amelie"
    movie.mkdir()
    (movie / "movie.nfo").write_text("https://www.imdb.com/title/tt0211915/", encoding="utf-8")
    item = LocalItem(movie, {"Amelie/movie.nfo": 37, "Amelie/movie.mkv": 10})

    assert find_ids(item) == MediaIds(imdb="tt0211915")


def test_tmdb_id_is_used_when_there_is_no_imdb_id() -> None:
    item = LocalItem(Path("/lib/Amelie.2001.1080p.mkv"), {"Amelie.2001.1080p.mkv": 1})

    queries = build_queries(item, ContentKind.MOVIE, (), MediaIds(tmdb="194"), FULL_CAPS)

    assert queries[0] == SearchQuery(mode="movie", tmdbid="194")
    assert queries[1] == SearchQuery(q="Amelie 2001", mode="movie")


def test_season_pack_is_searched_by_title_and_season() -> None:
    item = LocalItem(Path("/lib/The.Show.S02.1080p.WEB-GRP"), {})

    queries = build_queries(item, ContentKind.SERIES, (5000,), MediaIds(), FULL_CAPS)

    assert queries == [SearchQuery(q="The Show", mode="tvsearch", categories=(5000,), season=2)]


def test_single_episode_is_searched_with_season_and_episode() -> None:
    item = LocalItem(Path("/lib/The.Show.S02E05.mkv"), {"The.Show.S02E05.mkv": 1})

    queries = build_queries(item, ContentKind.SERIES, (), MediaIds(imdb="tt1234567"), FULL_CAPS)

    assert queries[0] == SearchQuery(mode="tvsearch", imdbid="1234567", season=2, ep=5)


def test_ebook_is_searched_by_name_in_book_mode() -> None:
    queries = build_queries(EBOOK, ContentKind.EBOOK, (7000,), MediaIds(), FULL_CAPS)

    assert queries == [
        SearchQuery(q="Le joueur d'echecs Stefan Zweig", mode="book", categories=(7000,))
    ]


def test_3d_models_use_a_plain_name_search() -> None:
    item = LocalItem(Path("/lib/Artist - Patreon Release 2024-03"), {})

    queries = build_queries(item, ContentKind.MODEL_3D, (), MediaIds(), FULL_CAPS)

    assert queries == [SearchQuery(q="Artist Patreon Release 2024 03")]


def test_modes_and_parameters_the_indexer_lacks_fall_back_to_a_name_search() -> None:
    item = LocalItem(Path("/lib/Amélie (2001) {imdb-tt0211915}"), {})

    queries = build_queries(item, ContentKind.MOVIE, (), find_ids(item), {"search": {"q"}})

    assert queries == [SearchQuery(q="Amélie 2001")]


def test_default_categories_per_kind_come_from_the_indexer_caps() -> None:
    from torrentlinker.queries import default_categories

    caps = {2000: "Films", 2030: "Films étrangers", 5000: "Séries", 7000: "Ebook", 3000: "Audio"}

    cats = default_categories(caps)

    assert cats[ContentKind.MOVIE] == [2000, 2030]
    assert cats[ContentKind.SERIES] == [5000]
    assert cats[ContentKind.EBOOK] == [7000]
    assert cats[ContentKind.MUSIC] == [3000]
    assert cats[ContentKind.MODEL_3D] == []
