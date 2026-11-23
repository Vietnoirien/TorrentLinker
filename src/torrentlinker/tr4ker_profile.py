"""tr4ker's account as the companion reads it: `/api/me`, `/api/me/stats`, the shop and
`/api/me/sw-rewards` (ADR-0025, ADR-0027).

`/api/me` also returns the account's API key, passkey and TOTP state, so the companion
filters it inside the tab and this module filters it again: only the names below are ever
read, and nothing else is kept. Every figure is nullable, because tr4ker's own accounts start
with empty statistics and snapshots. The raw and the bonus counters stay apart; the displayed
ratio is (uploaded + bonus_upload) / (downloaded + bonus_download), as the frontend computes it
(docs/research/tr4ker-credits.md).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

# The only /api/me keys that may leave the tab. No api_key, passkey, recovery or TOTP secret.
ME_KEYS = (
    "id",
    "username",
    "role",
    "power",
    "uploaded",
    "downloaded",
    "bonus_upload",
    "bonus_download",
    "money",
    "joined_at",
    "last_seen_at",
    "personal_freeleech_until",
    "freeleech_global",
    "token_currency_name",
    "badges",
)
SUMMARY_KEYS = (
    "uploaded",
    "downloaded",
    "raw_uploaded",
    "raw_downloaded",
    "bonus_upload",
    "bonus_download",
    "money",
    "ratio_warning",
)
SHOP_LIMIT = 50
BADGE_LIMIT = 20


def number(value: Any, *, minimum: float = 0, maximum: float = 1e30) -> float | int | None:
    """A finite number in range, never a bool, else None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        return None
    return value


def text(value: Any, limit: int = 160) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


@dataclass(frozen=True)
class Badge:
    name: str | None
    power_type: str | None
    power_value: float | None


def parse_badges(value: Any) -> list[Badge]:
    if not isinstance(value, list):
        return []
    result = []
    for entry in value[:BADGE_LIMIT]:
        if not isinstance(entry, dict):
            continue
        result.append(
            Badge(
                text(entry.get("name"), 80),
                text(entry.get("power_type"), 40),
                number(entry.get("power_value"), maximum=1e6),  # type: ignore[arg-type]
            )
        )
    return result


@dataclass(frozen=True)
class Tr4kerProfile:
    account_id: str
    username: str
    role: str | None = None
    uploaded: float | None = None
    downloaded: float | None = None
    raw_uploaded: float | None = None
    raw_downloaded: float | None = None
    bonus_upload: float | None = None
    bonus_download: float | None = None
    money: float | None = None
    ratio: float | None = None  # displayed ratio, bonus included
    ratio_raw: float | None = None  # the raw counters alone
    ratio_warning: bool | None = None
    freeleech_count: int | None = None
    freeleech_global: bool | None = None
    personal_freeleech_until: str | None = None
    credit_currency: str | None = None
    credit_multiplier: float | None = None  # percent of the strongest credit_multiplier badge
    badges: list[Badge] = field(default_factory=list)
    joined_at: str | None = None
    last_seen_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def ratio(up: float | None, down: float | None) -> float | None:
    """Upload over download, None when nothing was downloaded."""
    if up is None or down is None or down <= 0:
        return None
    return up / down


def _id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return str(value)
    return text(value, 80)


def account_identity(me: Any) -> tuple[str, str] | None:
    """(id, username) of a /api/me body, None without a usable identity."""
    if not isinstance(me, dict):
        return None
    ident, name = _id(me.get("id")), text(me.get("username"))
    return (ident, name) if ident and name else None


def parse_profile(me: Any, stats: Any = None) -> Tr4kerProfile | None:
    """A profile from a /api/me body and an optional /api/me/stats body; None without an
    account identity. Unknown fields are ignored, wrong-typed ones become None."""
    identity = account_identity(me)
    if identity is None:
        return None
    assert isinstance(me, dict)
    stats = stats if isinstance(stats, dict) else {}
    summary = stats.get("summary") if isinstance(stats.get("summary"), dict) else {}

    def pick(key: str) -> float | None:
        # The stats summary is the fresher read; /api/me is the fallback.
        found = number(summary.get(key))
        return found if found is not None else number(me.get(key))

    uploaded, downloaded = pick("uploaded"), pick("downloaded")
    bonus_up, bonus_down = pick("bonus_upload"), pick("bonus_download")
    raw_up, raw_down = number(summary.get("raw_uploaded")), number(summary.get("raw_downloaded"))
    displayed = (
        ratio(uploaded + (bonus_up or 0), downloaded + (bonus_down or 0))
        if uploaded is not None and downloaded is not None
        else None
    )
    raw = ratio(raw_up, raw_down) if raw_up is not None else ratio(uploaded, downloaded)
    badges = parse_badges(stats.get("badges") or me.get("badges"))
    multipliers = [
        b.power_value
        for b in badges
        if b.power_type == "credit_multiplier" and b.power_value is not None
    ]
    freeleech = number(stats.get("freeleech_count"))
    return Tr4kerProfile(
        account_id=identity[0],
        username=identity[1],
        role=text(me.get("role"), 60),
        uploaded=uploaded,
        downloaded=downloaded,
        raw_uploaded=raw_up,
        raw_downloaded=raw_down,
        bonus_upload=bonus_up,
        bonus_download=bonus_down,
        money=pick("money"),
        ratio=displayed,
        ratio_raw=raw,
        ratio_warning=flag(summary.get("ratio_warning")),
        freeleech_count=int(freeleech) if freeleech is not None else None,
        freeleech_global=flag(me.get("freeleech_global")),
        personal_freeleech_until=text(me.get("personal_freeleech_until"), 40),
        credit_currency=text(me.get("token_currency_name"), 40),
        credit_multiplier=max(multipliers) if multipliers else None,
        badges=badges,
        joined_at=text(me.get("joined_at"), 40),
        last_seen_at=text(me.get("last_seen_at"), 40),
    )


def restore_profile(data: Any) -> Tr4kerProfile | None:
    """A stored profile dict made a profile again; None when it no longer fits."""
    if not isinstance(data, dict):
        return None
    try:
        badges = [Badge(**b) for b in data.get("badges") or [] if isinstance(b, dict)]
        return Tr4kerProfile(**{**data, "badges": badges})
    except TypeError:
        return None


@dataclass(frozen=True)
class ShopItem:
    id: str
    name: str | None
    price: float | None
    bonus_bytes: float | None


def parse_shop(body: Any) -> list[ShopItem] | None:
    """The shop's upload items, None when the body is not a list of items. Read-only."""
    items = body.get("items") if isinstance(body, dict) else body
    if not isinstance(items, list):
        return None
    result = []
    for entry in items[:SHOP_LIMIT]:
        if not isinstance(entry, dict) or _id(entry.get("id")) is None:
            continue
        result.append(
            ShopItem(
                _id(entry.get("id")) or "",
                text(entry.get("name"), 80),
                number(entry.get("price")),
                number(entry.get("bonus_bytes")),
            )
        )
    return result


@dataclass(frozen=True)
class Payout:
    """One seedtime payout from /api/me/sw-rewards, with the inputs tr4ker paid it for."""

    key: str
    amount: float
    paid_at: float | None = None  # epoch seconds
    seeders: int | None = None
    size_bytes: int | None = None
    seedtime_seconds: int | None = None
    slug: str | None = None
    category: str | None = None
    multiplier: float | None = None  # badge credit multiplier in percent, when known

    def row(self) -> dict[str, Any]:
        return asdict(self)


def _count(value: Any) -> int | None:
    found = number(value)
    return int(found) if found is not None else None


def parse_payout(entry: Any, paid_at: float | None = None) -> Payout | None:
    """A payout from the companion's normalised entry; None without a numeric amount.
    Unknown extra fields are ignored. `paid_at` is the already parsed `at`."""
    if not isinstance(entry, dict):
        return None
    amount = number(entry.get("amount"), minimum=-1e12, maximum=1e12)
    if amount is None:
        return None
    seeders, size = _count(entry.get("seeders")), _count(entry.get("size_bytes"))
    seedtime = _count(entry.get("seedtime_seconds"))
    slug, category = text(entry.get("slug"), 200), text(entry.get("category"), 80)
    ident = _id(entry.get("id"))
    key = (
        f"id:{ident}"
        if ident
        else "h:"
        + hashlib.sha256(
            json.dumps(
                [entry.get("at"), amount, seeders, size, seedtime, slug], allow_nan=False
            ).encode()
        ).hexdigest()
    )
    return Payout(
        key,
        float(amount),
        paid_at,
        seeders,
        size,
        seedtime,
        slug,
        category,
        number(entry.get("multiplier"), maximum=1e6),  # type: ignore[arg-type]
    )
