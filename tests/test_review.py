from pathlib import Path

from torrentlinker.domain import LocalItem
from torrentlinker.indexer import Candidate
from torrentlinker.matching import IgnoreList
from torrentlinker.review import MatchRules, candidate_key, verify
from torrentlinker.store import Store

RULES = MatchRules(0.02, 0.5, IgnoreList.default())
ITEM = LocalItem(Path("/lib/x.epub"), {"x.epub": 100})


class NoFetch:
    """An Indexer that must not be asked for any .torrent."""

    def fetch_torrent(self, candidate: Candidate) -> bytes:
        raise AssertionError(f"fetched {candidate.title}")


def test_rejected_candidates_are_dropped_before_anything_is_fetched(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    rejected = Candidate("bad", 100, "https://t/dl/1?apikey=K", infohash="aa" * 20)
    store.reject(ITEM.path, candidate_key(rejected), "Rejected by user")

    results = verify(NoFetch(), ITEM, [rejected], RULES, store.rejections(ITEM.path))  # type: ignore[arg-type]

    assert results == []


def test_candidate_key_prefers_the_info_hash_and_never_contains_the_api_key() -> None:
    with_hash = Candidate("a", 1, "https://t/dl/1?apikey=K", infohash="ab" * 20)
    without = Candidate("b", 1, "https://t/dl/2?apikey=K", details_url="https://t/torrents/2")

    assert candidate_key(with_hash) == "ab" * 20
    assert candidate_key(without) == "https://t/torrents/2"


class RecordingIndexer:
    def __init__(self, answers: list[list[Candidate]]) -> None:
        self.answers = answers
        self.queries: list[object] = []

    def search(self, query: object) -> list[Candidate]:
        self.queries.append(query)
        return self.answers.pop(0)


def test_search_falls_back_to_the_name_when_the_id_search_finds_nothing() -> None:
    from torrentlinker.domain import ContentKind
    from torrentlinker.review import search_candidates

    item = LocalItem(Path("/lib/Amélie (2001) {imdb-tt0211915}"), {})
    hit = Candidate("Amelie.2001.FRENCH.1080p", 100, "u")
    indexer = RecordingIndexer([[], [hit]])

    found = search_candidates(indexer, item, ContentKind.MOVIE, (), None)  # type: ignore[arg-type]

    assert found == [hit]
    assert [q.imdbid for q in indexer.queries] == ["0211915", None]
