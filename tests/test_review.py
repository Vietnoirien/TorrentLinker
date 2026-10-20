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
