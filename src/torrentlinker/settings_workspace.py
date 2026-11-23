"""Validated owner Settings groups shared by desktop and Web hosts."""

from __future__ import annotations

import copy
import re
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from torrentlinker.client_profiles import pending_work
from torrentlinker.config import (
    C411_ID,
    CLIENT_FIELDS,
    HUB_SECRET,
    IndexerSettings,
    MatchingSettings,
    ProxySettings,
    Settings,
)
from torrentlinker.domain import ContentKind, PathMapping
from torrentlinker.release_score import PROFILES
from torrentlinker.release_score.preferences import Preferences as ScorePreferences
from torrentlinker.trackers import TRACKERS, Tracker, tracker, tracker_of_url
from torrentlinker.web.setup import (
    CLIENT_ADDRESS,
    INDEXER_ADDRESS,
    Connection,
    FolderRemoval,
    FolderSetup,
    IndexerConnection,
    ProxySetup,
    Setup,
)
from torrentlinker.web.zen_preferences import ZenPreferences


class General(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    language: Literal["auto", "en", "fr"] = "auto"
    theme: Literal["auto", "dark", "light"] = "auto"
    media_layout: Literal["cinematic", "focus", "horizon"] = "cinematic"
    media_horizon: Literal["home", "showcase", "wall"] = "home"
    ui_scale: float = Field(default=1, ge=0.75, le=2)
    adult_content: bool = False
    sequential_video: bool = True


class Matching(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind_categories: dict[ContentKind, list[Annotated[int, Field(ge=0)]]] = Field(
        default_factory=dict
    )
    size_tolerance: float = Field(ge=0, le=0.2)
    min_partial_coverage: float = Field(ge=0.01, le=1)
    ignore_patterns: list[str] = Field(max_length=10000)
    plan_exclusions: list[str] = Field(max_length=1000)


class TrackerConnection(BaseModel):
    """What a Tracker other than c411 keeps in Connections: its switch and two credentials.
    An absent key or passkey stays as saved; an empty one clears it."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    api_key: str | None = Field(default=None, max_length=4096)
    passkey: str | None = Field(default=None, max_length=4096)


def announce_url(found: Tracker, passkey: str) -> str:
    """The private Announce URL of a Tracker, which holds the passkey (never logged or shown)."""
    return f"https://{found.announce_hosts[-1]}/announce/{passkey.strip()}" if passkey else ""


class Connections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client: Connection
    indexer: IndexerConnection
    proxy: ProxySetup
    tmdb_api_key: str | None = Field(default=None, max_length=4096)
    announce_url: str | None = Field(default=None, max_length=4096)
    announce_hosts: list[str] | None = Field(default=None, max_length=16)
    trackers: dict[str, TrackerConnection] | None = None

    @field_validator("trackers")
    @classmethod
    def own_trackers(cls, value):
        if value is not None and any(k not in TRACKERS or k == C411_ID for k in value):
            raise ValueError("Unknown Tracker.")
        return value

    @field_validator("announce_hosts")
    @classmethod
    def valid_announce_hosts(cls, value):
        from torrentlinker.tracker_updates import host_name

        return list(dict.fromkeys(host_name(host) for host in value)) if value is not None else None

    reseed_link_root: str = Field(default="", max_length=4096)
    reseed_layout: Literal["auto", "client", "links"] = "auto"


def explain_validation(error: ValidationError) -> str:
    """One readable line per refused field. Never echoes an input, which can be a secret."""
    lines: list[str] = []
    for row in error.errors():
        field = [str(part) for part in row["loc"]]
        if row["type"] == "value_error":
            # Our own validators raise fixed, secret-free sentences.
            line = str(row["msg"]).removeprefix("Value error, ")
        elif field[-1:] == ["host"]:
            line = CLIENT_ADDRESS
        elif field[-1:] == ["url"] and field[:1] == ["indexer"]:
            line = INDEXER_ADDRESS
        else:
            line = "Invalid value: " + ".".join(field)
        if line not in lines:
            lines.append(line)
    return "\n".join(lines)


class SettingsWorkspace:
    def __init__(self, setup: Setup):
        self.setup = setup

    def announce_hosts(self):
        from torrentlinker.tracker_updates import announce_hosts

        return announce_hosts(self.setup)

    def secret_name(self, reference: str) -> str:
        """The stored name behind a Settings secret reference, or ValueError."""
        settings = self.setup.settings
        fixed = {
            "indexer-api-key": "indexer-api-key",
            "tmdb-api-key": "tmdb-api-key",
            "announce-url": "announce-url",
            "proxy-password": "proxy-password",
            "hub-key": HUB_SECRET,
            "assistant-brave": "assistant:brave",
        }
        if reference in fixed:
            return fixed[reference]
        if reference == "client-password":
            return settings.secret_name(CLIENT_FIELDS[settings.client] + "-password")
        if reference == "client-api-key":
            return settings.secret_name("qbit-api-key")
        prefix, _, identifier = reference.partition(":")
        if prefix == "extra-key" and identifier in {"1", "2", "3", "4"}:
            return f"indexer-extra-key-{identifier}"
        if prefix == "passkey" and identifier in TRACKERS and identifier != C411_ID:
            return TRACKERS[identifier].passkey_secret
        if prefix == "indexer" and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier):
            return settings.indexer_secret(identifier)
        if prefix == "assistant" and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier):
            return "assistant:" + identifier
        raise ValueError("Unknown secret.")

    def reveal(self, reference: str) -> str:
        """One saved secret for the Owner's eye button; a deployment-managed one never leaves."""
        name = self.secret_name(str(reference))
        if name in self.setup.secrets.files:
            raise ValueError("This secret is managed by the deployment.")
        return self.setup.secrets.get(name)

    def test_connection(self, group: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            if group == "client":
                return self.setup.test_client(Connection.model_validate(body))
            if group == "indexer":
                return self.setup.test_indexer(IndexerConnection.model_validate(body))
            if group == "proxy":
                from torrentlinker import net

                value = ProxySetup.model_validate(body)
                password = value.password
                if password is None:
                    password = self.setup.secrets.get("proxy-password")
                proxy = net.proxy_url(value.address, value.username, password)
                try:
                    return {"address": net.redacted(proxy), "ip": net.address_seen(proxy)}
                except Exception:
                    raise ValueError(
                        "Proxy test failed. Check its address and credentials."
                    ) from None
            if group == "tmdb":
                return self._test_tmdb(body)
            if group in TRACKERS and group != C411_ID:
                return self._test_tracker(tracker(group), body)
            raise ValueError("Unknown connection test.")
        except ValidationError as error:
            raise ValueError(explain_validation(error)) from None

    def _typed_or_saved(self, body: dict[str, Any], name: str) -> str:
        typed = body.get("api_key")
        if typed is not None and not isinstance(typed, str):
            raise ValueError("Invalid value: api_key")
        return typed or self.setup.secrets.get(name)

    def _test_tmdb(self, body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        from torrentlinker.tmdb import Tmdb

        key = self._typed_or_saved(body, "tmdb-api-key")
        if not key:
            raise ValueError("Enter your TMDb API key.")
        try:
            Tmdb(key).check()
        except httpx.HTTPStatusError as error:
            if error.response.status_code in (401, 403):
                raise ValueError("TMDb refused the API key.") from None
            raise ValueError("TMDb test failed. Check your connection and try again.") from None
        except Exception:
            raise ValueError("TMDb test failed. Check your connection and try again.") from None
        return {"ok": True}

    def _test_tracker(self, found: Tracker, body: dict[str, Any]) -> dict[str, Any]:
        """A Torznab caps call, through the same Indexer path searches use."""
        from torrentlinker.web.setup import mode_names

        key = self._typed_or_saved(body, found.api_key_secret)
        if not key:
            raise ValueError(f"Enter your {found.name} API key.")
        settings = self.setup.settings
        url = next(
            (i.url for i in settings.indexers if i.id == found.indexer_id), found.indexer_url
        )
        try:
            caps = self.setup._probe(url, key, found.name, found.id)
        except ValueError:
            raise ValueError(
                f"{found.name} test failed. Check its API key and your connection."
            ) from None
        modes = mode_names(caps)
        ids = sorted({p for params in modes.values() for p in params if p.endswith("id")})
        return {"ok": True, "modes": len(modes), "searchable_ids": ids}

    def storage(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        """Use the existing storage proofs and owner guards for either renderer."""
        with self.setup.lock:
            if action not in {
                "save",
                "mapping",
                "download",
                "remove",
                "remove-mapping",
                "categories",
            }:
                return self._storage(action, body)
            root = self.setup._root or self.setup
            previous = copy.deepcopy(root.settings)
            selected = copy.deepcopy(self.setup.settings)
            try:
                return self._storage(action, body)
            except Exception:
                root.settings = previous
                if self.setup is not root:
                    self.setup.settings = selected
                raise

    def _storage(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        setup = self.setup
        with setup.lock:
            if action == "browse":
                return setup.browse(str(body.get("path", "")))
            if action == "preview":
                return setup.preview_folder(FolderSetup.model_validate(body))
            if action == "client-folders":
                from torrentlinker.paths import PathMapper

                mapper = PathMapper(setup.settings.path_mappings)
                return {
                    "folders": [
                        {**asdict(folder), "local": mapper.to_local(folder.path)}
                        for folder in setup.client().folder_settings()
                    ]
                }
            if action == "categories":
                setup.test_indexer(IndexerConnection(url=setup.settings.indexer.url), save=True)
                return self.snapshot()
            if action == "test":
                from torrentlinker.paths import check_mappings, unreachable_download_folders

                value = FolderSetup.model_validate({**body, "original_local": ""})
                result = setup.folder(value, probe=True)
                mapping = PathMapping(str(setup.path_under_root(value.local)), value.client_path)

                def accessible(path: Path) -> bool:
                    try:
                        return setup.path_under_root(str(path)).is_dir()
                    except (ValueError, OSError):
                        return False

                result["checks"] = [
                    asdict(check)
                    for check in check_mappings(
                        setup.client().torrents(with_files=False), [mapping], is_dir=accessible
                    )
                ]
                downloads = setup.settings.download_folders
                result["unreachable"] = [
                    str(path)
                    for path in unreachable_download_folders(
                        [
                            Path(p)
                            for p in [downloads.default, *downloads.by_category.values()]
                            if p
                        ],
                        [mapping],
                        setup.client().default_save_path(),
                    )
                ]
                return result
            if action == "save":
                setup.folder(FolderSetup.model_validate(body), save=True)
            elif action == "mapping":
                value = FolderSetup.model_validate({**body, "original_local": ""})
                if pending_work(setup.settings, setup.store, setup.settings.active_client_id):
                    raise ValueError("Finish pending work before changing Path Mappings.")
                checked = setup.folder(value, probe=True)
                if not checked.get("verification"):
                    raise ValueError("Verify this Path Mapping before saving it.")
                local = str(setup.path_under_root(value.local))
                setup.settings.path_mappings = [
                    m
                    for m in setup.settings.path_mappings
                    if m.local != local
                    and m.qbit != value.client_path
                    and (m.local, m.qbit)
                    != (body.get("original_local"), body.get("original_client_path"))
                ] + [PathMapping(local, value.client_path)]
                setup.save()
            elif action == "download":
                value = FolderSetup.model_validate(body)
                setup.configure_download_folder(
                    value.local, value.category, value.client_path, save=True
                )
            elif action == "remove":
                if body.get("confirmed") is not True:
                    raise ValueError("Confirm folder removal first.")
                if setup.store.verification_hashes():
                    raise ValueError("Finish pending Reseed Verifications before removing folders.")
                setup.remove_folder(FolderRemoval.model_validate(body))
            elif action == "remove-mapping":
                if body.get("confirmed") is not True:
                    raise ValueError("Confirm Path Mapping removal first.")
                if pending_work(setup.settings, setup.store, setup.settings.active_client_id):
                    raise ValueError("Finish pending work before changing Path Mappings.")
                setup.settings.path_mappings = [
                    mapping
                    for mapping in setup.settings.path_mappings
                    if (mapping.local, mapping.qbit) != (body.get("local"), body.get("client_path"))
                ]
                setup.save()
            elif action == "suggest":
                return setup.suggest_mappings()
            else:
                raise ValueError("Unknown storage operation.")
            return self.snapshot()

    def clients(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.setup.lock:
            root = self.setup._root or self.setup
            original = root.settings
            draft = copy.deepcopy(original)
            draft.capture_client()
            if action == "add":
                draft.add_client(body.get("name", ""))
            elif action in {"default", "remove"}:
                profile = draft.profile(body.get("client_id", ""))
                if action == "default":
                    if not profile.enabled:
                        raise ValueError("Choose an enabled client.")
                    draft.default_client_id = profile.id
                else:
                    if body.get("confirmed") is not True:
                        raise ValueError("Confirm client removal first.")
                    if len(draft.client_profiles) == 1:
                        raise ValueError("Keep at least one client.")
                    if pending_work(draft, root.store, profile.id):
                        raise ValueError("Finish or remove this client's pending work first.")
                    from torrentlinker.client_profiles import require_no_file_access

                    require_no_file_access(root, profile.id)
                    remaining = [p for p in draft.client_profiles if p.id != profile.id]
                    if draft.active_client_id == profile.id:
                        draft.select_client(remaining[0].id)
                    draft.client_profiles = remaining
                    if draft.default_client_id == profile.id:
                        draft.default_client_id = remaining[0].id
            else:
                raise ValueError("Unknown client operation.")
            selected = self.setup.settings.active_client_id
            if selected not in {p.id for p in draft.client_profiles}:
                selected = draft.active_client_id
            root.settings = draft
            try:
                root.save()
            except Exception:
                root.settings = original
                raise
            root.store = root.store.for_client(draft.active_client_id)
            root._client = None
            if self.setup is not root:
                self.setup.settings = draft.for_client(selected)
                self.setup.store = root.store.for_client(selected)
                self.setup._client = None
            return self.snapshot()

    @staticmethod
    def _adoptable_entry(settings: Settings, found: Tracker) -> IndexerSettings | None:
        """An Indexer that is this Tracker's own site, whether added by hand (its address) or
        imported from Prowlarr or Jackett (listed under the Tracker's name)."""
        for entry in settings.indexers:
            if entry.id == found.indexer_id:
                continue
            if tracker_of_url(entry.url) is found:
                return entry
            if entry.source and entry.name.casefold() == found.name.casefold():
                return entry
        return None

    def _adoptable(self, found: Tracker) -> dict[str, Any] | None:
        """What the Tracker's tab offers to take over, unless the Tracker has its own key."""
        settings = self.setup.settings
        entry = self._adoptable_entry(settings, found)
        if entry is None or self.setup.secrets.get(found.api_key_secret):
            return None
        return {
            "name": entry.name,
            "source": entry.source,
            "url": entry.url,
            "history": self.setup.store.crossseed_count(entry.id),
        }

    def adopt(self, tracker_id: str) -> dict[str, Any]:
        """The Tracker takes over its existing Indexer in place: its key and Cross-seed
        history follow it, it leaves the Indexers list, and an Indexer import still lists it
        as imported, so a re-sync never creates it again."""
        found = tracker(tracker_id)
        if found.id == C411_ID:
            raise ValueError("c411 is built in.")
        with self.setup.lock:
            setup = self.setup
            root = setup._root or setup
            original = root.settings
            draft = copy.deepcopy(original)
            draft.capture_client()
            entry = self._adoptable_entry(draft, found)
            if entry is None:
                raise ValueError(f"No Indexer of {found.name} to adopt.")
            if setup.secrets.get(found.api_key_secret):
                raise ValueError(f"{found.name} already has its own API key.")
            old = entry.id
            key = setup.secrets.get(Settings.indexer_secret(old))
            draft.indexers[:] = [i for i in draft.indexers if i.id != found.indexer_id]
            entry.id = found.indexer_id
            entry.enabled = True
            root.settings = draft
            try:
                root.save()
            except Exception:
                root.settings = original
                raise
            setup.secrets.update({found.api_key_secret: key, Settings.indexer_secret(old): ""})
            root.store.rename_crossseed_indexer(old, found.indexer_id)
            if setup is not root:
                setup.settings = draft.for_client(setup.settings.active_client_id)
            for held in {id(x): x for x in (setup, root)}.values():
                held._torznab.pop(old, None)
                held._torznab.pop(found.indexer_id, None)
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self.setup.lock:
            setup = self.setup
            settings = setup.settings
            profile = settings.profile()
            storage = setup.snapshot()
            config = getattr(settings, CLIENT_FIELDS[settings.client])
            return {
                "client_id": profile.id,
                "clients": setup.snapshot()["clients"],
                "default_client_id": (setup._root or setup).settings.default_client_id,
                "storage": {
                    key: storage[key]
                    for key in (
                        "folders",
                        "download_folders",
                        "mappings",
                        "storage_roots",
                        "indexer_categories",
                    )
                },
                "tracker_registry": {
                    t.id: {
                        "name": t.name,
                        "capabilities": sorted(t.capabilities),
                        "companion": t.companion,
                        "announce_host": t.announce_hosts[-1],
                    }
                    for t in TRACKERS.values()
                },
                "adoptable": {
                    t.id: self._adoptable(t) for t in TRACKERS.values() if t.id != C411_ID
                },
                "indexer_count": sum(1 for i in settings.indexers if i.id not in TRACKERS) + 1,
                "score_defaults": PROFILES,
                "score_recommendation": ScorePreferences.model_validate(
                    settings.release_score
                ).equipment.recommendation(),
                "release_score": ScorePreferences.model_validate(settings.release_score).model_dump(
                    by_alias=True
                ),
                "general": {key: getattr(settings, key) for key in General.model_fields},
                "matching": {
                    **asdict(settings.matching),
                    "kind_categories": settings.kind_categories,
                    "plan_exclusions": settings.plan_exclusions,
                },
                "zen": {**asdict(settings.zen), "free_space_margin": settings.free_space_margin},
                "connections": {
                    "client": {
                        "client": settings.client,
                        "name": profile.name,
                        "host": config.host,
                        "username": getattr(config, "username", ""),
                    },
                    "indexer": {"url": settings.indexer.url},
                    "announce_hosts": self.announce_hosts(),
                    "trackers": {
                        t.id: {
                            "enabled": any(
                                i.id == t.indexer_id and i.enabled for i in settings.indexers
                            )
                        }
                        for t in TRACKERS.values()
                        if t.id != C411_ID
                    },
                    "proxy": asdict(settings.proxy),
                    "reseed_link_root": profile.reseed_link_root,
                    "reseed_layout": profile.reseed_layout,
                    "secrets": {
                        "password": bool(
                            setup.secrets.get(
                                settings.secret_name(CLIENT_FIELDS[settings.client] + "-password")
                            )
                        ),
                        "api_key": bool(setup.secrets.get(settings.secret_name("qbit-api-key"))),
                        "indexer_api_key": bool(setup.secrets.get("indexer-api-key")),
                        "extra_keys": len(setup.extra_indexer_keys()),
                        "extra_key_slots": [
                            i for i in range(1, 5) if setup.secrets.get(f"indexer-extra-key-{i}")
                        ],
                        "trackers": {
                            t.id: {
                                "api_key": bool(setup.secrets.get(t.api_key_secret)),
                                "passkey": bool(setup.secrets.get(t.passkey_secret)),
                            }
                            for t in TRACKERS.values()
                            if t.id != C411_ID
                        },
                        "tmdb_api_key": bool(setup.secrets.get("tmdb-api-key")),
                        "announce_url": bool(setup.secrets.get("announce-url")),
                        "proxy_password": bool(setup.secrets.get("proxy-password")),
                    },
                    "managed_secrets": list(setup.secrets.files),
                },
            }

    def save(self, group: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            if group in {"general", "matching", "zen", "release_score"}:
                return self._save_preferences(group, body)
            return self._save_connections(group, body)
        except ValidationError as error:
            # Validation errors can otherwise echo newly entered secrets.
            raise ValueError(explain_validation(error)) from None

    def _save_preferences(self, group: str, body: dict[str, Any]) -> dict[str, Any]:
        models: dict[str, type[BaseModel]] = {
            "general": General,
            "release_score": ScorePreferences,
            "matching": Matching,
            "zen": ZenPreferences,
        }
        value = models[group].model_validate(body)
        with self.setup.lock:
            root = self.setup._root or self.setup
            original = root.settings
            draft = copy.deepcopy(original)
            if isinstance(value, ScorePreferences):
                draft.release_score = value.model_dump(by_alias=True)
            elif isinstance(value, General):
                for key, item in value.model_dump().items():
                    setattr(draft, key, item)
            elif isinstance(value, Matching):
                draft.kind_categories = value.kind_categories
                draft.matching = MatchingSettings(
                    value.size_tolerance,
                    value.min_partial_coverage,
                    [line.strip() for line in value.ignore_patterns if line.strip()],
                )
                draft.plan_exclusions = [
                    line.strip() for line in value.plan_exclusions if line.strip()
                ]
            elif isinstance(value, ZenPreferences):
                value.apply(draft)
            root.settings = draft
            try:
                root.save()
            except Exception:
                root.settings = original
                raise
            if self.setup is not root:
                self.setup.settings = draft.for_client(self.setup.settings.active_client_id)
            if (
                group not in {"general", "release_score"}
                or original.adult_content != draft.adult_content
            ):
                for profile in draft.client_profiles:
                    root.store.for_client(profile.id).clear_plan()
            return self.snapshot()

    def _save_connections(self, group: str, body: dict[str, Any]) -> dict[str, Any]:
        if group != "connections":
            raise ValueError("Unknown Settings group.")
        # Parse every field before any mutation, including secret writes.
        value = Connections.model_validate(body)
        with self.setup.lock:
            setup = self.setup
            root = setup._root or setup
            original = root.settings
            draft = original.for_client(setup.settings.active_client_id)
            profile = draft.profile()
            if not value.client.name.strip():
                raise ValueError("Enter a client name of 1 to 100 characters.")
            old_config = getattr(draft, CLIENT_FIELDS[draft.client])
            changed = (
                draft.client != value.client.client
                or old_config.host != value.client.host
                or getattr(old_config, "username", "") != value.client.username
            )
            if changed and pending_work(original, root.store, profile.id):
                raise ValueError(
                    "Finish or remove this client's pending work before changing its connection."
                )
            if (
                value.indexer.url != draft.indexer.url
                and setup.secrets.get("indexer-api-key")
                and setup.store.catalogue_size()
            ):
                raise ValueError(
                    "Use a separate configuration directory for a different Indexer "
                    "with an existing catalogue."
                )
            config = getattr(draft, CLIENT_FIELDS[value.client.client])
            config.host = value.client.host
            if hasattr(config, "username"):
                config.username = value.client.username
            draft.client = value.client.client
            profile.name = value.client.name.strip()
            profile.reseed_link_root = value.reseed_link_root.strip()
            profile.reseed_layout = value.reseed_layout
            from torrentlinker.reseed_layout import DISK_RENAME_CLIENTS

            links = value.reseed_layout == "links" or value.client.client in DISK_RENAME_CLIENTS
            if links and profile.reseed_link_root and not hasattr(setup, "_folder_candidate"):
                profile.reseed_link_root = str(setup.path_under_root(profile.reseed_link_root))
            if changed:
                draft.path_mappings.clear()
                draft.download_folders.default = ""
                draft.download_folders.by_category.clear()
            draft.indexer.url = value.indexer.url
            for identifier, item in (value.trackers or {}).items():
                found = tracker(identifier)
                entry = next((i for i in draft.indexers if i.id == found.indexer_id), None)
                if entry is None and item.enabled:
                    draft.indexers.append(
                        IndexerSettings(
                            url=found.indexer_url,
                            id=found.indexer_id,
                            name=found.name,
                            enabled=True,
                        )
                    )
                elif entry is not None:
                    entry.enabled = item.enabled
            if value.announce_hosts is not None:
                draft.announce_hosts = value.announce_hosts
            draft.proxy = ProxySettings(
                value.proxy.address, value.proxy.username, value.proxy.torrent_client
            )
            values = {
                draft.secret_name(CLIENT_FIELDS[draft.client] + "-password"): value.client.password,
                "indexer-api-key": value.indexer.api_key,
                "tmdb-api-key": value.tmdb_api_key,
                "announce-url": value.announce_url,
                "proxy-password": value.proxy.password,
            }
            for identifier, item in (value.trackers or {}).items():
                found = tracker(identifier)
                values[found.api_key_secret] = item.api_key
                if item.passkey is not None:
                    # The Announce URL is the passkey in the Tracker's own form: kept in step.
                    values[found.passkey_secret] = item.passkey
                    values[found.announce_secret] = announce_url(found, item.passkey)
            if CLIENT_FIELDS[draft.client] == "qbit":
                values[draft.secret_name("qbit-api-key")] = value.client.api_key
            if value.indexer.extra_keys is not None:
                extras = setup.resolve_extra_keys(value.indexer.extra_keys)
                values.update(
                    {
                        f"indexer-extra-key-{i + 1}": extras[i] if i < len(extras) else ""
                        for i in range(4)
                    }
                )
            if not root.configured:
                from torrentlinker import net

                previous_proxy, previous_client_proxy = net.current()
                password = value.proxy.password
                if password is None:
                    password = setup.secrets.get("proxy-password")
                net.configure(
                    net.proxy_url(value.proxy.address, value.proxy.username, password),
                    value.proxy.torrent_client,
                )
                try:
                    setup.test_client(value.client)
                finally:
                    net.configure(previous_proxy, previous_client_proxy is not None)
            credentials = {key: item for key, item in values.items() if item is not None}
            previous_credentials = {key: setup.secrets.get(key) for key in credentials}
            draft.capture_client()
            draft.select_client(original.active_client_id)
            try:
                setup.secrets.update(credentials)
                root.settings = draft
                root.save()
            except Exception:
                root.settings = original
                # A failed configuration write must not leave replacement keys
                # paired with the old connection settings.
                if credentials and not any(key in setup.secrets.files for key in credentials):
                    setup.secrets.update(previous_credentials)
                raise
            if not root.configured:
                root.marker.write_text("connected", encoding="utf-8")
                root.configured = True
                setup.configured = True
            from torrentlinker import net

            net.configure(
                net.proxy_url(
                    draft.proxy.address, draft.proxy.username, setup.secrets.get("proxy-password")
                ),
                draft.proxy.torrent_client,
            )
            root._folder_proofs.clear()
            root._client = root._indexer = None
            if setup is not root:
                setup.settings = draft.for_client(profile.id)
                setup._client = setup._indexer = None
            return self.snapshot()
