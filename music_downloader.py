#!/usr/bin/env python3
"""
music_downloader.py
===================

A simple, friendly command-line music downloader built on top of `yt-dlp`.

Features
--------
* Download audio from any site supported by yt-dlp (YouTube, SoundCloud, ...).
* **Spotify & Deezer support** — paste a track, album, or playlist link and the
  tool reads the song list from Spotify/Deezer, then finds each song on a
  streaming provider (SoundCloud/YouTube).
* **Multiple providers** — music is fetched from whichever source works first
  (SoundCloud, YouTube, ...). Choose one with ``--source`` or let it auto-fall-back.
* Accept a direct URL **or** a plain search term (e.g. ``never gonna give you up``).
* Converts audio to MP3 (default) or other formats using ffmpeg.
* Embeds metadata (title, artist, album art) into the downloaded file.
* Handles single tracks, playlists, and a batch of queries from a file.
* Progress reporting and tidy, colourised console output.

Requirements
------------
* Python 3.8+
* yt-dlp      -> pip install yt-dlp
* requests    -> pip install requests   (for Spotify & Deezer links)
* ffmpeg      -> https://ffmpeg.org/  (must be on your PATH)
* deno/node   -> optional; lets yt-dlp extract from YouTube (auto-detected)

Usage examples
--------------
    # Download a single track by URL
    python music_downloader.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # Search for a song by name (takes the first match)
    python music_downloader.py -s "daft punk one more time"

    # Download a whole playlist into a folder
    python music_downloader.py -s "PLAYLIST_URL" --playlist

    # Download a Spotify track / album / playlist
    python music_downloader.py "https://open.spotify.com/album/<id>"

    # Download a Deezer track / album / playlist
    python music_downloader.py "https://www.deezer.com/album/185386862"

    # Force a specific provider (auto = try SoundCloud then YouTube)
    python music_downloader.py -s "daft punk one more time" --source youtube

    # Download everything listed in a text file (one query/URL per line)
    python music_downloader.py --batch songs.txt
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass, field

# Optional mutagen for reliably retagging files whose provider metadata would
# otherwise overwrite the true (Spotify/Deezer) title/artist/album.
try:
    import mutagen
    from mutagen.id3 import ID3, TALB, TCON, TDRC, TPE1, TPUB, TRCK
    _MUTAGEN_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive
    _MUTAGEN_AVAILABLE = False

try:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
except ImportError:  # pragma: no cover - defensive
    sys.stderr.write(
        "yt-dlp is not installed. Install it with:  pip install yt-dlp\n"
    )
    raise SystemExit(1)

# Optional Spotify support. Imported lazily-safe: if `requests` or `spotify.py`
# are unavailable we still let the tool run for non-Spotify URLs.
try:
    from spotify import SpotifyError, get_tracks, is_spotify_url
    _SPOTIFY_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive
    _SPOTIFY_AVAILABLE = False
    SpotifyError = Exception  # type: ignore[assignment]

    def is_spotify_url(_text: str) -> bool:  # type: ignore[misc]
        return False

    def get_tracks(_url: str):  # type: ignore[misc]
        raise SpotifyError("Spotify support is unavailable (missing requests/spotify.py).")

# Optional Deezer support (same pattern as Spotify above).
try:
    from deezer import DeezerError, get_tracks as deezer_get_tracks, is_deezer_url
    _DEEZER_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive
    _DEEZER_AVAILABLE = False
    DeezerError = Exception  # type: ignore[assignment]

    def is_deezer_url(_text: str) -> bool:  # type: ignore[misc]
        return False

    def deezer_get_tracks(_url: str):  # type: ignore[misc]
        raise DeezerError("Deezer support is unavailable (missing requests/deezer.py).")

# Provider registry (SoundCloud / YouTube search + Bandcamp/Audiomack/... URLs).
try:
    import providers as _providers
except ImportError:  # pragma: no cover - defensive
    _providers = None

# How many search results to fetch per provider so the duration guard has a
# choice of matches (the first result is often a short preview).
SEARCH_RESULTS = 5


# --------------------------------------------------------------------------- #
# Small helpers for pretty console output
# --------------------------------------------------------------------------- #
class C:
    """ANSI colour codes (gracefully disabled when not a TTY)."""

    _enabled = sys.stdout.isatty()

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"

    @classmethod
    def wrap(cls, code: str, text: str) -> str:
        return f"{code}{text}{cls.RESET}" if cls._enabled else text


def info(msg: str) -> None:
    print(C.wrap(C.CYAN, "ℹ ") + msg)


def success(msg: str) -> None:
    print(C.wrap(C.GREEN, "✔ ") + msg)


def warn(msg: str) -> None:
    print(C.wrap(C.YELLOW, "⚠ ") + msg)


def error(msg: str) -> None:
    print(C.wrap(C.RED, "✖ ") + msg, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass
class DownloadConfig:
    """Runtime configuration for a download session."""

    output_dir: str = "downloads"
    audio_format: str = "mp3"          # output container / codec target
    audio_quality: str = "0"           # yt-dlp quality (0 = best for Vorbis/MP3)
    allow_playlist: bool = False
    keep_video: bool = False           # if True, download full video instead
    embed_thumbnail: bool = True
    add_metadata: bool = True
    quiet: bool = False
    # Which provider to search for audio: "auto" (try each in turn), or the
    # key of a specific provider, e.g. "youtube" or "soundcloud".
    source: str = "auto"
    # Browser to pull cookies from (e.g. "chrome"), mirroring yt-dlp's
    # ``--cookies-from-browser``. None disables cookie use.
    cookies_from_browser: str | None = None
    # Number of threads used by ffmpeg for post-processing.
    concurrent_fragments: int = 4
    extra: dict = field(default_factory=dict)


class MusicDownloader:
    """Thin, friendly wrapper around ``yt_dlp.YoutubeDL``."""

    # How many search results to attempt per provider before giving up on it.
    _MAX_CANDIDATES = 5

    def __init__(self, config: DownloadConfig | None = None) -> None:
        self.config = config or DownloadConfig()
        self._check_ffmpeg()
        os.makedirs(self.config.output_dir, exist_ok=True)
        # yt-dlp 2026.x fires each postprocessor "started" hook twice (with the
        # same info_dict). We track what we've already printed so each step is
        # shown only once. See _postprocessor_hook.
        self._seen_pp_events: set[tuple] = set()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _detect_js_runtime() -> dict | None:
        """Return a yt-dlp ``js_runtimes`` dict if a runtime is available.

        Recent yt-dlp needs a JavaScript runtime (Deno or Node) to solve some of
        YouTube's signature challenges. We auto-detect one on PATH so the tool
        "just works" without the user passing ``--js-runtimes`` manually.

        Returns a mapping like ``{"deno": {"path": "/usr/bin/deno"}}``, which is
        the format yt-dlp's Python API expects, or ``None`` if no runtime is
        found.
        """
        # Deno is yt-dlp's preferred runtime; Node is a fine fallback.
        for name in ("deno", "node"):
            path = shutil.which(name)
            if path:
                return {name: {"path": path}}
        return None

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_cookies_from_browser(spec: str) -> tuple:
        """Parse a ``--cookies-from-browser`` spec into the tuple yt-dlp wants.

        The spec format matches yt-dlp's CLI::

            BROWSER[+KEYRING][:PROFILE][::CONTAINER]

        e.g. ``chrome``, ``chrome:Default``, ``firefox::work``. Returns the
        4-tuple ``(browser, profile, keyring, container)``. Raises
        :class:`ValueError` for an unsupported/blank browser.
        """
        spec = (spec or "").strip()
        if not spec:
            raise ValueError("no browser specified for --cookies-from-browser")

        mobj = re.fullmatch(
            r"""(?x)
                (?P<name>[^+:]+)
                (?:\s*\+\s*(?P<keyring>[^:]+))?
                (?:\s*:\s*(?!:)(?P<profile>.+?))?
                (?:\s*::\s*(?P<container>.+))?
            """,
            spec,
        )
        if mobj is None:
            raise ValueError(f"invalid --cookies-from-browser spec: {spec!r}")

        browser, keyring, profile, container = mobj.group(
            "name", "keyring", "profile", "container"
        )
        browser = browser.lower()

        from yt_dlp.cookies import SUPPORTED_BROWSERS

        if browser not in SUPPORTED_BROWSERS:
            raise ValueError(
                f"unsupported browser for cookies: {browser!r}. "
                f"Supported: {', '.join(sorted(SUPPORTED_BROWSERS))}"
            )
        return (browser, profile, keyring, container)

    # ------------------------------------------------------------------ #
    def _check_ffmpeg(self) -> None:
        """Warn (but don't crash) if ffmpeg is missing and it is required."""
        needs_ffmpeg = self.config.embed_thumbnail or not self.config.keep_video
        if needs_ffmpeg and shutil.which("ffmpeg") is None:
            warn(
                "ffmpeg was not found on your PATH. Audio extraction and "
                "thumbnail embedding require it. Install from https://ffmpeg.org/"
            )

    # ------------------------------------------------------------------ #
    def _build_output_template(self, group_by_artist: bool = True) -> str:
        """Return a yt-dlp ``-o`` output template.

        * ``group_by_artist=True``  -> ``<output_dir>/<artist>/<title> [<id>].<ext>``
          (used for albums/playlists so songs are grouped neatly).
        * ``group_by_artist=False`` -> ``<output_dir>/<title> [<id>].<ext>``
          (used for a single song, which drops straight into the output dir).
        """
        if group_by_artist:
            return os.path.join(
                self.config.output_dir, "%(uploader)s", "%(title)s [%(id)s].%(ext)s"
            )
        return os.path.join(
            self.config.output_dir, "%(title)s [%(id)s].%(ext)s"
        )

    # ------------------------------------------------------------------ #
    def _build_options(self, group_by_artist: bool = True) -> dict:
        """Assemble the options dict passed to ``YoutubeDL``.

        ``group_by_artist`` controls the output path: ``True`` nests files under
        an ``<artist>/`` folder (used for albums/playlists), ``False`` writes
        them straight into the output dir (used for a single song).
        """
        opts: dict = {
            "outtmpl": self._build_output_template(group_by_artist=group_by_artist),
            "quiet": self.config.quiet,
            "no_warnings": self.config.quiet,
            "noprogress": self.config.quiet,
            "concurrent_fragment_downloads": self.config.concurrent_fragments,
            "ignoreerrors": True,   # keep going if one item in a playlist fails
            "noplaylist": not self.config.allow_playlist,
            "restrictfilenames": False,
            "windowsfilenames": True,
            "postprocessors": [],
        }

        # Let yt-dlp use a JavaScript runtime (Deno/Node) if one is installed,
        # so YouTube extraction doesn't fail with "No supported JavaScript
        # runtime could be found".
        js_runtime = self._detect_js_runtime()
        if js_runtime and "js_runtimes" not in self.config.extra:
            opts["js_runtimes"] = js_runtime

        # Pull cookies from a browser (e.g. Chrome) when the user asked for it.
        # This is what lets yt-dlp past YouTube's "Sign in to confirm you're
        # not a bot" check using the user's own logged-in session.
        if self.config.cookies_from_browser and "cookiesfrombrowser" not in self.config.extra:
            try:
                opts["cookiesfrombrowser"] = self._parse_cookies_from_browser(
                    self.config.cookies_from_browser
                )
            except ValueError as exc:
                error(str(exc))
                raise SystemExit(2)

        if not self.config.keep_video:
            # Extract the best available audio and convert it.
            opts["format"] = "bestaudio/best"
            opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.config.audio_format,
                    "preferredquality": self.config.audio_quality,
                }
            )
            if self.config.embed_thumbnail:
                opts["writethumbnail"] = True
                opts["postprocessors"].append({"key": "EmbedThumbnail"})
            if self.config.add_metadata:
                opts["postprocessors"].append({"key": "FFmpegMetadata"})
        else:
            # Full video download, best quality up to 1080p merged with audio.
            opts["format"] = "bestvideo[height<=1080]+bestaudio/best"
            opts["merge_output_format"] = (
                self.config.audio_format
                if self.config.audio_format != "mp3"
                else "mkv"
            )

        # Progress / logging hooks
        opts["progress_hooks"] = [self._progress_hook]
        opts["postprocessor_hooks"] = [self._postprocessor_hook]
        opts.update(self.config.extra)
        return opts

    # ------------------------------------------------------------------ #
    @staticmethod
    def _looks_like_url(term: str) -> bool:
        """Very small heuristic: does this look like a web URL?"""
        return term.startswith(
            ("http://", "https://", "www.", "youtube.com", "youtu.be")
        )

    def _resolve_query(self, term: str) -> str:
        """Turn a search term into a yt-dlp compatible target."""
        if self._looks_like_url(term):
            return term
        # Use the first configured provider's search prefix (SoundCloud by
        # default; falls back to YouTube). ``scsearch1:``/``ytsearch1:`` grab the
        # single best match for the given keywords.
        prefix = self._provider_prefixes()[0]
        return f"{prefix}{term}"

    # ------------------------------------------------------------------ #
    # yt-dlp hooks
    # ------------------------------------------------------------------ #
    @staticmethod
    def _progress_hook(d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            pct = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "").strip()
            filename = d.get("filename", "")
            base = os.path.basename(filename) if filename else ""
            # \r keeps everything on one line for a live progress feel.
            sys.stdout.write(
                f"\r{C.wrap(C.DIM, '  downloading')} {pct} "
                f"{C.wrap(C.DIM, speed)}  {base[:40]}"
            )
            sys.stdout.flush()
        elif status == "finished":
            sys.stdout.write("\n")

    def _postprocessor_hook(self, d: dict) -> None:
        """Print a one-line note when a post-processing step starts.

        yt-dlp 2026.x dispatches each "started" event twice with the *same*
        ``info_dict`` object, which made every step look like it ran twice (even
        though only one file is produced). We key on ``id(info_dict)`` plus the
        postprocessor name and status so each real step prints exactly once.
        """
        if d.get("status") != "started":
            return
        name = d.get("postprocessor", "processing")
        info_dict = d.get("info_dict")
        key = (id(info_dict), name, d.get("status"))
        if key in self._seen_pp_events:
            return
        self._seen_pp_events.add(key)
        sys.stdout.write(f"{C.wrap(C.DIM, '  -> ' + name)}...\n")
        sys.stdout.flush()

    # ------------------------------------------------------------------ #
    def download(self, target: str) -> int:
        """Download a single URL/search term. Returns number of files saved.

        Routing logic:

        * Spotify link  -> read metadata, then find each track on a provider.
        * Deezer link   -> read metadata, then find each track on a provider.
        * Anything else -> hand the URL/search term straight to yt-dlp.
        """
        # --- Spotify branch -------------------------------------------------
        if is_spotify_url(target):
            return self.download_metadata_url(target, service="Spotify")

        # --- Deezer branch --------------------------------------------------
        if is_deezer_url(target):
            return self.download_metadata_url(target, service="Deezer")

        resolved = self._resolve_query(target)
        is_url = self._looks_like_url(target)
        label = target if is_url else f"search: {target}"
        info(f"Fetching {C.wrap(C.BOLD, label)}")

        # A single URL/search term is one song -> keep it flat in the output
        # dir (no artist subfolder).
        opts = self._build_options(group_by_artist=False)
        saved = 0
        try:
            with YoutubeDL(opts) as ydl:
                # Extract info and download in one pass.
                result = ydl.extract_info(resolved, download=True)
                saved = self._count_entries(result)
        except DownloadError as exc:
            error(f"Download failed: {exc}")
            return 0

        if saved:
            success(f"Saved {saved} file(s) to {C.wrap(C.BOLD, self.config.output_dir)}/")
        else:
            warn("Nothing was downloaded.")
        return saved

    # ------------------------------------------------------------------ #
    def download_metadata_url(self, url: str, service: str = "Spotify") -> int:
        """Download music described by a Spotify or Deezer track/album/playlist.

        The streaming service only provides *metadata* (its full audio is
        DRM-protected). We read the song list from it, then locate and download
        each track from a real provider (SoundCloud/YouTube), tagging files with
        the correct title/artist/album.
        """
        info(f"Reading {service} metadata from {C.wrap(C.BOLD, url)}")
        try:
            if service == "Deezer":
                tracks = deezer_get_tracks(url)
            else:
                tracks = get_tracks(url)
        except (SpotifyError, DeezerError) as exc:
            error(f"Could not read {service} link: {exc}")
            return 0

        kind = "track" if len(tracks) == 1 else "collection"
        info(
            f"Found {C.wrap(C.BOLD, str(len(tracks)))} "
            f"{'track' if len(tracks) == 1 else 'tracks'} in this {kind}."
        )

        # Only albums/playlists get an artist subfolder; a lone track drops
        # straight into the output directory.
        group_by_artist = len(tracks) > 1

        total = 0
        for i, track in enumerate(tracks, 1):
            prefix = (
                ""
                if len(tracks) == 1
                else C.wrap(C.BOLD, f"[{i}/{len(tracks)}] ")
            )
            print(prefix + C.wrap(C.CYAN, track.search_query()))
            saved = self._download_search_query(
                track.search_query(),
                override_meta={
                    "title": track.title,
                    "artist": track.artists,
                    "album": track.album,
                },
                expected_duration=getattr(track, "duration", None),
                group_by_artist=group_by_artist,
            )
            total += saved

        if total:
            success(
                f"Saved {total}/{len(tracks)} track(s) to "
                f"{C.wrap(C.BOLD, self.config.output_dir)}/"
            )
        else:
            warn(f"No {service} tracks could be downloaded.")
        return total


    def _download_search_query(self, query: str, override_meta: dict | None = None,
                               expected_duration: int | None = None,
                               group_by_artist: bool = True) -> int:
        """Search providers for *query* and download the best audio match.

        Tries each provider in turn (SoundCloud, then YouTube by default, or a
        single one if ``--source`` was given). Within a provider it ranks the
        matches by how close their length is to *expected_duration* (so 30-second
        previews are skipped) and attempts them top-down, so a DRM-protected or
        blocked first result just falls through to the next candidate before
        moving on to another provider.

        ``override_meta`` lets the caller force the title/artist/album tags
        (used for Spotify/Deezer, where the true metadata differs from the
        provider's).

        ``group_by_artist`` decides the save path: ``True`` nests the file under
        an ``<artist>/`` folder (albums/playlists); ``False`` writes a single
        song straight into the output dir.
        """
        prefixes = self._provider_prefixes()
        opts = self._build_options(group_by_artist=group_by_artist)
        # Reset the per-song de-dup set so playlist tracks never collide via a
        # recycled id() of a previous track's info_dict.
        self._seen_pp_events.clear()
        # When we know the true metadata (Spotify/Deezer), name the file after
        # it instead of the provider's (often messy) title/uploader, and retag
        # the finished file so the tags match too (providers like SoundCloud
        # otherwise win over any fields we pre-set on the entry).
        if override_meta and override_meta.get("title"):
            clean_title = override_meta["title"]
            clean_artist = override_meta.get("artist") or "%(uploader)s"
            filename = f"{clean_title} [%(id)s].%(ext)s"
            if group_by_artist:
                opts["outtmpl"] = os.path.join(
                    self.config.output_dir, clean_artist, filename
                )
            else:
                # Single song -> flat, no artist folder.
                opts["outtmpl"] = os.path.join(self.config.output_dir, filename)

        for prefix in prefixes:
            # prefix looks like "scsearch1:"; rebuild it to fetch several results
            # so the ranker has a choice (the first hit is often a 30s preview).
            base = prefix.rstrip(":").rstrip("0123456789")
            resolved = f"{base}{SEARCH_RESULTS}:{query}"
            provider_name = base.replace("search", "") or prefix
            try:
                with YoutubeDL(opts) as ydl:
                    # extract_flat keeps this fast: we only need enough metadata
                    # (title/duration) to choose, not every format.
                    info_dict = ydl.extract_info(resolved, download=False)
                    if not info_dict:
                        continue
                    candidates = self._rank_entries(info_dict, expected_duration)
                    if not candidates:
                        continue

                    # Try each candidate until one actually downloads.
                    for best in candidates[: self._MAX_CANDIDATES]:
                        try:
                            result = ydl.process_ie_result(best, download=True)
                        except DownloadError as exc:
                            # This particular result failed (DRM, geo-block,
                            # bot-check...); note it and try the next candidate.
                            error(f"Download failed on {provider_name} for {query!r}: {exc}")
                            continue
                        saved = self._count_entries(result)
                        if saved:
                            self._apply_override_tags(result, override_meta)
                            return saved
            except DownloadError as exc:
                error(f"Search failed on {provider_name} for {query!r}: {exc}")
                continue

        warn(f"No downloadable result for: {query}")
        return 0

    # ------------------------------------------------------------------ #
    def _provider_prefixes(self) -> list[str]:
        """Return the ordered list of search prefixes to try.

        Respects ``--source``: ``"auto"`` tries every provider in turn, while a
        specific key (e.g. ``"youtube"``) tries only that provider.
        """
        prefixes: list[str] = []
        if _providers is not None:
            if self.config.source == "auto":
                prefixes = _providers.search_prefixes()
            else:
                for p in _providers.SEARCH_PROVIDERS:
                    if p.key == self.config.source and p.search_prefix:
                        prefixes = [p.search_prefix]
        # Always fall back to a plain YouTube search so we never end up with no
        # provider at all (e.g. if providers.py is missing).
        if not prefixes:
            prefixes = ["ytsearch1:"]
        return prefixes

    def _rank_entries(self, info_dict: dict, expected_duration: int | None) -> list:
        """Return search candidates ordered best-first.

        Duration is used mainly to *demote* obviously-too-short clips (e.g. 30s
        previews, sped-up/slowed edits are much longer or shorter than the
        original). Within the "looks like a full song" group we keep the search
        engine's original relevance order, because that order is generally the
        best match and reference durations from Spotify/Deezer are sometimes
        inaccurate.

        Returns an empty list when there is nothing usable.
        """
        if not isinstance(info_dict, dict):
            return []
        raw_entries = info_dict.get("entries")

        # No "entries" key -> this is a single direct result.
        if raw_entries is None:
            return [info_dict]

        # Drop empty/None placeholders yt-dlp may include.
        entries = [e for e in raw_entries if e]
        if not entries:
            return []

        if not expected_duration:
            return entries

        # Loose "full song" window around the reference length. Anything clearly
        # shorter (a preview) is demoted; anything clearly longer (a mega-mix or
        # hour-long upload) is also demoted. In-between we trust search order.
        lo, hi = expected_duration * 0.5, expected_duration * 2.0

        def score(entry):
            dur = entry.get("duration")
            if not dur:
                # No length info: keep, ranked right after confident matches.
                return (1, 0)
            if dur < 60:
                # Almost certainly a preview/clip; rank last.
                return (3, 0)
            if lo <= dur <= hi:
                # Plausible full-length match.
                return (0, 0)
            # Wrong length (very short or very long); demote but keep as backup.
            return (2, abs(dur - expected_duration))

        # ``sorted`` is stable, so entries with equal score keep their original
        # (search-relevance) order.
        return sorted(entries, key=score)


    # ------------------------------------------------------------------ #
    def _apply_override_tags(self, result: dict | None, override_meta: dict | None) -> None:
        """Rewrite an MP3's ID3 tags to the true metadata after download.

        Providers such as SoundCloud report their own title/uploader, which
        yt-dlp writes into the file. When we know the real metadata (from a
        Spotify/Deezer link) we overwrite title/artist/album here so the saved
        file carries correct tags. Non-fatal: any problem is silently ignored
        so it never breaks a successful download.
        """
        if not _MUTAGEN_AVAILABLE or not override_meta or not result:
            return

        # Work out the saved file path(s) from the yt-dlp result.
        entries = []
        if result.get("_type") == "playlist":
            entries = [e for e in result.get("entries", []) if e]
        else:
            entries = [result]

        wanted = {
            "title": override_meta.get("title"),
            "artist": override_meta.get("artist"),
            "album": override_meta.get("album"),
        }
        for entry in entries:
            path = entry.get("requested_downloads")
            # Newer yt-dlp records final files here.
            if path and isinstance(path, list):
                path = path[0].get("filepath")
            else:
                path = entry.get("filepath") or entry.get("_filename")
            if not path or not os.path.isfile(path):
                continue
            try:
                audio = ID3(path)
            except Exception:
                try:
                    audio = ID3()
                except Exception:
                    continue
            if wanted["title"]:
                audio.delall("TIT2")
                audio.add(mutagen.id3.TIT2(encoding=3, text=wanted["title"]))
            if wanted["artist"]:
                audio.delall("TPE1")
                audio.add(TPE1(encoding=3, text=wanted["artist"]))
            if wanted["album"]:
                audio.delall("TALB")
                audio.add(TALB(encoding=3, text=wanted["album"]))
            try:
                audio.save(path)
            except Exception as exc:  # pragma: no cover - defensive
                warn(f"Could not retag {os.path.basename(path)}: {exc}")

    @staticmethod
    def _count_entries(result: dict | None) -> int:
        """Count how many actual tracks came out of an extract_info result."""
        if not result:
            return 0
        if result.get("_type") == "playlist":
            return len([e for e in result.get("entries", []) if e])
        return 1

    # ------------------------------------------------------------------ #
    def download_batch(self, filepath: str) -> int:
        """Download every query/URL listed in a text file (one per line)."""
        if not os.path.isfile(filepath):
            error(f"Batch file not found: {filepath}")
            return 0

        with open(filepath, "r", encoding="utf-8") as fh:
            lines = [
                ln.strip()
                for ln in fh
                if ln.strip() and not ln.lstrip().startswith("#")
            ]

        info(f"Found {len(lines)} entr{'y' if len(lines) == 1 else 'ies'} in {filepath}")
        total = 0
        for i, line in enumerate(lines, 1):
            print(C.wrap(C.BOLD, f"\n[{i}/{len(lines)}] ") + line)
            total += self.download(line)
        return total



# --------------------------------------------------------------------------- #
# Command-line interface
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="music_downloader",
        description=(
            "Download music (audio or video) from URLs, search terms, or "
            "Spotify/Deezer links using yt-dlp."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s \"https://www.youtube.com/watch?v=dQw4w9WgXcQ\"\n"
            "  %(prog)s -s \"never gonna give you up\"\n"
            "  %(prog)s -s \"PLAYLIST_URL\" --playlist\n"
            "  %(prog)s --batch songs.txt\n"
            "  %(prog)s \"https://open.spotify.com/track/<id>\"\n"
            "  %(prog)s \"https://open.spotify.com/album/<id>\"\n"
            "  %(prog)s \"https://www.deezer.com/track/<id>\"\n"
            "  %(prog)s \"https://www.deezer.com/en/playlist/<id>\"\n"
            "  %(prog)s -s \"daft punk one more time\" --source youtube\n"
        ),
    )
    parser.add_argument(
        "target",
        nargs="?",
        help=(
            "A YouTube/other URL, a Spotify or Deezer track/album/playlist "
            "link, or (with -s) a search term describing the music you want."
        ),
    )
    parser.add_argument(
        "-s", "--search",
        action="store_true",
        help="Treat TARGET as a search query instead of a URL.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="downloads",
        help="Directory to save files in (default: %(default)s).",
    )
    parser.add_argument(
        "-f", "--format",
        dest="audio_format",
        default="mp3",
        choices=["mp3", "m4a", "opus", "wav", "flac", "vorbis"],
        help="Audio output format (default: %(default)s).",
    )
    parser.add_argument(
        "-q", "--quality",
        default="0",
        help="Audio quality 0 (best) - 10 (worst) for Vorbis/MP3 (default: %(default)s).",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Download an entire playlist instead of a single item.",
    )
    parser.add_argument(
        "--video",
        action="store_true",
        help="Download the full video (best <=1080p) instead of audio only.",
    )
    parser.add_argument(
        "--no-thumbnail",
        action="store_true",
        help="Do not embed album art / thumbnail into the file.",
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Do not write metadata tags (title, artist, ...).",
    )
    parser.add_argument(
        "--source",
        default="auto",
        metavar="PROVIDER",
        help=(
            "Where to fetch audio from: 'auto' (try each in turn), "
            "'soundcloud', or 'youtube' (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--cookies-from-browser",
        dest="cookies_from_browser",
        default=None,
        metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]",
        help=(
            "Load cookies from a browser so yt-dlp can use your logged-in "
            "session (e.g. 'chrome', 'firefox:Default', 'edge'). Helps get "
            "past YouTube's bot check. Not used for Deezer metadata."
        ),
    )
    parser.add_argument(
        "--batch",
        metavar="FILE",
        help="Read queries/URLs from FILE (one per line, '#' for comments).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress and informational output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.target and not args.batch:
        parser.error("provide a TARGET (URL or search term) or use --batch FILE")

    config = DownloadConfig(
        output_dir=args.output_dir,
        audio_format=args.audio_format,
        audio_quality=args.quality,
        allow_playlist=args.playlist,
        keep_video=args.video,
        embed_thumbnail=not args.no_thumbnail,
        add_metadata=not args.no_metadata,
        source=args.source,
        cookies_from_browser=args.cookies_from_browser,
        quiet=args.quiet,
    )

    downloader = MusicDownloader(config)

    total = 0
    if args.batch:
        total = downloader.download_batch(args.batch)
    else:
        total = downloader.download(args.target)

    if total == 0:
        return 1
    if not args.quiet:
        print()
        success(C.wrap(C.BOLD, f"All done - {total} file(s) downloaded."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

