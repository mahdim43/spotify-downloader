#!/usr/bin/env python3
"""
spotify.py
==========

Helpers to read track / album / playlist information from Spotify so it can be
fed to the yt-dlp based downloader.

Why this module exists
----------------------
Spotify streams are DRM-protected and cannot be downloaded directly. What we
*can* do is read the **public metadata** (song titles, artists, album names and
cover art) and then find a matching audio track on another site (e.g. YouTube)
using yt-dlp.

How it works
------------
Spotify's public *embed* pages (``open.spotify.com/embed/<kind>/<id>``) render a
``__NEXT_DATA__`` JSON blob that already contains everything we need, and they do
**not** require any login or API token. This module fetches that page and turns
it into a small list of :class:`SpotifyTrack` objects.

Only the standard library plus ``requests`` are used.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

# A realistic desktop User-Agent keeps the embed pages happy.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_HEADERS = {"User-Agent": _USER_AGENT, "Accept-Language": "en"}

# Regular expression that pulls the embedded JSON out of the page.
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


class SpotifyError(Exception):
    """Raised when a Spotify URL cannot be parsed or metadata fetched."""


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class SpotifyTrack:
    """A single song we want to download, described by its Spotify metadata."""

    track_id: str
    title: str
    artists: str            # "Artist A, Artist B"
    album: str | None = None
    cover_url: str | None = None
    duration: int | None = None     # seconds, used to skip short previews

    def search_query(self) -> str:
        """Build a good search string for finding this song on YouTube."""
        # e.g. "Rick Astley - Never Gonna Give You Up"
        if self.artists:
            return f"{self.artists} - {self.title}"
        return self.title


# --------------------------------------------------------------------------- #
# URL parsing
# --------------------------------------------------------------------------- #
@dataclass
class SpotifyRef:
    """A parsed Spotify reference: what kind of thing it is and its id."""

    kind: str   # "track" | "album" | "playlist" | "artist"
    spotify_id: str
    url: str


def parse_spotify_url(url: str) -> SpotifyRef:
    """Parse a Spotify URL or ``spotify:`` URI into a :class:`SpotifyRef`.

    Accepts inputs such as::

        https://open.spotify.com/track/<id>
        https://open.spotify.com/album/<id>?si=...
        https://open.spotify.com/intl-de/playlist/<id>
        spotify:track:<id>

    Raises :class:`SpotifyError` if the string is not a Spotify link.
    """
    url = url.strip()

    # spotify:track:<id> style URIs
    if url.startswith("spotify:"):
        parts = url.split(":")
        if len(parts) >= 3:
            kind, spotify_id = parts[1], parts[2]
            return SpotifyRef(kind, spotify_id, url)
        raise SpotifyError(f"Malformed Spotify URI: {url!r}")

    parsed = urlparse(url)
    if "spotify.com" not in (parsed.netloc or ""):
        raise SpotifyError(f"Not a Spotify URL: {url!r}")

    # Path looks like /track/<id>, /intl-de/album/<id>, /playlist/<id> ...
    segments = [seg for seg in parsed.path.split("/") if seg]
    if len(segments) < 2:
        raise SpotifyError(f"Could not read Spotify id from: {url!r}")

    kind = segments[-2]
    spotify_id = segments[-1]
    if kind not in ("track", "album", "playlist", "artist", "episode", "show"):
        raise SpotifyError(f"Unsupported Spotify type {kind!r} in: {url!r}")

    return SpotifyRef(kind, spotify_id, url)


def is_spotify_url(text: str) -> bool:
    """Return True if *text* looks like a Spotify link / URI."""
    try:
        parse_spotify_url(text)
        return True
    except SpotifyError:
        return False


# --------------------------------------------------------------------------- #
# Metadata fetching via the public embed page
# --------------------------------------------------------------------------- #
def _fetch_next_data(ref: SpotifyRef, timeout: int = 20) -> dict:
    """Download the embed page for *ref* and return its ``__NEXT_DATA__`` dict."""
    embed_url = f"https://open.spotify.com/embed/{ref.kind}/{ref.spotify_id}"
    try:
        resp = requests.get(embed_url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise SpotifyError(f"Failed to fetch Spotify embed page: {exc}") from exc

    match = _NEXT_DATA_RE.search(resp.text)
    if not match:
        raise SpotifyError("Could not find metadata in the Spotify embed page.")

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SpotifyError(f"Spotify metadata was not valid JSON: {exc}") from exc


def _extract_entity(data: dict) -> dict:
    """Pull the ``entity`` object out of the parsed ``__NEXT_DATA__`` dict."""
    try:
        return data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError) as exc:
        raise SpotifyError("Unexpected Spotify metadata structure.") from exc


def _artists_from(artists) -> str:
    """Normalise Spotify's artist field(s) into a comma-joined string."""
    if isinstance(artists, list):
        names = [
            a.get("name") for a in artists if isinstance(a, dict) and a.get("name")
        ]
        return ", ".join(names)
    if isinstance(artists, str):
        return artists
    return ""


def _best_cover(entity: dict) -> str | None:
    """Return the largest available cover-art URL, if any."""
    vi = entity.get("visualIdentity") or {}
    image = vi.get("image") if isinstance(vi, dict) else None
    if isinstance(image, dict):
        # Prefer the largest "sources" entry when present.
        sources = image.get("sources")
        if isinstance(sources, list) and sources:
            return sources[0].get("url")
        return image.get("url")
    if isinstance(image, str):
        return image
    return None


def _duration_seconds(entity: dict) -> int | None:
    """Return the track length in whole seconds, or ``None`` if unknown.

    Spotify's embed entity stores ``duration`` in **milliseconds**; playlist
    items sometimes carry ``duration`` in seconds instead, so we normalise both.
    """
    dur = entity.get("duration")
    if isinstance(dur, (int, float)) and dur > 0:
        # Heuristic: values above ~6000 are almost certainly milliseconds.
        if dur > 6000:
            return int(round(dur / 1000))
        return int(round(dur))
    return None


def get_tracks(url: str) -> list[SpotifyTrack]:
    """Resolve a Spotify URL/URI into a list of :class:`SpotifyTrack`.

    * A **track** link yields a one-element list.
    * An **album** or **playlist** link yields every track it contains.
    """
    ref = parse_spotify_url(url)

    if ref.kind == "track":
        return [_track_from_entity(_extract_entity(_fetch_next_data(ref)))]

    if ref.kind in ("album", "playlist"):
        entity = _extract_entity(_fetch_next_data(ref))
        album_name = entity.get("name") or entity.get("title")
        cover = _best_cover(entity)
        track_list = entity.get("trackList") or []
        tracks: list[SpotifyTrack] = []
        for item in track_list:
            if not isinstance(item, dict):
                continue
            # Some entries are not real tracks (episodes / nulls); skip them.
            if item.get("entityType") not in (None, "track"):
                continue
            if not item.get("uri"):
                continue
            track_id = item["uri"].split(":")[-1]
            title = item.get("title") or ""
            artists = item.get("subtitle") or ""
            if not title:
                continue
            tracks.append(
                SpotifyTrack(
                    track_id=track_id,
                    title=title,
                    artists=artists,
                    album=album_name,
                    cover_url=cover,
                    duration=_duration_seconds(item),
                )
            )
        if not tracks:
            raise SpotifyError("The Spotify album/playlist contained no tracks.")
        return tracks

    raise SpotifyError(
        f"Spotify {ref.kind!r} links are not supported (only track/album/playlist)."
    )


def _track_from_entity(entity: dict) -> SpotifyTrack:
    """Build a :class:`SpotifyTrack` from a single-track ``entity``."""
    title = entity.get("name") or entity.get("title") or ""
    artists = _artists_from(entity.get("artists"))
    track_id = entity.get("id")
    if not track_id and entity.get("uri"):
        track_id = entity["uri"].split(":")[-1]
    album = None
    alb = entity.get("album")
    if isinstance(alb, dict):
        album = alb.get("name")
    return SpotifyTrack(
        track_id=track_id or "unknown",
        title=title,
        artists=artists,
        album=album,
        cover_url=_best_cover(entity),
        duration=_duration_seconds(entity),
    )

