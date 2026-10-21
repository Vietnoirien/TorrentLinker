from pathlib import Path

from torrentlinker.domain import LocalItem
from torrentlinker.indexer import Candidate
from torrentlinker.matching import IgnoreList, MatchRules
from torrentlinker.review import candidate_key, check_candidates
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

    results = check_candidates(NoFetch(), ITEM, [rejected], RULES, store.rejections(ITEM.path))  # type: ignore[arg-type]

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


def test_zen_of_a_match_counts_the_user_among_its_seeders_at_seed_age_zero() -> None:
    import pytest

    from torrentlinker.matching import Match
    from torrentlinker.review import CheckedCandidate, match_zen
    from torrentlinker.zen import GB, ZenClass, ZenProfile, ZenTorrent, estimate

    profile = ZenProfile(ZenClass.TANKER)
    matched = CheckedCandidate(
        Candidate("film", 4 * GB, "u", seeders=99), match=Match({"a": "a"}, [], [], 1.0)
    )
    unmatched = CheckedCandidate(Candidate("other", 40 * GB, "u", seeders=99))

    zen = match_zen(profile, [matched, unmatched])

    assert zen == pytest.approx(estimate(profile, [ZenTorrent(4 * GB, 100, 0)]).total)
    assert zen == pytest.approx(1.35 / 7)  # rarity .35 needs 41+ seeders, the user included
    assert match_zen(profile, [unmatched]) is None


# Remembered search results -----------------------------------------------------


def offline_indexer(store: Store, api_key: str = "S3CRET-KEY"):  # type: ignore[no-untyped-def]
    """An Indexer whose network fails the test if it is ever used."""
    import httpx

    from torrentlinker.indexer import Indexer

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network used: {request.url}")

    return Indexer(
        "https://c411.example/api/torznab",
        api_key,
        http=httpx.Client(transport=httpx.MockTransport(no_network)),
        cache=store,
    )


def test_last_candidates_are_remembered_per_local_item_without_the_api_key(
    tmp_path: Path,
) -> None:
    from torrentlinker.review import remember_candidates, remembered_candidates

    store = Store(tmp_path / "s.db")
    indexer = offline_indexer(store)
    found = [Candidate("Zweig.EPUB", 100, "https://c411.example/dl/42?apikey=S3CRET-KEY", 7)]

    remember_candidates(store, indexer, ITEM.path, found)

    assert remembered_candidates(store, indexer, ITEM.path) == found
    assert remembered_candidates(store, indexer, Path("/lib/other")) is None
    assert b"S3CRET-KEY" not in (tmp_path / "s.db").read_bytes()


def test_remembered_candidates_are_compared_again_from_cached_torrents_only(
    tmp_path: Path,
) -> None:
    import hashlib

    from tests.torrents import make_torrent
    from torrentlinker.review import restore_checked

    lib = tmp_path / "lib"
    lib.mkdir()
    local = lib / "Le joueur d'echecs - Stefan Zweig.epub"
    local.write_bytes(b"z" * 67163)
    item = LocalItem(local, {local.name: 67163})
    store = Store(tmp_path / "s.db")
    indexer = offline_indexer(store)
    fetched = Candidate("Zweig.2013.EPUB", 67163, "https://c411.example/dl/1?apikey=S3CRET-KEY")
    never_fetched = Candidate("Zweig.Integrale", 9_000_000, "https://c411.example/dl/2")
    key = hashlib.sha1(indexer.redact(fetched.download_url).encode()).hexdigest()
    store.cache_torrent(key, make_torrent(local))

    checked = restore_checked(indexer, item, [fetched, never_fetched], RULES)

    assert checked[0].match is not None and checked[0].match.is_full
    assert not checked[1].compared
