"""Organisation: Jellyfin names from templates (the board and Ranger are in test_ranger)."""

from __future__ import annotations

import pytest

from torrentlinker.organisation import DEFAULTS, example, fill, template_error


def test_the_default_templates_give_the_jellyfin_layout():
    film = {"titre": "Dune", "année": "2021", "tmdbid": "438631"}
    assert fill(DEFAULTS["film"], film) == ["Dune (2021) [tmdbid-438631]"] * 2
    series = {"titre": "Severance", "année": "2022", "saison": "01", "épisode": "03"}
    assert fill(DEFAULTS["series"], series) == ["Severance (2022)", "Saison 01", "Severance S01E03"]


def test_a_missing_id_or_year_drops_its_group_and_a_colon_becomes_a_dash():
    assert (
        fill(DEFAULTS["film"], {"titre": "Dune: Part Two", "année": "2024"})
        == ["Dune - Part Two (2024)"] * 2
    )
    assert fill("{titre} ({année})", {"titre": "Dune"}) == ["Dune"]


@pytest.mark.parametrize(
    ("template", "fragment"),
    [("{titre}/{nope}", "Unknown token"), ("{année}", "{titre}"), ("../{titre}", "Invalid"),
     ("{titre}/a/b/c", "Three levels")],
)  # fmt: skip
def test_a_bad_template_says_why(template, fragment):
    assert fragment in template_error(template)
    assert example(template, "film") == ""
