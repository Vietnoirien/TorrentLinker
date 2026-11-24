"""One category chosen in Search, expressed for each Tracker (ADR-0025).

c411 and tr4ker do not cut their catalogues the same way, so a pill cannot always become one
request parameter on both. c411 keeps films, series, documentaries and concerts in a single
`Films & Vidéos` root; tr4ker splits them into `films` and `series`. c411 has a `GPS` root
tr4ker has nothing for, and tr4ker has `formations` and `autres` that c411 lacks.

A choice therefore resolves to one of three answers, which Search reports rather than hides:

  `server`  one `cat=` slug covers it, so tr4ker narrows its own catalogue
  `page`    no single slug covers it; tr4ker answers unnarrowed and its rows are kept here
  `none`    tr4ker has no such category; it has nothing to contribute

c411's own root and child IDs come from its live tree (`search_indexer_options`); the slugs
are tr4ker's, from `/api/public/categories`. Both were read from a live instance on
24 November 2026. A category neither side knows about resolves to `page`, never to a wrong
slug: narrowing the wrong catalogue is worse than narrowing none.
"""

from __future__ import annotations

from typing import Literal

Scope = Literal["server", "page", "none"]

# c411 native root ID -> the tr4ker root slugs that cover it.
ROOTS: dict[int, tuple[str, ...]] = {
    1: ("films", "series"),  # Films & Vidéos: tr4ker splits this one
    2: ("livres",),  # Ebook
    3: ("audio",),
    4: ("applications",),
    5: ("jeux-video",),
    6: ("emulation",),
    7: (),  # GPS: tr4ker has no equivalent
    8: ("porno",),  # XXX
    9: ("nulled",),
    10: ("impression-3d",),  # Imprimante 3D
}

# c411 child ID (negative, as its tree numbers them) -> the one tr4ker slug that covers it.
# These are what let `Films & Vidéos` resolve to a single slug once narrowed: picking
# `Série TV` is `cat=series`, picking `Film` is `cat=films`. `Collection` spans both and is
# deliberately absent.
CHILDREN: dict[int, str] = {
    -1: "films",  # Animation
    -2: "series",  # Animation Série
    -3: "films",  # Concert
    -4: "films",  # Documentaire
    -5: "series",  # Emission TV
    -6: "films",  # Film
    -7: "series",  # Série TV
    -8: "films",  # Spectacle
    -9: "films",  # Sport
    -10: "films",  # Vidéo-clips
    -57: "series",  # Série Documentaire
}


def tr4ker_category(category: int | None) -> tuple[Scope, str, tuple[str, ...]]:
    """How tr4ker should be asked for `category`: its scope, its `cat=` slug and the slugs
    the choice covers.

    `category` is a c411 native ID as Search sends it: None for every category, a positive
    root, or a negative child. The slug is empty unless the scope is `server`; the covered
    slugs are what a `page` scope keeps its rows by.
    """
    if category is None:
        return "server", "", ()
    if (child := CHILDREN.get(category)) is not None:
        return "server", child, (child,)
    slugs = ROOTS.get(category)
    if slugs is None:
        # An unknown ID: a c411 child we have not mapped, or a tree that has changed. Ask for
        # everything and keep what matches nothing, rather than send a slug that may be wrong.
        return "page", "", ()
    if not slugs:
        return "none", "", ()
    if len(slugs) == 1:
        return "server", slugs[0], slugs
    return "page", "", slugs


def covers(category: int | None, parent_slug: str) -> bool:
    """Whether a tr4ker row in `parent_slug` belongs to `category`, for the rows Search keeps
    itself when no single slug covered the choice."""
    scope, _, slugs = tr4ker_category(category)
    if scope == "server":
        return True  # tr4ker already narrowed it
    if scope == "none":
        return False
    return not slugs or parent_slug in slugs
