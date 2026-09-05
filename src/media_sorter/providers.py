"""Metadata provider integrations for Media Sorter.

Provides interfaces and implementations for querying external metadata (TMDB, TVDB,
MusicBrainz) with rate-limiting, request caching, and offline fallbacks.
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ProviderResult:
    canonical_title: str
    year: Optional[int] = None
    media_type: str = "movie"  # movie, tv, anime, music
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    genres: List[str] = None
    confidence_boost: float = 0.15
    raw_payload: Optional[Dict[str, Any]] = None


class MetadataProvider(ABC):
    """Abstract base class for all metadata providers."""

    @abstractmethod
    def search_movie(self, title: str, year: Optional[int] = None) -> Optional[ProviderResult]:
        pass

    @abstractmethod
    def search_tv(self, title: str, year: Optional[int] = None, season: Optional[int] = None, episode: Optional[int] = None) -> Optional[ProviderResult]:
        pass

    @abstractmethod
    def search_music(self, artist: str, album: Optional[str] = None, title: Optional[str] = None) -> Optional[ProviderResult]:
        pass


class MemoryCache:
    """In-memory cache with TTL for metadata queries."""

    def __init__(self, ttl_seconds: int = 86400):
        self.ttl = ttl_seconds
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self._store:
            timestamp, data = self._store[key]
            if time.time() - timestamp < self.ttl:
                return data
            del self._store[key]
        return None

    def set(self, key: str, data: Any) -> None:
        self._store[key] = (time.time(), data)


class TMDBProvider(MetadataProvider):
    """TheMovieDatabase (TMDB) API provider with rate-limiting and caching."""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key: Optional[str] = None, rate_limit_per_second: float = 2.0, cache_ttl_seconds: int = 86400):
        self.api_key = api_key
        self.min_interval = 1.0 / max(rate_limit_per_second, 0.1)
        self.last_request_time = 0.0
        self.cache = MemoryCache(ttl_seconds=cache_ttl_seconds)

    def _throttle(self) -> None:
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    def _query(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None

        cache_key = f"tmdb:{endpoint}:{json.dumps(params, sort_keys=True)}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        self._throttle()
        req_params = dict(params)
        req_params["api_key"] = self.api_key

        try:
            resp = requests.get(f"{self.BASE_URL}/{endpoint}", params=req_params, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                self.cache.set(cache_key, data)
                return data
            logger.warning("TMDB request failed", status=resp.status_code, endpoint=endpoint)
        except Exception as e:
            logger.warning("TMDB network error", error=str(e))
        return None

    def search_movie(self, title: str, year: Optional[int] = None) -> Optional[ProviderResult]:
        params: Dict[str, Any] = {"query": title}
        if year:
            params["year"] = year

        data = self._query("search/movie", params)
        if not data or not data.get("results"):
            return None

        first = data["results"][0]
        release_date = first.get("release_date", "")
        res_year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else year

        return ProviderResult(
            canonical_title=first.get("title", title),
            year=res_year,
            media_type="movie",
            confidence_boost=0.15,
            raw_payload=first,
        )

    def search_tv(self, title: str, year: Optional[int] = None, season: Optional[int] = None, episode: Optional[int] = None) -> Optional[ProviderResult]:
        params: Dict[str, Any] = {"query": title}
        if year:
            params["first_air_date_year"] = year

        data = self._query("search/tv", params)
        if not data or not data.get("results"):
            return None

        first = data["results"][0]
        show_id = first.get("id")
        show_title = first.get("name", title)
        air_date = first.get("first_air_date", "")
        res_year = int(air_date[:4]) if len(air_date) >= 4 and air_date[:4].isdigit() else year

        ep_title = None
        if show_id and season is not None and episode is not None:
            ep_data = self._query(f"tv/{show_id}/season/{season}/episode/{episode}", {})
            if ep_data:
                ep_title = ep_data.get("name")

        return ProviderResult(
            canonical_title=show_title,
            year=res_year,
            media_type="tv",
            season=season,
            episode=episode,
            episode_title=ep_title,
            confidence_boost=0.20,
            raw_payload=first,
        )

    def search_music(self, artist: str, album: Optional[str] = None, title: Optional[str] = None) -> Optional[ProviderResult]:
        return None  # TMDB does not index music


class MusicBrainzProvider(MetadataProvider):
    """MusicBrainz WS2 API provider with courteous rate-limiting (1 req/sec)."""

    BASE_URL = "https://musicbrainz.org/ws/2"

    def __init__(self, rate_limit_per_second: float = 1.0, cache_ttl_seconds: int = 86400):
        self.min_interval = 1.0 / max(rate_limit_per_second, 0.1)
        self.last_request_time = 0.0
        self.cache = MemoryCache(ttl_seconds=cache_ttl_seconds)

    def _throttle(self) -> None:
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    def search_movie(self, title: str, year: Optional[int] = None) -> Optional[ProviderResult]:
        return None

    def search_tv(self, title: str, year: Optional[int] = None, season: Optional[int] = None, episode: Optional[int] = None) -> Optional[ProviderResult]:
        return None

    def search_music(self, artist: str, album: Optional[str] = None, title: Optional[str] = None) -> Optional[ProviderResult]:
        query_parts = [f'artist:"{artist}"']
        if album:
            query_parts.append(f'release:"{album}"')
        if title:
            query_parts.append(f'recording:"{title}"')

        query_str = " AND ".join(query_parts)
        cache_key = f"mb:{query_str}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        self._throttle()
        headers = {"User-Agent": "MediaSorter/0.1.0 (https://github.com/example/media-sorter)"}
        params = {"query": query_str, "fmt": "json", "limit": 1}

        try:
            resp = requests.get(f"{self.BASE_URL}/recording", params=params, headers=headers, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                recordings = data.get("recordings", [])
                if recordings:
                    rec = recordings[0]
                    rec_title = rec.get("title", title or "")
                    # Extract release info
                    releases = rec.get("releases", [])
                    rec_album = releases[0].get("title", album) if releases else album
                    release_date = releases[0].get("date", "") if releases else ""
                    res_year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else None

                    res = ProviderResult(
                        canonical_title=rec_title,
                        artist=artist,
                        album=rec_album,
                        year=res_year,
                        media_type="music",
                        confidence_boost=0.15,
                        raw_payload=rec,
                    )
                    self.cache.set(cache_key, res)
                    return res
        except Exception as e:
            logger.warning("MusicBrainz network error", error=str(e))
        return None


class MockMetadataProvider(MetadataProvider):
    """Deterministic mock provider for offline testing and fixture validation."""

    def __init__(self, mock_data: Optional[Dict[str, ProviderResult]] = None):
        self.mock_data = mock_data or {}

    def search_movie(self, title: str, year: Optional[int] = None) -> Optional[ProviderResult]:
        key = f"movie:{title.lower()}"
        return self.mock_data.get(key)

    def search_tv(self, title: str, year: Optional[int] = None, season: Optional[int] = None, episode: Optional[int] = None) -> Optional[ProviderResult]:
        key = f"tv:{title.lower()}"
        return self.mock_data.get(key)

    def search_music(self, artist: str, album: Optional[str] = None, title: Optional[str] = None) -> Optional[ProviderResult]:
        key = f"music:{artist.lower()}"
        return self.mock_data.get(key)
