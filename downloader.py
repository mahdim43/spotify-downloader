import asyncio
import html
import logging
import re
import subprocess
import json
from pathlib import Path
from typing import Callable

import requests
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, TRCK, TDRC, USLT, SYLT, ID3NoHeaderError

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


def fetch_lyrics(artist: str, title: str, duration: int = 0) -> dict | None:
    """Fetch lyrics from lrclib.net (synced + plain) with lyrics.ovh fallback (plain only).
    Returns dict with 'plain' and/or 'synced' (LRC) lyrics.
    """
    try:
        params = {"artist_name": artist, "track_name": title}
        if duration > 0:
            params["duration"] = duration
        resp = requests.get(f"{LRCLIB_API}/get", params=params, timeout=30)
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

        resp2 = requests.get(f"{LRCLIB_API}/search", params=params, timeout=30)
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
        resp = requests.get(f"{LYRICS_OVH_API}/{safe_artist}/{safe_title}", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            lyrics_text = data.get("lyrics", "")
            if lyrics_text:
                logger.info(f"Lyrics found (lyrics.ovh) for: {artist} - {title}")
                return {"plain": lyrics_text}
    except Exception as e:
        logger.warning(f"lyrics.ovh fetch failed: {e}")

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
        logger.info(f"Embedded metadata into: {file_path.name} (ID3v2.3)")
    except Exception as e:
        logger.warning(f"Failed to embed metadata: {e}")


def _build_search_query(title: str, artist: str) -> str:
    """Build accurate YouTube search query from full title and artist, preferring audio-only."""
    parts = []
    if artist:
        clean_artist = re.sub(r'\s*,\s*feat\.?.*', '', artist, flags=re.IGNORECASE).strip()
        clean_artist = re.sub(r'\s*ft\.?.*', '', clean_artist, flags=re.IGNORECASE).strip()
        parts.append(clean_artist)
    if title:
        clean_title = re.sub(r'\s*-\s*Spotify.*', '', title).strip()
        clean_title = re.sub(r'\s*\(feat\.?.*?\)', '', clean_title, flags=re.IGNORECASE).strip()
        clean_title = re.sub(r'\s*\(ft\.?.*?\)', '', clean_title, flags=re.IGNORECASE).strip()
        parts.append(clean_title)

    return " ".join(parts) + " official audio"


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


async def download_spotify(
    url: str,
    output_dir: Path,
    bitrate: str = "320",
    embed_lyrics: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
    on_file: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> dict:
    """Download Spotify track using oEmbed metadata + yt-dlp YouTube search.
    Returns dict with 'files' (success) and 'failed' (list of failed track dicts).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    is_playlist_url = bool(re.search(r'/(playlist|album)/', url))
    metadata = get_spotify_metadata(url)
    page_info = get_spotify_track_info_from_url(url)

    if is_playlist_url:
        return await _download_playlist(
            url, output_dir, bitrate, metadata, page_info,
            embed_lyrics, on_progress, on_file, on_error
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
    for f in output_dir.iterdir():
        if f.suffix == ".mp3" and f.is_file() and f.name not in downloaded_files:
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


async def _download_playlist(
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
    """Download a Spotify playlist/album by searching each track on YouTube."""
    album_title = ""
    if metadata:
        album_title = metadata.get("title", "") or metadata.get("description", "")
    if not album_title and page_info:
        album_title = page_info.get("title", "")

    album_title = re.sub(r'\s*[\(\[].*?[\)\]]', '', album_title).strip()
    album_title = re.sub(r'\s*-\s*Spotify.*', '', album_title).strip()

    playlist_dir = output_dir / album_title if album_title else output_dir
    playlist_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Fetching playlist tracks from: {url}")

    html_tracks = await _fetch_all_playlist_tracks(url)
    if not html_tracks:
        html_tracks = [album_title] if album_title else []

    total = len(html_tracks)
    logger.info(f"Found {total} tracks in playlist")

    if total == 0:
        if on_error:
            on_error("No tracks found in playlist")
        return []

    downloaded_files = []
    failed_tracks = []

    for i, track_info in enumerate(html_tracks, 1):
        if isinstance(track_info, dict):
            track_name = track_info.get("title", "")
            track_artist = track_info.get("artist", "")
            track_cover = track_info.get("cover", "")
        else:
            track_name = str(track_info)
            track_artist = ""
            track_cover = ""

        logger.info(f"Downloading [{i}/{total}]: {track_name} - {track_artist}")
        if on_progress:
            on_progress(i - 1, total, f"{track_artist} - {track_name}" if track_artist else track_name)

        search_query = _build_search_query(track_name, track_artist)
        logger.info(f"Searching YouTube for: ytsearch:{search_query}")

        output_template = str(playlist_dir / "%(title)s.%(ext)s")

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
            result = await asyncio.to_thread(
                subprocess.run,
                args,
                capture_output=True,
                timeout=300,
            )

            if result.returncode == 0:
                track_cover_data = None
                if track_cover:
                    track_cover_data = await asyncio.to_thread(download_cover_image, track_cover)

                for f in playlist_dir.iterdir():
                    if f.suffix == ".mp3" and f.is_file() and f.name not in downloaded_files:
                        downloaded_files.append(f.name)

                        track_meta = {
                            "title": track_name,
                            "artist": track_artist or "Unknown Artist",
                            "album": album_title,
                            "track_num": str(i),
                        }

                        lyrics = None
                        if embed_lyrics and track_artist and track_name:
                            lyrics = await asyncio.to_thread(fetch_lyrics, track_artist, track_name)

                        await asyncio.to_thread(embed_metadata, f, track_meta, track_cover_data, lyrics)

                        if on_file:
                            on_file(f.name)
                        break
            else:
                logger.warning(f"Failed track {i}/{total}: {track_name}")
                failed_tracks.append({"title": track_name, "artist": track_artist, "error": "yt-dlp failed"})
                if on_error:
                    on_error(f"Failed: {track_name}")
        except Exception as e:
            logger.error(f"Error downloading track {i}: {e}")
            failed_tracks.append({"title": track_name, "artist": track_artist, "error": str(e)})
            if on_error:
                on_error(f"Error: {track_name} - {e}")

    if on_progress:
        on_progress(total, total, "Done")

    return {"files": downloaded_files, "failed": failed_tracks}


async def _fetch_all_playlist_tracks(url: str) -> list[dict]:
    """Fetch ALL tracks from a Spotify playlist/album."""
    info = extract_spotify_id(url)
    if not info:
        return []

    content_type, content_id = info
    tracks = []

    if content_type == "album":
        tracks = await _fetch_album_tracks(content_id)
    elif content_type == "playlist":
        tracks = await _fetch_playlist_tracks(content_id)

    if not tracks:
        tracks = await _fetch_tracks_from_ids(url)

    return tracks


async def _fetch_album_tracks(album_id: str) -> list[dict]:
    """Fetch all tracks from a Spotify album."""
    try:
        def fetch_page():
            return requests.get(
                f"https://open.spotify.com/album/{album_id}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=15,
            )

        resp = await asyncio.to_thread(fetch_page)
        if resp.status_code != 200:
            return []

        html_text = resp.text

        token_match = re.search(r'"accessToken":"([^"]+)"', html_text)
        if token_match:
            token = token_match.group(1)

            def fetch_api():
                return requests.get(
                    f"https://api.spotify.com/v1/albums/{album_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )

            api_resp = await asyncio.to_thread(fetch_api)
            if api_resp.status_code == 200:
                data = api_resp.json()
                tracks = []
                for item in data.get("tracks", {}).get("items", []):
                    track_name = item.get("name", "")
                    artists = [a.get("name", "") for a in item.get("artists", [])]
                    artist_str = ", ".join(artists)
                    cover_url = ""
                    if data.get("images"):
                        cover_url = data["images"][0].get("url", "")
                    tracks.append({
                        "title": html.unescape(track_name),
                        "artist": html.unescape(artist_str),
                        "cover": _upgrade_cover_url(cover_url) if cover_url else "",
                    })
                return tracks

        track_ids = re.findall(r'spotify:track:([a-zA-Z0-9]+)', html_text)
        track_ids = list(dict.fromkeys(track_ids))
        if track_ids:
            return await _fetch_tracks_by_ids(track_ids)

        return []
    except Exception as e:
        logger.warning(f"Failed to fetch album tracks: {e}")
        return []


async def _fetch_playlist_tracks(playlist_id: str) -> list[dict]:
    """Fetch all tracks from a Spotify playlist."""
    try:
        def fetch_page():
            return requests.get(
                f"https://open.spotify.com/playlist/{playlist_id}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=15,
            )

        resp = await asyncio.to_thread(fetch_page)
        if resp.status_code != 200:
            return []

        html_text = resp.text

        token_match = re.search(r'"accessToken":"([^"]+)"', html_text)
        if token_match:
            token = token_match.group(1)
            tracks = []
            offset = 0
            limit = 100
            while True:
                def fetch_api():
                    return requests.get(
                        f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit={limit}&offset={offset}",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=15,
                    )

                api_resp = await asyncio.to_thread(fetch_api)
                if api_resp.status_code != 200:
                    break
                data = api_resp.json()
                items = data.get("items", [])
                for item in items:
                    track = item.get("track")
                    if not track:
                        continue
                    track_name = track.get("name", "")
                    artists = [a.get("name", "") for a in track.get("artists", [])]
                    artist_str = ", ".join(artists)
                    album_data = track.get("album", {})
                    cover_url = ""
                    if album_data.get("images"):
                        cover_url = album_data["images"][0].get("url", "")
                    tracks.append({
                        "title": html.unescape(track_name),
                        "artist": html.unescape(artist_str),
                        "cover": _upgrade_cover_url(cover_url) if cover_url else "",
                    })
                if not data.get("next") or len(items) < limit:
                    break
                offset += limit
            return tracks

        track_ids = re.findall(r'spotify:track:([a-zA-Z0-9]+)', html_text)
        track_ids = list(dict.fromkeys(track_ids))
        if track_ids:
            return await _fetch_tracks_by_ids(track_ids)

        return []
    except Exception as e:
        logger.warning(f"Failed to fetch playlist tracks: {e}")
        return []


async def _fetch_tracks_by_ids(track_ids: list[str]) -> list[dict]:
    """Fetch metadata for tracks by their Spotify IDs using oEmbed + page scraping."""
    sem = asyncio.Semaphore(10)

    async def fetch_one(track_id: str) -> dict | None:
        async with sem:
            try:
                track_url = f"https://open.spotify.com/track/{track_id}"

                def do_oembed():
                    return requests.get(
                        "https://open.spotify.com/oembed",
                        params={"url": track_url},
                        timeout=10,
                    )

                oembed_resp = await asyncio.to_thread(do_oembed)
                title = ""
                thumbnail = ""
                if oembed_resp.status_code == 200:
                    data = oembed_resp.json()
                    title = html.unescape(data.get("title", ""))
                    thumbnail = data.get("thumbnail_url", "")

                artist = ""
                album = ""
                og_image = ""

                def do_page():
                    return requests.get(
                        track_url,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                        timeout=10,
                    )

                page_resp = await asyncio.to_thread(do_page)
                if page_resp.status_code == 200:
                    page_html = page_resp.text
                    og_desc = re.search(r'<meta property="og:description" content="([^"]+)"', page_html)
                    if og_desc:
                        desc = html.unescape(og_desc.group(1))
                        parts = [p.strip() for p in desc.split("\u00B7")]
                        if len(parts) >= 2:
                            artist = parts[0]
                        if len(parts) >= 3:
                            album = parts[1]
                    og_img_match = re.search(r'<meta property="og:image" content="([^"]+)"', page_html)
                    if og_img_match:
                        og_image = og_img_match.group(1)

                cover_url = _upgrade_cover_url(og_image) if og_image else thumbnail

                if title:
                    return {
                        "title": title,
                        "artist": artist,
                        "cover": cover_url,
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch metadata for {track_id}: {e}")
            return None

    tasks = [fetch_one(tid) for tid in track_ids]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]


async def _fetch_tracks_from_ids(url: str) -> list[dict]:
    """Extract track IDs from page HTML and fetch metadata for each."""
    try:
        def fetch_page():
            return requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=15,
            )

        resp = await asyncio.to_thread(fetch_page)
        if resp.status_code != 200:
            return []

        html_text = resp.text
        track_ids = re.findall(r'spotify:track:([a-zA-Z0-9]+)', html_text)
        track_ids = list(dict.fromkeys(track_ids))

        if not track_ids:
            return []

        logger.info(f"Found {len(track_ids)} track IDs, fetching metadata...")
        return await _fetch_tracks_by_ids(track_ids)
    except Exception as e:
        logger.warning(f"Failed to extract track IDs: {e}")
        return []
