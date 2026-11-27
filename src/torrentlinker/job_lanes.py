"""Explicit read-only jobs may bypass serialized batch and mutation work."""

INTERACTIVE = frozenset(
    {
        "check",
        "library-review",
        "check-candidate",
        "details",
        "library-evidence",
        "find-compatible",
        "search",
        "search-options",
        "search-search",
        "search-search-options",
    }
)
# The film index fills for hours, so it has its own worker: it must not hold up the batch lane.
FILMS = frozenset({"films-index"})
# The series index too, apart from the films: its first sync parses ~200,000 release names.
SERIES = frozenset({"series-index"})
BACKGROUND = frozenset(
    {"check-all", "reseed-all", "search-library", "plan", "catalogue", "reseed-workspace"}
)
READ_INSPECTOR_ACTIONS = frozenset(
    {"review", "check", "search", "repairs", "provenance", "evidence", "details"}
)


def job_lane(kind: str, parameters: dict | None = None) -> str:
    parameters = parameters or {}
    if kind in INTERACTIVE:
        return "interactive"
    if kind in FILMS:
        return "films"
    if kind in SERIES:
        return "series"
    if (
        kind == "candidate-inspector"
        and parameters.get("inspector_action", "review") in READ_INSPECTOR_ACTIONS
    ):
        return "interactive"
    if kind == "search-library" and len(parameters.get("paths", [])) == 1:
        return "interactive"
    return "batch"
