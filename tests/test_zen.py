import pytest

from torrentlinker.zen import (
    GB,
    ZenClass,
    ZenProfile,
    ZenTorrent,
    class_bonus,
    compare_classes,
    duration_bonus,
    estimate,
    is_indexer_torrent,
    rarity_bonus,
    tree_bonus,
    weight,
)

TANKER = ZenProfile(ZenClass.TANKER)
KEEPER = ZenProfile(ZenClass.SWARM_KEEPER)


def film(seeders: int = 100, days: float = 90, size: float = 4 * GB) -> ZenTorrent:
    return ZenTorrent(size=int(size), seeders=seeders, seed_days=days)


def test_guide_worked_example_tanker_fifteen_films_of_4_gb_earns_about_4_a_day() -> None:
    day = estimate(TANKER, [film() for _ in range(15)])

    assert day.notes[0] == pytest.approx(1.7)
    assert day.total == pytest.approx(1.7 * 15 * 1.05 / 7)
    assert day.paid == 4


@pytest.mark.parametrize(
    ("size", "expected"),
    [(1 * GB, 0.29), (4 * GB, 1.0), (25 * GB, 1.24), (5_000_000, 0.06)],
)
def test_size_weight_matches_the_guide(size: float, expected: float) -> None:
    assert weight(int(size)) == pytest.approx(expected, abs=0.006)


def test_weight_keeps_rising_slowly_beyond_25_gb() -> None:
    assert weight(60 * GB) == pytest.approx(1.38)
    assert weight(95 * GB) > weight(60 * GB)


def test_seed_age_bonus_grows_by_steps() -> None:
    assert [duration_bonus(d) for d in (0, 6.9, 7, 30, 90, 180)] == [0, 0, 0.1, 0.25, 0.35, 0.5]


def test_rarity_depends_on_class_size_and_seeders() -> None:
    assert rarity_bonus(ZenClass.TANKER, 4 * GB, 40) == 0  # too few seeders for a Tanker
    assert rarity_bonus(ZenClass.TANKER, 4 * GB, 100) == 0.35
    assert rarity_bonus(ZenClass.TANKER, 60 * GB, 100) == 0.5
    assert rarity_bonus(ZenClass.TANKER, 60 * GB, 220) == 0.35
    assert rarity_bonus(ZenClass.TANKER, 4 * GB, 300) == 0
    assert rarity_bonus(ZenClass.SWARM_KEEPER, 4 * GB, 5) == 0.35
    assert rarity_bonus(ZenClass.SWARM_KEEPER, 0.5 * GB, 30) == 0
    assert rarity_bonus(ZenClass.SWARM_KEEPER, 20 * GB, 8) == 0.5


def test_class_bonus_grows_with_the_number_of_torrents() -> None:
    assert class_bonus(ZenClass.TANKER, 14) == 0
    assert class_bonus(ZenClass.TANKER, 15) == 0.05
    assert class_bonus(ZenClass.TANKER, 750) == pytest.approx(0.35)
    assert class_bonus(ZenClass.TANKER, 5000) == pytest.approx(0.35)
    assert class_bonus(ZenClass.SWARM_KEEPER, 10) == 0.2


def test_tree_bonus_is_capped_at_5_percent() -> None:
    assert tree_bonus(ZenClass.TANKER, 1000, 2.0) == 0.05
    assert tree_bonus(ZenClass.TANKER, 50, 2.0) == 0
    assert tree_bonus(ZenClass.SWARM_KEEPER, 100, 1.4) == 0
    assert tree_bonus(ZenClass.SWARM_KEEPER, 100, 1.5) == 0.01


def test_tree_bonus_already_unlocked_on_c411_is_kept() -> None:
    unlocked = ZenProfile(ZenClass.TANKER, tree_bonus=0.03)

    assert estimate(unlocked, [film()]).multiplier == pytest.approx(1.03)


def test_seed_time_is_prorated_and_under_30_minutes_counts_nothing() -> None:
    full = estimate(TANKER, [film()]).total

    assert estimate(ZenProfile(ZenClass.TANKER, seed_hours=12), [film()]).total == pytest.approx(
        full / 2
    )
    assert estimate(ZenProfile(ZenClass.TANKER, seed_hours=0.4), [film()]).total == 0


def test_each_torrent_estimate_adds_up_to_the_total() -> None:
    day = estimate(KEEPER, [film(3), film(30, 10), film(200, 400, 40 * GB)])

    assert sum(day.per_torrent) == pytest.approx(day.total)


def test_groups_of_torrents_with_the_same_bonuses_are_rounded_separately() -> None:
    group = [film(100, 90) for _ in range(2)]  # note 1.7: 0.49/day, paid 0
    other = [film(100, 200) for _ in range(2)]  # note 1.85: 0.53/day, paid 1
    day = estimate(TANKER, group + other)

    assert day.paid == 1 == round(sum(day.per_torrent[:2])) + round(sum(day.per_torrent[2:]))


def test_a_reuploader_earns_nothing_from_seeding_and_a_rough_amount_per_upload() -> None:
    reup = ZenProfile(ZenClass.REUPLOADER)

    assert estimate(reup, [film()]).total == 0
    assert estimate(reup, [], uploads=10).total == pytest.approx(4.3)


def test_c411_torrents_are_recognised_by_their_tracker_host() -> None:
    url = "https://c411.org/api/torznab"
    assert is_indexer_torrent("https://tracker.c411.org/announce/abc", url)
    assert is_indexer_torrent("c411.org", url)
    assert not is_indexer_torrent("udp://tracker.opentrackr.org:1337/announce", url)
    assert not is_indexer_torrent("", url)


def test_class_comparison_estimates_the_same_seeding_in_every_class() -> None:
    torrents = [film(5, 200, 8 * GB) for _ in range(20)]  # few seeders: Swarm Keeper land
    profile = ZenProfile(ZenClass.TANKER, tree_bonus=0.05)

    days = compare_classes(profile, torrents, uploads=3)

    assert days[ZenClass.TANKER].total == estimate(profile, torrents).total
    assert days[ZenClass.SWARM_KEEPER].total > days[ZenClass.TANKER].total
    assert days[ZenClass.SWARM_KEEPER].multiplier == 1 + class_bonus(ZenClass.SWARM_KEEPER, 20)
    assert days[ZenClass.REUPLOADER].total == pytest.approx(3 * 0.43)
