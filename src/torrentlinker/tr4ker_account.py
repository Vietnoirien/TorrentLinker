"""tr4ker's companion account: pairing, the filtered profile snapshot and the payout log.

c411's pairing is bound to the API profile (profile_workspace). tr4ker has no API profile: its
native JSON needs a signed-in browser session (ADR-0025), so the companion reads the account in
a tr4ker tab and the first pairing binds that account. Every later message must come from the
same account, with the same token and extension. Nothing here keeps a cookie, an API key or a
passkey: the profile is rebuilt from an allowlist of fields (tr4ker_profile) even when the
companion has already filtered it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from torrentlinker.store import Store
from torrentlinker.tr4ker_profile import (
    Payout,
    account_identity,
    parse_payout,
    parse_profile,
    parse_shop,
    restore_profile,
    text,
)
from torrentlinker.trackers import TR4KER, tracker

FRESH = 300  # seconds a snapshot keeps the session "ready"
PAYOUTS_PER_POST = 100
ESTIMATE_MINIMUM = 30  # payouts before "estimate from your payouts" has anything to fit
ROUTES = ("pair", "snapshot", "payouts", "disconnect")
SNAPSHOT_KEYS = {"schema", "source", "tracker", "capturedAt", "account", "me", "stats", "shop"}


def stamp(value: Any) -> float | None:
    """Epoch seconds of an ISO time with a zone, None otherwise."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, OverflowError, OSError):
        return None


class Tr4kerAccount:
    def __init__(
        self,
        directory: Path,
        store: Store | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.path = directory / "tr4ker-companion.json"
        self.store = store.for_tracker(TR4KER) if store else None
        self.clock = clock
        self.lock = threading.RLock()
        self.data: dict[str, Any] = {}
        try:
            saved = json.loads(self.path.read_text())
            if isinstance(saved, dict):
                self.data = saved
        except (OSError, ValueError):
            pass
        self._code = ""
        self._code_until = 0.0
        self._pair: tuple[str, str] | None = None
        pair = self.data.get("connection")
        if (
            isinstance(pair, list)
            and len(pair) == 2
            and all(isinstance(v, str) for v in pair)
            and re.fullmatch(r"[a-f0-9]{64}", pair[0])
            and re.fullmatch(r"chrome-extension://[a-p]{32}", pair[1])
        ):
            self._pair = (pair[0], pair[1])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(temp, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(self.data, output, allow_nan=False)
        os.replace(temp, self.path)

    @property
    def account_id(self) -> str | None:
        account = self.data.get("account")
        return account.get("id") if isinstance(account, dict) else None

    def pairing(self) -> dict[str, Any]:
        with self.lock:
            self._code = secrets.token_urlsafe(32)
            self._code_until = self.clock() + 600
            return {"code": self._code, "expiresIn": 600}

    def cancel(self) -> None:
        with self.lock:
            self._code = ""

    def disconnect(self) -> None:
        """Forget the pairing and the snapshot; the payout log is the Owner's history and stays."""
        with self.lock:
            self._code, self._pair = "", None
            for key in ("connection", "profile", "shop", "received_at"):
                self.data.pop(key, None)
            self._save()

    def _authorised(self, origin: str, authorization: str) -> None:
        digest = hashlib.sha256(authorization.encode()).hexdigest()
        if (
            not self._pair
            or origin != self._pair[1]
            or not hmac.compare_digest(digest, self._pair[0])
        ):
            raise PermissionError("Pair tr4ker again from Settings.")

    def receive(
        self, route: str, origin: str, authorization: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        name = route.removeprefix("/api/companion/")
        if name not in ROUTES:
            raise PermissionError("The tr4ker companion does not use this route yet.")
        with self.lock:
            if name == "pair":
                return self._receive_pair(origin, body)
            self._authorised(origin, authorization)
            if name == "disconnect":
                self.disconnect()
                return {"disconnected": True}
            if body.get("tracker") != TR4KER or (
                name == "payouts" and body.get("accountId") != self.account_id
            ):
                raise PermissionError("Different tr4ker account.")
            if name == "payouts":
                return self._receive_payouts(body)
            return self._receive_snapshot(body)

    def _receive_pair(self, origin: str, body: dict[str, Any]) -> dict[str, Any]:
        code = body.get("code")
        if (
            not isinstance(code, str)
            or not self._code
            or self.clock() >= self._code_until
            or not hmac.compare_digest(code.encode(), self._code.encode())
        ):
            raise PermissionError("Pairing code invalid or expired.")
        account = text(body.get("accountId"), 80)
        if body.get("tracker") != TR4KER or not account:
            raise PermissionError("Pair from a signed-in tr4ker tab.")
        token = secrets.token_urlsafe(32)
        self._pair = (hashlib.sha256(("Bearer " + token).encode()).hexdigest(), origin)
        if self.account_id != account:
            for key in ("profile", "shop", "received_at"):
                self.data.pop(key, None)
        self.data["account"] = {"id": account, "username": text(body.get("username"))}
        self.data["connection"] = list(self._pair)
        self._code = ""
        self._save()
        return {"token": token}

    def _receive_snapshot(self, body: dict[str, Any]) -> dict[str, Any]:
        if set(body) - SNAPSHOT_KEYS or not {"schema", "source", "capturedAt", "me"} <= set(body):
            raise ValueError("Snapshot fields invalid.")
        taken = stamp(body["capturedAt"])
        if (
            body["schema"] != 1
            or body["source"] != tracker(TR4KER).origin
            or taken is None
            or not -30 <= self.clock() - taken <= 300
        ):
            raise ValueError("Snapshot invalid or expired.")
        identity = account_identity(body["me"])
        named = body.get("account")
        if (
            identity is None
            or identity[0] != self.account_id
            or not isinstance(named, dict)
            or named.get("id") != self.account_id
        ):
            raise PermissionError("Different tr4ker account.")
        profile = parse_profile(body["me"], body.get("stats"))
        if profile is None:
            raise ValueError("Snapshot fields invalid.")
        previous = self.data.get("captured_at") or 0
        if taken <= previous:
            raise ValueError("Snapshot already received or older than current data.")
        self.data["account"] = {"id": profile.account_id, "username": profile.username}
        self.data["profile"] = profile.as_dict()
        self.data["captured_at"] = taken
        self.data["received_at"] = self.clock()
        if body.get("shop") is not None:
            shop = parse_shop(body["shop"])
            if shop is None:
                raise ValueError("Shop format invalid.")
            self.data["shop"] = [item.__dict__ for item in shop]
        self._save()
        self._record_day(profile.as_dict())
        return {"accepted": True}

    def _record_day(self, profile: dict[str, Any]) -> None:
        """Keep the day's last figures under Tracker tr4ker, for Profile history."""
        if self.store is None:
            return
        day = datetime.fromtimestamp(self.clock()).date().isoformat()
        keep = (
            "uploaded", "downloaded", "raw_uploaded", "raw_downloaded", "bonus_upload",
            "bonus_download", "money", "ratio", "ratio_raw", "freeleech_count",
        )  # fmt: skip
        account = str(self.account_id)
        row = self.store.profile_day(account, day) or {"values": {}}
        row["values"].update({k: profile[k] for k in keep if profile.get(k) is not None})
        row["companion"] = True
        self.store.save_profile_day(account, day, row)

    def _receive_payouts(self, body: dict[str, Any]) -> dict[str, Any]:
        entries = body.get("entries")
        if not isinstance(entries, list) or len(entries) > PAYOUTS_PER_POST:
            raise ValueError("Payout entries invalid.")
        payouts: list[Payout] = []
        for entry in entries:
            at = stamp(entry.get("at")) if isinstance(entry, dict) else None
            payout = parse_payout(entry, at)
            if payout is not None:
                payouts.append(payout)
        added = (
            self.store.add_tr4ker_payouts(str(self.account_id), [p.row() for p in payouts])
            if self.store
            else 0
        )
        return {"accepted": len(payouts), "added": added}

    def state(self) -> dict[str, Any]:
        with self.lock:
            received = self.data.get("received_at")
            account = self.data.get("account")
            profile = restore_profile(self.data.get("profile"))
            payouts = (
                self.store.tr4ker_payouts(str(self.account_id), 50)
                if self.store and self.account_id
                else []
            )
            count = (
                self.store.tr4ker_payout_count(str(self.account_id))
                if self.store and self.account_id
                else 0
            )
            return {
                "paired": bool(self._pair),
                "pending": bool(self._code) and self.clock() < self._code_until,
                "account": account if self._pair and isinstance(account, dict) else None,
                "profile": profile.as_dict() if profile and self._pair else None,
                "shop": self.data.get("shop") if self._pair else None,
                "received_at": received if self._pair else None,
                "available": bool(self._pair and received and self.clock() - received <= FRESH),
                "payouts": {"count": count, "recent": payouts},
                # The fit itself comes with Plans (ADR-0027); until the log is big enough
                # there is nothing to fit, and no earnings figure is shown.
                "estimate": {"available": False, "payouts": count, "needed": ESTIMATE_MINIMUM},
            }
