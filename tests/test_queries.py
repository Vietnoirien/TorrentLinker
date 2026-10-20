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
