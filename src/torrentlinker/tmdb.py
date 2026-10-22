"""Optional TMDb lookup of a title, for searching an Indexer by ID."""

from __future__ import annotations

import httpx

from torrentlinker import net
from torrentlinker.domain import ContentKind

API = "https://api.themoviedb.org/3"


class Tmdb:
    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._key = api_key
        self._http = http or net.client(timeout=15)

    def lookup(self, title: str, year: int | None, kind: ContentKind) -> str | None:
        if kind is ContentKind.MOVIE:
            path, year_param = "/search/movie", "year"
        elif kind is ContentKind.SERIES:
            path, year_param = "/search/tv", "first_air_date_year"
        else:
            return None
        params = {"query": title}
        if year:
            params[year_param] = str(year)
        headers = {}
        if len(self._key) > 40:  # a v4 read access token
            headers["Authorization"] = f"Bearer {self._key}"
        else:
            params["api_key"] = self._key
        response = self._http.get(API + path, params=params, headers=headers)
        response.raise_for_status()
        results = response.json().get("results") or []
        return str(results[0]["id"]) if results else None
