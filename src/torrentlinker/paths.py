"""Path Mappings: translate between this app's view of a path and qBittorrent's."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from torrentlinker.domain import PathMapping, Torrent
from torrentlinker.qbit import Qbit


def _is_windows(path: str) -> bool:
    return "\\" in path or (len(path) >= 2 and path[1] == ":")


def _split(path: str) -> list[str]:
    return [p for p in path.replace("\\", "/").split("/") if p]


def _join(prefix: str, rest: list[str]) -> str:
    sep = "\\" if _is_windows(prefix) else "/"
    if not rest:
        return prefix
    return prefix.rstrip("/\\") + sep + sep.join(rest)


def _strip_prefix(path: str, prefix: str) -> list[str] | None:
    """Remaining segments of `path` under `prefix`, or None if it is not under it."""
    p, pre = _split(path), _split(prefix)
    if _is_windows(prefix):
        p_cmp, pre_cmp = [s.casefold() for s in p], [s.casefold() for s in pre]
    else:
        p_cmp, pre_cmp = p, pre
    if p_cmp[: len(pre_cmp)] != pre_cmp:
        return None
    return p[len(pre) :]


class PathMapper:
    def __init__(self, mappings: Iterable[PathMapping]) -> None:
        self.mappings = list(mappings)

    def to_qbit(self, local: str) -> str:
        return self._translate(local, [(m.local, m.qbit) for m in self.mappings])

    def to_local(self, qbit: str) -> str:
        return self._translate(qbit, [(m.qbit, m.local) for m in self.mappings])

    @staticmethod
    def _translate(path: str, pairs: list[tuple[str, str]]) -> str:
        best: tuple[int, str, list[str]] | None = None
        for src, dst in pairs:
            rest = _strip_prefix(path, src)
            if rest is not None and (best is None or len(_split(src)) > best[0]):
                best = (len(_split(src)), dst, rest)
        return path if best is None else _join(best[1], best[2])


class MappedQbit:
    """The Qbit port seen through Path Mappings: callers only ever handle local paths."""

    def __init__(self, inner: Qbit, mapper: PathMapper) -> None:
        self._inner = inner
        self._mapper = mapper

    def _local(self, t: Torrent) -> Torrent:
        return replace(t, save_path=Path(self._mapper.to_local(str(t.save_path))))

    def torrents(self, tag: str | None = None) -> list[Torrent]:
        return [self._local(t) for t in self._inner.torrents(tag=tag)]

    def torrent(self, hash: str) -> Torrent | None:
        t = self._inner.torrent(hash)
        return self._local(t) if t else None

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        return self._inner.add(data, self._mapper.to_qbit(save_path), tags)

    def rename_file(self, hash: str, old: str, new: str) -> None:
        self._inner.rename_file(hash, old, new)

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None:
        self._inner.set_file_priority(hash, indexes, priority)

    def recheck(self, hash: str) -> None:
        self._inner.recheck(hash)

    def start(self, hash: str) -> None:
        self._inner.start(hash)

    def remove(self, hash: str) -> None:
        self._inner.remove(hash)

    def add_tags(self, hash: str, tags: list[str]) -> None:
        self._inner.add_tags(hash, tags)

    def remove_tags(self, hash: str, tags: list[str]) -> None:
        self._inner.remove_tags(hash, tags)
