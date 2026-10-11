#!/usr/bin/env python3
"""
deezer.py
=========

Helpers to read track / album / playlist information from Deezer so it can be
fed to the yt-dlp based downloader.

Why this module exists
----------------------
Deezer's full-length streams are DRM-protected (only 30-second previews are
publicly downloadable), exactly like Spotify. What we *can* do is read the
**public metadata** (song titles, artists, album names and cover art) from
Deezer's public API — which needs **no login or API token** — and then find a
matching full audio track on a streaming provider (YouTube, SoundCloud, ...)
using yt-dlp.

How it works
------------
Deezer exposes a simple, open JSON API at ``https://api.deezer.com``::

    GET /track/<id>       -> a single track's metadata
    GET /album/<id>       -> an album (with its tracks inline)
    GET /playlist/<id>    -> a playlist (tracks paginated via "next")

This module turns those responses into a list of :class:`DeezerTrack` objects.

Only the standard library plus ``requests`` are used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests

# Deezer's public, unauthenticated JSON API.
API_BASE = "https://api.deezer.com"

# A realistic desktop User-Agent keeps the API happy.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_HEADERS = {"User-Agent": _USER_AGENT, "Accept-Language": "en"}

# Match Deezer URLs / URIs, tolerating an optional country prefix ("/en/",
# "/us/", ...) and an optional "www." host. The numeric id must be a complete
# path segment (not a leading-digit prefix of a longer token). Examples::
#
#   https://www.deezer.com/track/3135556
#   https://www.deezer.com/en/album/185386862
#   https://deezer.com/us/playlist/6298161304?utm_source=...
_DEEZER_URL_RE = re.compile(
    r"deezer\.(?:com|page\.link)/(?:[a-z]{2}/)?(track|album|playlist)/(\d+)"
    r"(?![0-9A-Za-z])",
    re.IGNORECASE,
)


class DeezerError(Exception):
    """Raised when a Deezer URL cannot be parsed or metadata fetched."""


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class DeezerTrack:
    """A single song we want to download, described by its Deezer metadata."""

    track_id: str
    title: str
    artists: str            # "Artist A, Artist B"
    album: str | None = None
    cover_url: str | None = None
    duration: int | None = None          # seconds, used to skip short previews

    def search_query(self) -> str:
        """Build a good search string for finding this song on a provider."""
        # e.g. "Aya Nakamura - Copines"
        if self.artists:
            return f"{self.artists} - {self.title}"
        return self.title


# --------------------------------------------------------------------------- #
# URL parsing
# --------------------------------------------------------------------------- #
@dataclass
class DeezerRef:
    """A parsed Deezer reference: what kind of thing it is and its id."""

    kind: str   # "track" | "album" | "playlist"
    deezer_id: str
    url: str


def is_deezer_url(text: str) -> bool:
    """Return True if *text* looks like a Deezer track/album/playlist link."""
    return _DEEZER_URL_RE.search(text.strip()) is not None


def parse_deezer_url(url: str) -> DeezerRef:
    """Parse a Deezer URL into a :class:`DeezerRef`.

    Accepts inputs such as::

        https://www.deezer.com/track/3135556
        https://www.deezer.com/en/album/185386862
        https://deezer.com/us/playlist/6298161304?utm=...

    Raises :class:`DeezerError` if the string is not a usable Deezer link.
    """
    url = url.strip()
    match = _DEEZER_URL_RE.search(url)
    if not match:
        raise DeezerError(f"Not a Deezer track/album/playlist link: {url!r}")
    kind, deezer_id = match.group(1).lower(), match.group(2)
    return DeezerRef(kind=kind, deezer_id=deezer_id, url=url)


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _api_get(path: str, params: dict | None = None) -> dict:
    """GET a JSON object from the Deezer API. Raises :class:`DeezerError`."""
    url = f"{API_BASE}{path}"
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=20)
    except requests.RequestException as exc:
        raise DeezerError(f"Could not reach the Deezer API: {exc}") from exc

    if resp.status_code != 200:
        raise DeezerError(
            f"Deezer API returned HTTP {resp.status_code} for {url}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise DeezerError("Deezer API returned non-JSON data.") from exc


# --------------------------------------------------------------------------- #
# Metadata extraction
# --------------------------------------------------------------------------- #
def _artists_from(artists) -> str:
    """Normalise a Deezer ``artist``/``artists`` field into a joined string."""
    if isinstance(artists, list):
        names = [
            a.get("name") for a in artists if isinstance(a, dict) and a.get("name")
        ]
        return ", ".join(names)
    if isinstance(artists, dict):
        return artists.get("name") or ""
    if isinstance(artists, str):
        return artists
    return ""


def _best_cover(album) -> str | None:
    """Return the best available cover-art URL from an ``album`` object."""
    if isinstance(album, dict):
        # Prefer the largest cover Deezer offers.
        return (
            album.get("cover_xl")
            or album.get("cover_big")
            or album.get("cover_medium")
            or album.get("cover")
        )
    if isinstance(album, str):
        return album
    return None


def _track_from_api(item: dict, album_name: str | None = None,
                    cover: str | None = None) -> DeezerTrack:
    """Build a :class:`DeezerTrack` from an API track object."""
    album = item.get("album") if isinstance(item.get("album"), dict) else None
    title = item.get("title_short") or item.get("title") or ""
    if not title:
        raise DeezerError("Encountered a Deezer track with no title.")
    return DeezerTrack(
        track_id=str(item.get("id", "unknown")),
        title=title,
        artists=_artists_from(item.get("artist")),
        album=album_name or (album.get("title") if album else None),
        cover_url=cover or _best_cover(album),
        duration=item.get("duration"),
    )


def _paginate(collection: dict):
    """Yield every item in a Deezer paginated collection (follows ``next``).

    Deezer playlist responses look like::

        {"data": [...], "next": "https://api.deezer.com/playlist/1/tracks?index=50"}

    The first page is already inlined in the playlist object; subsequent pages
    are fetched by following ``next`` (a full URL).
    """
    if not isinstance(collection, dict):
        return
    page = collection
    seen_next = set()
    while page:
        for item in page.get("data") or []:
            yield item
        nxt = page.get("next")
        if not nxt or nxt in seen_next:
            break
        seen_next.add(nxt)
        page = _api_get(nxt.replace(API_BASE, ""))


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
def get_tracks(url: str) -> list[DeezerTrack]:
    """Resolve a Deezer URL into a list of :class:`DeezerTrack`.

    * A **track** link yields a one-element list.
    * An **album** or **playlist** link yields every track it contains.
    """
    ref = parse_deezer_url(url)

    if ref.kind == "track":
        data = _api_get(f"/track/{ref.deezer_id}")
        if not data or data.get("id") is None:
            raise DeezerError(f"Deezer track not found: {ref.deezer_id}")
        return [_track_from_api(data)]

    if ref.kind == "album":
        data = _api_get(f"/album/{ref.deezer_id}")
        if not data or data.get("id") is None:
            raise DeezerError(f"Deezer album not found: {ref.deezer_id}")
        album_name = data.get("title")
        cover = _best_cover(data)
        track_items = (data.get("tracks") or {}).get("data") or []
        tracks = [_track_from_api(it, album_name, cover) for it in track_items]
        if not tracks:
            raise DeezerError("The Deezer album contained no tracks.")
        return tracks

    if ref.kind == "playlist":
        data = _api_get(f"/playlist/{ref.deezer_id}")
        if not data or data.get("id") is None:
            raise DeezerError(f"Deezer playlist not found: {ref.deezer_id}")
        cover = _best_cover(data) or data.get("picture_xl")
        tracks = [
            _track_from_api(it, cover=cover) for it in _paginate(data.get("tracks"))
        ]
        if not tracks:
            raise DeezerError("The Deezer playlist contained no tracks.")
        return tracks

    raise DeezerError(
        f"Deezer {ref.kind!r} links are not supported (only track/album/playlist)."
    )


def search(query: str, limit: int = 10) -> list[DeezerTrack]:
    """Search Deezer for *query* and return matching tracks.

    Useful for quick lookups and for testing without a specific URL.
    """
    data = _api_get("/search", params={"q": query, "limit": limit})
    results = data.get("data") or []
    return [_track_from_api(item) for item in results]

