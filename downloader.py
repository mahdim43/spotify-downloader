import asyncio
import html
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Callable

import requests
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, TRCK, TDRC, USLT, SYLT, ID3NoHeaderError
from spotify_scraper import SpotifyClient

logger = logging.getLogger(__name__)

SPOTIFY_URL_PATTERN = re.compile(
    r'https?://open\.spotify\.com/(track|playlist|album)/([a-zA-Z0-9]+)'
)

SPOTIFY_OEMBED_URL = "https://open.spotify.com/oembed"


def is_spotify_url(url: str) -> bool:
    return bool(SPOTIFY_URL_PATTERN.search(url))


def extract_spotify_id(url: str) -> tuple[str, str] | None:
    m = SPOTIFY_URL_PATTERN.search(url)
    if m:
        return m.group(1), m.group(2)
    return None


def get_spotify_metadata(url: str) -> dict | None:
    """Get track/album/playlist metadata via Spotify oEmbed (no auth required)."""
    try:
        resp = requests.get(SPOTIFY_OEMBED_URL, params={"url": url}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "title": html.unescape(data.get("title", "")),
                "description": html.unescape(data.get("description", "")),
                "thumbnail": data.get("thumbnail_url", ""),
                "provider_name": data.get("provider_name", ""),
            }
    except Exception as e:
        logger.warning(f"oEmbed failed: {e}")
    return None


def _upgrade_cover_url(url: str) -> str:
    """Return the cover URL as-is - Spotify CDN URLs are already optimal."""
    return url if url else ""


def get_spotify_track_info_from_url(url: str) -> dict | None:
    """Extract rich metadata by fetching the Spotify page and parsing meta tags."""
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if resp.status_code != 200:
            return None

        html_text = resp.text

        def meta(prop):
            m = re.search(rf'<meta property="{prop}" content="(.+?)"', html_text)
            return html.unescape(m.group(1).strip()) if m else ""

        def meta_name(prop):
            m = re.search(rf'<meta name="{prop}" content="(.+?)"', html_text)
            return html.unescape(m.group(1).strip()) if m else ""

        title = meta("og:title") or meta_name("title")
        description = meta("og:description") or meta_name("description")
        image = meta("og:image")

        if image:
            image = _upgrade_cover_url(image)

        artist = ""
        album = ""
        track_num = ""

        spotify_data = re.search(
            r'<script type="application/ld\+json">(.*?)</script>', html_text, re.DOTALL
        )
        if spotify_data:
            try:
                ld = json.loads(spotify_data.group(1))
                if "byArtist" in ld:
                    artist = html.unescape(ld["byArtist"].get("name", ""))
                elif "artist" in ld:
                    artist = html.unescape(ld["artist"].get("name", ""))
                if "name" in ld:
                    if not title or title == "":
                        title = html.unescape(ld["name"])
            except Exception:
                pass

        if not artist:
            desc_match = re.match(r'^(.+?)\s*·\s*', description)
            if desc_match:
                artist = desc_match.group(1).strip()

        if not artist:
            title_parts = title.split(" - ", 1)
            if len(title_parts) == 2:
                artist = title_parts[0].strip()
                title = title_parts[1].strip()

        album = ""
        if description:
            album_match = re.search(r'·\s*(.+?)\s*·\s*(?:Song|Single)', description)
            if album_match:
                album = html.unescape(album_match.group(1).strip())

        return {
            "title": title,
            "artist": artist,
            "album": album,
            "description": description,
            "image": image,
            "track_num": track_num,
        }
    except Exception as e:
        logger.warning(f"Page fetch failed: {e}")
    return None


def download_cover_image(url: str) -> bytes | None:
    """Download album art from URL."""
    if not url:
        logger.warning("No cover URL provided")
        return None
    try:
        logger.info(f"Downloading cover art from: {url}")
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            data = resp.content
            if len(data) > 500:
                logger.info(f"Cover art downloaded: {len(data)} bytes")
                return data
            else:
                logger.warning(f"Cover art too small: {len(data)} bytes")
        else:
            logger.warning(f"Cover art HTTP {resp.status_code} from {url}")
    except Exception as e:
        logger.warning(f"Cover download failed: {e}")
    return None


LRCLIB_API = "https://lrclib.net/api"
LYRICS_OVH_API = "https://api.lyrics.ovh/v1"
LYRICS_FANDOM_API = "https://lyrics.fandom.com/api.php"


def fetch_lyrics(artist: str, title: str, duration: int = 0) -> dict | None:
    """Fetch lyrics from multiple sources: lrclib.net, lyrics.ovh, lyrics.fandom.com.
    Returns dict with 'plain' and/or 'synced' (LRC) lyrics.
    """
    try:
        params = {"artist_name": artist, "track_name": title}
        if duration > 0:
            params["duration"] = duration
        resp = requests.get(f"{LRCLIB_API}/get", params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            result = {}
            if data.get("plainLyrics"):
                result["plain"] = data["plainLyrics"]
            if data.get("syncedLyrics"):
                result["synced"] = data["syncedLyrics"]
            if result:
                logger.info(f"Lyrics found (lrclib) for: {artist} - {title}")
                return result

        resp2 = requests.get(f"{LRCLIB_API}/search", params=params, timeout=5)
        if resp2.status_code == 200:
            results = resp2.json()
            if results:
                data = results[0]
                result = {}
                if data.get("plainLyrics"):
                    result["plain"] = data["plainLyrics"]
                if data.get("syncedLyrics"):
                    result["synced"] = data["syncedLyrics"]
                if result:
                    logger.info(f"Lyrics found (lrclib search) for: {artist} - {title}")
                    return result
    except Exception as e:
        logger.warning(f"lrclib lyrics fetch failed: {e}")

    try:
        safe_artist = requests.utils.quote(artist)
        safe_title = requests.utils.quote(title)
        resp = requests.get(f"{LYRICS_OVH_API}/{safe_artist}/{safe_title}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            lyrics_text = data.get("lyrics", "")
            if lyrics_text:
                logger.info(f"Lyrics found (lyrics.ovh) for: {artist} - {title}")
                return {"plain": lyrics_text}
    except Exception as e:
        logger.warning(f"lyrics.ovh fetch failed: {e}")

    try:
        params = {
            "action": "query",
            "titles": f"{title} by {artist}",
            "prop": "revisions",
            "rvprop": "content",
            "format": "json",
        }
        resp = requests.get(LYRICS_FANDOM_API, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            for page_id, page_data in pages.items():
                if page_id == "-1":
                    continue
                revisions = page_data.get("revisions", [])
                if revisions:
                    content = revisions[0].get("*", "")
                    lyrics_lines = []
                    in_lyrics = False
                    for line in content.split("\n"):
                        if "<lyrics>" in line.lower():
                            in_lyrics = True
                            continue
                        if "</lyrics>" in line.lower():
                            in_lyrics = False
                            continue
                        if in_lyrics and line.strip() and not line.startswith("[") and not line.startswith("{"):
                            lyrics_lines.append(line.strip())
                    if lyrics_lines:
                        lyrics_text = "\n".join(lyrics_lines)
                        logger.info(f"Lyrics found (fandom) for: {artist} - {title}")
                        return {"plain": lyrics_text}
    except Exception as e:
        logger.warning(f"lyrics.fandom fetch failed: {e}")

    logger.info(f"No lyrics found for: {artist} - {title}")
    return None


def embed_metadata(file_path: Path, meta: dict, cover_data: bytes | None, lyrics: dict | None = None):
    """Embed ID3v2.3 metadata and album art into an MP3 file.
    Windows Explorer/Media Player require ID3v2.3 for cover art display.
    """
    try:
        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()

        if meta.get("title"):
            tags.add(TIT2(encoding=3, text=[meta["title"]]))
        if meta.get("artist"):
            tags.add(TPE1(encoding=3, text=[meta["artist"]]))
        if meta.get("album"):
            tags.add(TALB(encoding=3, text=[meta["album"]]))
        if meta.get("track_num"):
            tags.add(TRCK(encoding=3, text=[meta["track_num"]]))

        if cover_data:
            tags.delall("APIC")
            tags.add(APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="",
                data=cover_data,
            ))

        if lyrics:
            if lyrics.get("plain"):
                tags.delall("USLT")
                tags.add(USLT(
                    encoding=3,
                    lang="eng",
                    desc="",
                    text=lyrics["plain"],
                ))
            if lyrics.get("synced"):
                tags.delall("SYLT")
                synced_lines = []
                for line in lyrics["synced"].split("\n"):
                    m = re.match(r'\[(\d+):(\d+)\.(\d+)\](.*)', line)
                    if m:
                        mins = int(m.group(1))
                        secs = int(m.group(2))
                        cs = int(m.group(3))
                        text = m.group(4).strip()
                        if text:
                            timestamp_ms = (mins * 60 + secs) * 1000 + cs * 10
                            synced_lines.append((text, timestamp_ms))
                if synced_lines:
                    tags.add(SYLT(
                        encoding=3,
                        lang="eng",
                        desc="",
                        type=1,
                        format=2,
                        text=synced_lines,
                    ))

        tags.save(file_path, v2_version=3)
        safe_name = file_path.name.encode('ascii', 'replace').decode('ascii')
        logger.info(f"Embedded metadata into: {safe_name} (ID3v2.3)")
    except Exception as e:
        safe_name = file_path.name.encode("ascii", "replace").decode("ascii") if file_path else "unknown"
        logger.warning(f"Failed to embed metadata: {safe_name} - {str(e).encode(errors='replace').decode()}")


def _safe_log(text: str) -> str:
    """Encode text as ASCII-safe for Windows console logging."""
    return text.encode("ascii", "replace").decode("ascii")


def _normalize_for_match(text: str) -> str:
    """Normalize for fuzzy matching: lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _find_existing_track(track_name: str, track_artist: str, folder: Path) -> Path | None:
    """Find a matching mp3 file for a track in a folder.

    Checks ID3 tags first (exact normalized match), then falls back to filename matching.
    Both artist AND name must match — not just one or the other.
    Returns the Path of the matching file, or None.
    """
    logger.info(f"Skip check: looking for '{_safe_log(track_artist)} - {_safe_log(track_name)}' in {folder}")
    if not folder.exists():
        logger.info(f"Skip check: folder does not exist: {folder}")
        return None
    mp3_count = sum(1 for f in folder.iterdir() if f.suffix.lower() == ".mp3" and f.is_file())
    logger.info(f"Skip check: {mp3_count} mp3 files in {folder}")
    track_norm = _normalize_for_match(f"{track_artist} {track_name}")
    name_norm = _normalize_for_match(track_name)
    artist_norm = _normalize_for_match(track_artist)
    stop_words = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or", "is", "feat", "ft"}

    name_keywords = {w for w in name_norm.split() if w not in stop_words}
    artist_keywords = {w for w in artist_norm.split() if w not in stop_words}

    def _parse_artist_title(stem_norm: str):
        base = re.sub(r'\s*[\(\[].*?[\)\]]', '', stem_norm).strip()
        if " - " in base:
            parts = base.split(" - ", 1)
            return set(parts[1].split()), set(parts[0].split())
        return None, set(base.split())

    def _title_matches(file_title_words: set) -> bool:
        if not name_keywords:
            return True
        name_str = " ".join(sorted(name_keywords))
        title_str = " ".join(sorted(file_title_words))
        if name_str == title_str:
            return True
        if len(name_keywords) <= 3:
            return False
        score = len(name_keywords & file_title_words) / len(name_keywords)
        return score >= 0.8

    for f in folder.iterdir():
        if f.suffix.lower() != ".mp3" or not f.is_file():
            continue

        try:
            tags = ID3(f)
            t = str(tags.get("TIT2", ""))
            a = str(tags.get("TPE1", ""))
            if t and a and _normalize_for_match(f"{a} {t}") == track_norm:
                logger.info(f"Skip check: ID3 match: {_safe_log(f.name)} for {_safe_log(track_artist)} - {_safe_log(track_name)}")
                return f
        except Exception:
            pass

        stem_norm = _normalize_for_match(f.stem)
        file_artist, file_title = _parse_artist_title(stem_norm)

        if file_artist is not None:
            if artist_keywords and artist_keywords == file_artist:
                if _title_matches(file_title):
                    logger.info(f"Skip check: filename match: {_safe_log(f.name)} for {_safe_log(track_artist)} - {_safe_log(track_name)}")
                    return f
            elif artist_keywords and file_artist and artist_keywords.issubset(file_artist):
                if _title_matches(file_title):
                    logger.info(f"Skip check: filename match (subset): {_safe_log(f.name)} for {_safe_log(track_artist)} - {_safe_log(track_name)}")
                    return f
        else:
            if artist_keywords and artist_keywords == file_title and _title_matches(file_title):
                logger.info(f"Skip check: filename match (no artist): {_safe_log(f.name)} for {_safe_log(track_artist)} - {_safe_log(track_name)}")
                return f

    logger.info(f"Skip check: no match for '{_safe_log(track_artist)} - {_safe_log(track_name)}' in {folder}")
    return None


def _sanitize_filename(name: str) -> str:
    """Remove characters unsafe for filenames on Windows."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')


def _clean_yt_filename(name: str) -> str:
    """Strip YouTube suffixes and unusual characters from downloaded filenames."""
    cleaned = re.sub(r'\s*\(Official\s*Audio\)', '', name, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\(Official\s*Music\s*Video\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\(Audio\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\(Lyric\s*Video\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\(Lyrics\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\(Official\s*Lyric\s*Video\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\[Official\s*Audio\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\[Official\s*Music\s*Video\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\[Audio\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\[Lyric\s*Video\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\[Lyrics\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\(Visualizer\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\[Visualizer\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[⧸⁄]', ' - ', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned.strip()


def _build_search_query(title: str, artist: str) -> str:
    """Build accurate YouTube search query from full title and artist, preferring audio-only."""
    parts = []
    if artist:
        clean_artist = re.sub(r'\s*,\s*feat\.?.*', '', artist, flags=re.IGNORECASE).strip()
        clean_artist = re.sub(r'\s*ft\.?.*', '', clean_artist, flags=re.IGNORECASE).strip()
        parts.append(clean_artist)
    if title:
        clean_title = re.sub(r'\s*-\s*Spotify.*', '', title).strip()
        clean_title = re.sub(r'[,!;:?]', '', clean_title).strip()
        clean_title = re.sub(r'[^\x00-\x7F]+', '', clean_title).strip()
        clean_title = re.sub(r'\(\s*\)', '', clean_title).strip()
        clean_title = re.sub(r'\s{2,}', ' ', clean_title).strip()
        parts.append(clean_title)

    query = " ".join(parts) + " official audio"
    return query


def _parse_title_artist(raw_title: str) -> tuple[str, str]:
    """Parse 'Artist - Title' format, return (title, artist)."""
    raw_title = re.sub(r'\s*-\s*Spotify.*', '', raw_title).strip()
    raw_title = re.sub(r'\s*\(Official.*?\)', '', raw_title, flags=re.IGNORECASE).strip()
    raw_title = re.sub(r'\s*\(Audio.*?\)', '', raw_title, flags=re.IGNORECASE).strip()
    raw_title = re.sub(r'\s*\(Lyric.*?\)', '', raw_title, flags=re.IGNORECASE).strip()
    raw_title = re.sub(r'\s*\[Official.*?\]', '', raw_title, flags=re.IGNORECASE).strip()
    raw_title = re.sub(r'\s*\[Audio.*?\]', '', raw_title, flags=re.IGNORECASE).strip()
    raw_title = re.sub(r'\s*\[Lyric.*?\]', '', raw_title, flags=re.IGNORECASE).strip()

    parts = raw_title.split(" - ", 1)
    if len(parts) == 2:
        return parts[1].strip(), parts[0].strip()
    return raw_title.strip(), ""


def search_spotify(query: str, limit: int = 10) -> list[dict]:
    """Search Spotify for tracks by name/artist. Returns list of track dicts."""
    try:
        client = _get_spotify_client()
        results = client.search(query, types=["track"], limit=limit)
        tracks = []
        for t in results.tracks:
            artist_names = ", ".join(a.name for a in t.artists) if t.artists else "Unknown Artist"
            album_name = t.album.name if t.album else ""
            cover_url = t.images[0].url if t.images and t.images[0].url else ""
            duration_sec = t.duration_ms // 1000 if t.duration_ms else 0
            spotify_url = t.share_url or f"https://open.spotify.com/track/{t.id}"
            tracks.append({
                "title": html.unescape(t.name) if t.name else "",
                "artist": html.unescape(artist_names),
                "album": html.unescape(album_name),
                "duration": f"{duration_sec // 60}:{duration_sec % 60:02d}",
                "cover": cover_url,
                "url": spotify_url,
                "explicit": t.explicit,
            })
        logger.info(f"Spotify search for '{query}': {len(tracks)} results")
        return tracks
    except Exception as e:
        logger.warning(f"Spotify search failed for '{query}': {e}")
        return []


async def download_spotify(
    url: str,
    output_dir: Path,
    bitrate: str = "320",
    embed_lyrics: bool = False,
    stop_event: asyncio.Event | None = None,
    start_index: int = 0,
    parallel: int = 1,
    on_progress: Callable[[int, int, str], None] | None = None,
    on_file: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> dict:
    """Download Spotify track using oEmbed metadata + yt-dlp YouTube search.
    Returns dict with 'files' (success) and 'failed' (list of failed track dicts).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    is_playlist_url = bool(re.search(r'/(playlist|album)/', url))
    is_album = bool(re.search(r'/album/', url))
    metadata = get_spotify_metadata(url)
    page_info = get_spotify_track_info_from_url(url)

    if is_playlist_url:
        return await _download_playlist(
            url, output_dir, bitrate, metadata, page_info,
            embed_lyrics, stop_event, start_index, on_progress, on_file, on_error,
            is_album=is_album, parallel=parallel
        )
    else:
        return await _download_single(
            url, output_dir, bitrate, metadata, page_info,
            embed_lyrics, on_progress, on_file, on_error
        )


async def _download_single(
    url: str,
    output_dir: Path,
    bitrate: str,
    metadata: dict | None,
    page_info: dict | None,
    embed_lyrics: bool,
    on_progress: Callable,
    on_file: Callable,
    on_error: Callable,
) -> dict:
    """Download a single Spotify track with full metadata."""
    raw_title = ""
    if metadata:
        raw_title = metadata.get("title", "")
    if not raw_title and page_info:
        raw_title = page_info.get("title", "")

    if not raw_title:
        raw_title = "Unknown Track"

    artist = ""
    if page_info:
        artist = page_info.get("artist", "")
    if not artist and metadata:
        desc = metadata.get("description", "")
        desc_match = re.match(r'^(.+?)\s*·\s*', desc)
        if desc_match:
            artist = desc_match.group(1).strip()

    clean_title, parsed_artist = _parse_title_artist(raw_title)
    if not artist:
        artist = parsed_artist

    search_query = _build_search_query(clean_title, artist)
    logger.info(f"Searching YouTube for: ytsearch:{search_query}")

    if on_progress:
        on_progress(0, 1, f"Searching: {search_query}")

    output_template = str(output_dir / "%(title)s.%(ext)s")

    args = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", f"{bitrate}k",
        "-o", output_template,
        "--no-warnings",
        "--no-check-certificates",
        "--match-filter", "duration<600",
        "--no-update",
        "--extractor-args", "youtube:player_client=android_vr",
        f"ytsearch:{search_query}",
    ]

    if on_progress:
        on_progress(0, 1, f"Downloading: {search_query}")

    before_download = {f.name for f in output_dir.iterdir() if f.suffix == ".mp3" and f.is_file()}

    result = await asyncio.to_thread(
        subprocess.run,
        args,
        capture_output=True,
        timeout=300,
    )

    if result.returncode != 0:
        error_msg = result.stderr.decode(errors="replace")[:500]
        logger.error(f"yt-dlp failed: {error_msg}")
        if on_error:
            on_error(f"Download failed: {error_msg}")
        return {"files": [], "failed": [{"title": clean_title, "artist": artist, "error": error_msg}]}

    downloaded_files = []
    failed_tracks = []

    after_download = {f.name for f in output_dir.iterdir() if f.suffix == ".mp3" and f.is_file()}
    new_files = after_download - before_download

    for fname in new_files:
        f = output_dir / fname
        safe_artist = _sanitize_filename(artist) if artist else "Unknown Artist"
        safe_title = _sanitize_filename(clean_title) if clean_title else _clean_yt_filename(f.stem)
        new_name = f"{safe_title} - {safe_artist}.mp3"
        if new_name != f.name:
            new_path = f.parent / new_name
            if not new_path.exists():
                f.rename(new_path)
                f = new_path
            else:
                f.unlink()
                f = new_path

        downloaded_files.append(f.name)

        cover_data = None
        thumb_url = ""
        if page_info:
            thumb_url = page_info.get("image", "")
        if not thumb_url and metadata:
            thumb_url = metadata.get("thumbnail", "")

        if thumb_url:
            cover_data = await asyncio.to_thread(download_cover_image, thumb_url)

        track_meta = {
            "title": clean_title,
            "artist": artist or "Unknown Artist",
            "album": "",
            "track_num": "",
        }
        if page_info:
            if page_info.get("album"):
                track_meta["album"] = page_info["album"]

        lyrics = None
        if embed_lyrics and artist and clean_title:
            lyrics = await asyncio.to_thread(fetch_lyrics, artist, clean_title)

        await asyncio.to_thread(embed_metadata, f, track_meta, cover_data, lyrics)

        if on_file:
            on_file(f.name)

    if on_progress:
        on_progress(1, 1, "Done")

    logger.info(f"Downloaded: {downloaded_files}")
    return {"files": downloaded_files, "failed": failed_tracks}


async def retry_single_track(
    output_dir: Path,
    bitrate: str,
    track_name: str,
    track_artist: str,
    track_num: int,
    is_album: bool,
    embed_lyrics: bool,
    on_progress: Callable,
    on_file: Callable,
    on_error: Callable,
) -> dict:
    """Retry downloading a single failed track, with correct numbering for albums."""
    logger.info(f"Retrying track {track_num}: {track_name} - {track_artist}")

    if on_progress:
        on_progress(0, 1, f"Retrying: {track_artist} - {track_name}" if track_artist else f"Retrying: {track_name}")

    search_query = _build_search_query(track_name, track_artist)
    logger.info(f"Searching YouTube for: ytsearch:{search_query}")

    output_template = str(output_dir / "%(title)s.%(ext)s")

    args = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", f"{bitrate}k",
        "-o", output_template,
        "--no-warnings",
        "--no-check-certificates",
        "--match-filter", "duration<600",
        "--no-update",
        "--extractor-args", "youtube:player_client=android_vr",
        f"ytsearch:{search_query}",
    ]

    try:
        before_download = {f.name for f in output_dir.iterdir() if f.suffix == ".mp3" and f.is_file()}

        result = await asyncio.to_thread(
            subprocess.run,
            args,
            capture_output=True,
            timeout=300,
        )

        if result.returncode != 0:
            error_msg = (result.stderr or b"").decode(errors="replace")[:300]
            logger.warning(f"Retry failed for track {track_num}: {_safe_log(track_name)} | {error_msg}")
            if on_error:
                on_error(f"Retry failed: {track_name}")
            return {"files": [], "failed": [{"title": track_name, "artist": track_artist, "error": "yt-dlp failed", "track_num": track_num}]}

        after_download = {f.name for f in output_dir.iterdir() if f.suffix == ".mp3" and f.is_file()}
        new_files = after_download - before_download
        new_mp3s = [output_dir / f for f in new_files]
        if not new_mp3s:
            logger.warning(f"Retry returned 0 but no file created for: {_safe_log(track_name)}")
            if on_error:
                on_error(f"No results: {track_name}")
            return {"files": [], "failed": [{"title": track_name, "artist": track_artist, "error": "no results found", "track_num": track_num}]}

        track_cover_data = None

        downloaded_files = []
        for f in new_mp3s:
            safe_artist = _sanitize_filename(track_artist) if track_artist else "Unknown Artist"
            safe_title = _sanitize_filename(track_name) if track_name else _clean_yt_filename(f.stem)
            if is_album:
                new_name = f"{track_num:02d}.{safe_title} - {safe_artist}.mp3"
            else:
                new_name = f"{safe_title} - {safe_artist}.mp3"
            if new_name != f.name:
                new_path = f.parent / new_name
                if not new_path.exists():
                    f.rename(new_path)
                    f = new_path
                else:
                    f.unlink()
                    f = new_path

            downloaded_files.append(f.name)

            track_meta = {
                "title": track_name,
                "artist": track_artist or "Unknown Artist",
                "album": "",
                "track_num": str(track_num) if is_album else "",
            }

            await asyncio.to_thread(embed_metadata, f, track_meta, track_cover_data, None)

            if on_file:
                on_file(f.name)
            break

        if on_progress:
            on_progress(1, 1, "Done")

        logger.info(f"Retry succeeded: {downloaded_files}")
        return {"files": downloaded_files, "failed": []}

    except Exception as e:
        logger.error(f"Error retrying track {track_num}: {str(e).encode(errors='replace').decode()}")
        if on_error:
            on_error(f"Error: {track_name} - {e}")
        return {"files": [], "failed": [{"title": track_name, "artist": track_artist, "error": str(e), "track_num": track_num}]}


async def _download_playlist(
    url: str,
    output_dir: Path,
    bitrate: str,
    metadata: dict | None,
    page_info: dict | None,
    embed_lyrics: bool,
    stop_event: asyncio.Event | None,
    start_index: int,
    on_progress: Callable,
    on_file: Callable,
    on_error: Callable,
    is_album: bool = False,
    parallel: int = 1,
) -> dict:
    """Download a Spotify playlist/album by searching each track on YouTube."""
    album_title = ""
    if metadata:
        album_title = metadata.get("title", "") or metadata.get("description", "")
    if not album_title and page_info:
        album_title = page_info.get("title", "")

    album_title = re.sub(r'\s*[\(\[].*?[\)\]]', '', album_title).strip()
    album_title = re.sub(r'\s*-\s*Spotify.*', '', album_title).strip()
    album_title = _sanitize_filename(album_title)

    playlist_dir = output_dir
    playlist_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Download folder: {playlist_dir}")
    logger.info(f"Output dir: {output_dir}, album_title: {album_title!r}, parallel: {parallel}")

    existing_count = sum(1 for _ in output_dir.rglob("*.mp3"))
    logger.info(f"Existing mp3 files in output_dir (recursive): {existing_count}")

    logger.info(f"Fetching playlist tracks from: {url}")

    html_tracks = await _fetch_all_playlist_tracks(url)
    if not html_tracks:
        html_tracks = [album_title] if album_title else []

    total = len(html_tracks)
    logger.info(f"Found {total} tracks in playlist")

    if total == 0:
        if on_error:
            on_error("No tracks found in playlist")
        return {"files": [], "skipped": [], "failed": []}

    import threading
    import tempfile
    import shutil
    lock = threading.Lock()
    downloaded_files = []
    skipped_files = []
    failed_tracks = []
    completed_count = [0]

    async def download_one(i: int, track_info):
        if stop_event and stop_event.is_set():
            return

        if isinstance(track_info, dict):
            track_name = track_info.get("title", "")
            track_artist = track_info.get("artist", "")
            track_cover = track_info.get("cover", "")
        else:
            track_name = str(track_info)
            track_artist = ""
            track_cover = ""

        logger.info(f"Downloading [{i}/{total}]: {_safe_log(track_name)} - {_safe_log(track_artist)}")
        if on_progress:
            on_progress(i - 1, total, f"{track_artist} - {track_name}" if track_artist else track_name)

        existing = _find_existing_track(track_name, track_artist, playlist_dir)
        if not existing and output_dir != playlist_dir:
            existing = _find_existing_track(track_name, track_artist, output_dir)
        if not existing:
            for sub in output_dir.iterdir():
                if sub.is_dir() and sub != playlist_dir:
                    existing = _find_existing_track(track_name, track_artist, sub)
                    if existing:
                        break
        if existing:
            logger.info(f"Skipping (already exists): {_safe_log(track_name)} - {_safe_log(track_artist)}")
            with lock:
                skipped_files.append(existing.name)
            if on_file:
                on_file("(exists) " + existing.name)
            if on_progress:
                on_progress(i, total, f"Skipped (exists): {track_artist} - {track_name}" if track_artist else f"Skipped (exists): {track_name}")
            return

        logger.info(f"Not found, will download: {_safe_log(track_name)} - {_safe_log(track_artist)}")

        search_query = _build_search_query(track_name, track_artist)
        logger.info(f"Searching YouTube for: ytsearch:{_safe_log(search_query)}")

        tmp_dir = Path(tempfile.mkdtemp(prefix=f"spotdown_{i}_"))
        try:
            output_template = str(tmp_dir / "%(title)s.%(ext)s")

            args = [
                "yt-dlp",
                "--no-playlist",
                "-f", "bestaudio/best",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", f"{bitrate}k",
                "-o", output_template,
                "--no-warnings",
                "--no-check-certificates",
                "--match-filter", "duration<600",
                "--no-update",
                "--extractor-args", "youtube:player_client=android_vr",
                f"ytsearch:{search_query}",
            ]

            result = await asyncio.to_thread(
                subprocess.run,
                args,
                capture_output=True,
                timeout=300,
            )

            if result.returncode != 0:
                stderr_text = (result.stderr or b"").decode(errors="replace")
                logger.warning(f"Failed track {i}/{total}: {_safe_log(track_name)} | stderr: {stderr_text[:300]}")
                with lock:
                    failed_tracks.append({"title": track_name, "artist": track_artist, "error": "yt-dlp failed", "track_num": i})
                if on_error:
                    on_error(f"Failed: {track_name}")
                return

            mp3_files = [f for f in tmp_dir.iterdir() if f.suffix == ".mp3" and f.is_file()]
            if not mp3_files:
                stderr_text = (result.stderr or b"").decode(errors="replace")
                if "0 results" in stderr_text:
                    logger.warning(f"No YouTube results for: {_safe_log(track_name)} - {_safe_log(track_artist)}")
                else:
                    logger.warning(f"yt-dlp returned 0 but no file created for: {_safe_log(track_name)} - {_safe_log(track_artist)}")
                with lock:
                    failed_tracks.append({"title": track_name, "artist": track_artist, "error": "no results found", "track_num": i})
                if on_error:
                    on_error(f"No results: {track_name}")
                return

            src_file = mp3_files[0]

            safe_artist = _sanitize_filename(track_artist) if track_artist else "Unknown Artist"
            safe_title = _sanitize_filename(track_name) if track_name else _clean_yt_filename(src_file.stem)
            if is_album:
                final_name = f"{i:02d}.{safe_title} - {safe_artist}.mp3"
            else:
                final_name = f"{safe_title} - {safe_artist}.mp3"
            final_path = playlist_dir / final_name

            track_cover_data = None
            if track_cover:
                track_cover_data = await asyncio.to_thread(download_cover_image, track_cover)

            lyrics = None
            if embed_lyrics and track_artist and track_name:
                lyrics = await asyncio.to_thread(fetch_lyrics, track_artist, track_name)

            track_meta = {
                "title": track_name,
                "artist": track_artist or "Unknown Artist",
                "album": album_title,
                "track_num": str(i),
            }

            await asyncio.to_thread(embed_metadata, src_file, track_meta, track_cover_data, lyrics)

            with lock:
                if final_path.exists():
                    final_path.unlink()
                shutil.move(str(src_file), str(final_path))
                downloaded_files.append(final_name)

            if on_file:
                on_file(final_name)

        except Exception as e:
            safe_err = str(e).encode(errors="replace").decode()
            logger.error(f"Error downloading track {i}: {safe_err}")
            with lock:
                failed_tracks.append({"title": track_name, "artist": track_artist, "error": safe_err, "track_num": i})
            if on_error:
                on_error(f"Error: {track_name}")
        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    if parallel <= 1:
        for i, track_info in enumerate(html_tracks, 1):
            if stop_event and stop_event.is_set():
                break
            if i <= start_index:
                continue
            await download_one(i, track_info)
            with lock:
                completed_count[0] += 1
                if on_progress:
                    on_progress(completed_count[0], total, f"{completed_count[0]}/{total} completed")
    else:
        queue = asyncio.Queue()
        for i, track_info in enumerate(html_tracks, 1):
            if i <= start_index:
                continue
            queue.put_nowait((i, track_info))

        async def worker():
            while True:
                if stop_event and stop_event.is_set():
                    break
                try:
                    i, track_info = await asyncio.wait_for(queue.get(), timeout=5)
                except (asyncio.TimeoutError, asyncio.QueueEmpty):
                    break
                try:
                    await asyncio.wait_for(download_one(i, track_info), timeout=600)
                except asyncio.TimeoutError:
                    logger.error(f"Track {i} timed out after 600s, skipping")
                    with lock:
                        failed_tracks.append({"title": track_info.get("title", "") if isinstance(track_info, dict) else str(track_info), "artist": track_info.get("artist", "") if isinstance(track_info, dict) else "", "error": "download timed out", "track_num": i})
                    if on_error:
                        on_error(f"Timeout: track {i}")
                except Exception as e:
                    logger.error(f"Worker error on track {i}: {str(e).encode(errors='replace').decode()}")
                    with lock:
                        failed_tracks.append({"title": track_info.get("title", "") if isinstance(track_info, dict) else str(track_info), "artist": track_info.get("artist", "") if isinstance(track_info, dict) else "", "error": str(e), "track_num": i})
                    if on_error:
                        on_error(f"Error: track {i} - {e}")
                finally:
                    with lock:
                        completed_count[0] += 1
                        if on_progress:
                            on_progress(completed_count[0], total, f"{completed_count[0]}/{total} completed")
                    queue.task_done()

        num_workers = min(parallel, queue.qsize())
        workers = [asyncio.create_task(worker()) for _ in range(num_workers)]
        await asyncio.gather(*workers, return_exceptions=True)

    if on_progress:
        on_progress(total, total, "Done")

    return {"files": downloaded_files, "skipped": skipped_files, "failed": failed_tracks}


def _extract_track_ids(html_text: str) -> list[str]:
    """Extract unique Spotify track IDs from the raw HTML + initialState JSON."""
    ids = re.findall(r'spotify:track:([a-zA-Z0-9]+)', html_text)
    json_match = re.search(r'<script[^>]+id="initialState"[^>]*>(.*?)</script>', html_text, re.DOTALL)
    if json_match:
        raw = json_match.group(1).strip()
        padding = 4 - len(raw) % 4
        if padding != 4:
            raw += '=' * padding
        try:
            data = json.loads(__import__("base64").b64decode(raw).decode('utf-8'))
            json_str = json.dumps(data)
            json_ids = re.findall(r'spotify:track:([a-zA-Z0-9]+)', json_str)
            ids.extend(json_ids)
        except Exception:
            pass
    return list(dict.fromkeys(ids))


_spotify_client: SpotifyClient | None = None


def _get_spotify_client() -> SpotifyClient:
    global _spotify_client
    if _spotify_client is None:
        _spotify_client = SpotifyClient()
    return _spotify_client


async def _fetch_all_playlist_tracks(url: str) -> list[dict]:
    """Fetch ALL tracks from a Spotify playlist/album."""
    info = extract_spotify_id(url)
    if not info:
        return []

    content_type, content_id = info
    client = _get_spotify_client()

    try:
        if content_type == "album":
            album = await asyncio.to_thread(client.get_album, content_id)
            album_cover = _upgrade_cover_url(album.images[0].url) if album.images and album.images[0].url else ""
            tracks = []
            for t in album.tracks:
                cover = _upgrade_cover_url(t.images[0].url) if t.images and t.images[0].url else album_cover
                tracks.append({
                    "title": html.unescape(t.name) if t.name else "",
                    "artist": html.unescape(", ".join(a.name for a in t.artists)) if t.artists else "",
                    "cover": cover,
                })
            logger.info(f"Found {len(tracks)} tracks in album")
            return tracks
        elif content_type == "playlist":
            playlist = await asyncio.to_thread(client.get_playlist, content_id, max_tracks=None)
            playlist_cover = _upgrade_cover_url(playlist.images[0].url) if playlist.images and playlist.images[0].url else ""
            tracks = []
            for pt in playlist.tracks:
                t = pt.track
                cover = _upgrade_cover_url(t.images[0].url) if t.images and t.images[0].url else playlist_cover
                tracks.append({
                    "title": html.unescape(t.name) if t.name else "",
                    "artist": html.unescape(", ".join(a.name for a in t.artists)) if t.artists else "",
                    "cover": cover,
                })
            logger.info(f"Found {len(tracks)} tracks in playlist (total: {playlist.total_tracks})")
            return tracks
    except Exception as e:
        logger.warning(f"spotify_scraper failed for {content_type}/{content_id}: {e}")

    return []


