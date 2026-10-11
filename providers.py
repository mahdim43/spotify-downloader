#!/usr/bin/env python3
"""
providers.py
============

A small registry of audio sources the downloader can pull music from, plus a
"search once, try each provider in turn" fallback helper.

Why a provider layer?
---------------------
Different sites behave differently:

* **YouTube** (``ytsearch1:``) and **SoundCloud** (``scsearch1:``) both support
  yt-dlp *search* — you give them a song name and they return matches.
* **Bandcamp / Audiomack / Yandex Music** have no working search prefix in some
  yt-dlp builds, but you can download them from a **direct URL**.
* Some sites (YouTube) block datacenter IPs, others (SoundCloud) don't — so it
  helps to try several and use whichever works.

This module centralises that knowledge so the downloader stays simple.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    """Description of a single audio source.

    Attributes
    ----------
    key:
        Short internal name, e.g. ``"youtube"``.
    label:
        Human-friendly name for messages, e.g. ``"YouTube"``.
    search_prefix:
        A yt-dlp search prefix that works for this provider (e.g.
        ``"scsearch1:"``), or ``None`` if the provider has no search and can
        only be used from a direct URL. The downloader strips the trailing
        count and re-requests several results, so the exact number here is not
        important.
    """

    key: str
    label: str
    search_prefix: str | None = None


# Providers that support *searching by song name* (in fallback order).
# SoundCloud is tried first because it is generally more permissive about
# automated downloads than YouTube; YouTube is the reliable fallback.
#
# The prefix is a *base* yt-dlp search prefix (no result count). The downloader
# appends a count (SEARCH_RESULTS) when it builds the query so it fetches several
# results and can skip 30-second previews in favour of a full-length match.
SEARCH_PROVIDERS: list[Provider] = [
    Provider("soundcloud", "SoundCloud", "scsearch:"),
    Provider("youtube", "YouTube", "ytsearch:"),
]

# Providers that only work from a direct URL (no search prefix).
URL_ONLY_PROVIDERS: dict[str, Provider] = {
    "bandcamp": Provider("bandcamp", "Bandcamp"),
    "audiomack": Provider("audiomack", "Audiomack"),
    "yandexmusic": Provider("yandexmusic", "Yandex Music"),
}

# Map yt-dlp's provider keys to our Provider, used when a user points at a
# direct URL so we can show a friendly source label.
_BY_KEY: dict[str, Provider] = {p.key: p for p in SEARCH_PROVIDERS}
_BY_KEY.update(URL_ONLY_PROVIDERS)


def search_prefixes() -> list[str]:
    """Return the list of usable search prefixes, in fallback order."""
    return [p.search_prefix for p in SEARCH_PROVIDERS if p.search_prefix]


def provider_for_url(url: str) -> Provider | None:
    """Best-effort guess of which provider a direct *url* belongs to.

    Used only for pretty logging; returns ``None`` when unknown.
    """
    u = url.lower()
    if "soundcloud.com" in u:
        return _BY_KEY["soundcloud"]
    if "youtube.com" in u or "youtu.be" in u:
        return _BY_KEY["youtube"]
    if "bandcamp.com" in u:
        return _BY_KEY["bandcamp"]
    if "audiomack.com" in u:
        return _BY_KEY["audiomack"]
    if "music.yandex" in u:
        return _BY_KEY["yandexmusic"]
    return None
