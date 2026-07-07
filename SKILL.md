# Spotify Downloader Skill

## Project Overview
Self-hosted Spotify music downloader with cyberpunk web UI. Downloads tracks/albums/playlists as MP3 (192/320kbps) with full metadata via YouTube search.

## Tech Stack
- Python 3.13, FastAPI, yt-dlp, ffmpeg, mutagen, uvicorn
- Frontend: HTML/CSS/JS with neon cyberpunk theme

## Critical Lessons Learned

### mutagen / ID3 Tags
- **ALWAYS** use `tags.save(file_path, v2_version=3)` — Windows ignores cover art in ID3v2.4
- Use `desc=""` in APIC frame (not `desc="Cover"`) for maximum player compatibility
- APIC frame: `encoding=3, mime="image/jpeg", type=3, desc="", data=cover_bytes`

### yt-dlp / YouTube
- **MUST** use `--extractor-args "youtube:player_client=android_vr"` — other clients fail with 403/sig challenges
- Append `" official audio"` to search queries to prefer audio-only over music videos
- Use `--match-filter "duration<600"` (simple syntax only — complex filters break silently)
- `-f bestaudio/best` + `--extract-audio --audio-format mp3 --audio-quality {bitrate}k`

### Windows + asyncio
- Cannot use `asyncio.create_subprocess_exec` with dict kwargs on Windows
- Must use `asyncio.to_thread(subprocess.run, args, ...)` as wrapper
- Example pattern:
  ```python
  result = await asyncio.to_thread(
      subprocess.run, args, capture_output=True, timeout=300
  )
  ```

### Spotify Metadata (No API Credentials)
- oEmbed API: `GET https://open.spotify.com/oembed?url={track_url}` → title, thumbnail
- Page scraping: fetch HTML, parse `og:image`, `og:description`, `ld+json` for artist/album
- Playlist/album tracks: extract `spotify:track:XXXXX` IDs from page HTML, then fetch each individually
- Cover art URLs: use original `og:image` URLs as-is (no CDN upgrades)
- `html.unescape()` ALL parsed metadata strings

### SSE (Server-Sent Events)
- Use `json.dumps(data)` not `str(data)` for payloads
- Keepalive with `: keepalive\n\n` on timeout

### FastAPI Async Wrapping
- Wrap sync functions with `async def` using `await asyncio.to_thread(sync_func, ...)`
- Pass simple positional args only — no dict kwargs to `asyncio.to_thread`

## Key File Locations
- `downloader.py` — core download logic, metadata embedding, Spotify scraping
- `tasks.py` — job management, progress broadcasting
- `main.py` — FastAPI routes, SSE endpoints
- `static/js/app.js` — frontend download UI
- `static/js/ui.js` — UI helpers (toast, progress, etc.)
- `static/js/api.js` — API client, SSE connection

## Testing Checklist
1. Single track download with cover art
2. Playlist download with per-track cover art
3. Verify ID3v2.3 (check `tags.version` returns `(2, 3, 0)`)
4. Verify APIC frame exists with valid JPEG data
5. Test in Windows Media Player and File Explorer
