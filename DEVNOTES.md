# SpotDownMoz - Development Notes & Lessons Learned

## Critical Fixes Applied

### 1. ID3v2.3 Required for Windows Cover Art
**Problem:** mutagen defaults to ID3v2.4 — Windows Explorer and Windows Media Player ignore cover art in v2.4 tags.
**Fix:** `tags.save(file_path, v2_version=3)` forces ID3v2.3 output.
**Also:** Use `desc=""` (empty) in APIC frame, not `desc="Cover"` — some players reject non-empty desc.

### 2. YouTube 403 / Signature Challenges
**Problem:** Default yt-dlp player clients fail with HTTP 403 or signature verification errors.
**Fix:** `--extractor-args "youtube:player_client=android_vr"` bypasses both issues.

### 3. Windows asyncio Subprocess Limitation
**Problem:** `asyncio.create_subprocess_exec` fails silently on Windows with dict kwargs.
**Fix:** Use `asyncio.to_thread(subprocess.run, ...)` with lambda/wrapper functions.

### 4. SSE Broadcast Bug
**Problem:** `str(data)` sent Python repr strings, not JSON.
**Fix:** `json.dumps(data)` for proper SSE JSON payloads.

### 5. HTML Entities in Metadata
**Problem:** Metadata showed `&#x27;` instead of apostrophes.
**Fix:** `html.unescape()` on all parsed strings.

### 6. Spotify API No Longer Embeds Access Tokens
**Problem:** Unauthenticated requests no longer get `accessToken` in page HTML for playlists/albums.
**Fix:** Extract `spotify:track:XXXXX` IDs from page HTML, then fetch metadata via oEmbed + per-track page scraping.

### 7. Cover Art URL Handling
**Problem:** `_upgrade_cover_url()` tried upgrading CDN URLs which broke them. `i.scdn.co` with `ab67616d0000ba32` returns 404.
**Fix:** No-op passthrough — use original `og:image` URLs (`ab67616d0000b273`) as-is.

### 8. --match-filter Syntax
**Problem:** `duration<600 & !original_url*=/shorts/` is invalid and caused ALL downloads to fail silently.
**Fix:** Use simple `duration<600` only.

### 9. Audio-Only Prioritization
**Problem:** yt-dlp `ytsearch:{query}` returns music videos over audio-only tracks.
**Fix:** Append `" official audio"` to search query to prefer audio-only uploads.

## Architecture

- **FastAPI** backend with SSE progress streaming
- **yt-dlp** for YouTube search/download + ffmpeg for MP3 conversion
- **mutagen** for ID3 tag embedding (title, artist, album, track#)
- **Spotify oEmbed + page scraping** for metadata (no API credentials needed)
- Cyberpunk/neon-themed web UI

## File Structure
```
main.py          - FastAPI app, routes, SSE
downloader.py    - Core download logic, metadata, cover art
tasks.py         - Job management, progress broadcasting
transcoder.py    - Audio transcoding utilities
config.py        - Settings, dependency checks
static/          - Frontend (HTML, CSS, JS)
```

## Spotify Metadata Extraction Flow
1. oEmbed API → title, thumbnail (no auth required)
2. Page HTML scrape → og:image, og:description, ld+json (artist, album)
3. For playlists: extract `spotify:track:XXX` IDs from HTML, then fetch each via oEmbed + page scrape
