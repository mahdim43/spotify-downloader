# SPOTDOWN

A cyberpunk-themed Spotify music downloader with a neon-glowing web UI.

## Features

- **Search & Download** — Search songs by name/artist directly, no URL needed
- Download Spotify tracks, albums, and playlists as MP3
- Full metadata embedding (title, artist, album, cover art)
- 192/320 kbps bitrate selection
- Album track numbering (01.Song - Artist.mp3)
- Retry failed tracks with one click
- Real-time SSE progress updates
- Stop/Resume downloads
- Output directory selector
- Lyrics embedding (synced + plain)
- High-resolution cover art (640x640)
- Duplicate detection (skips already downloaded tracks)
- Cyberpunk/neon-themed responsive UI

## Requirements

- Python 3.10+
- FFmpeg (must be in PATH)
- yt-dlp

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/mahdim43/spotify-downloader.git
   cd spotify-downloader
   ```

2. Create virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   source venv/bin/activate  # Linux/Mac
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the server:
   ```bash
   python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

5. Open http://localhost:8000 in your browser.

## Usage

### Search
1. Type a song name or artist in the input field (e.g. "Bohemian Rhapsody")
2. Click **EXEC** or press Enter
3. Browse search results with cover art, artist, album, and duration
4. Click **DOWNLOAD** on any result to start downloading

### Direct URL
1. Paste a Spotify track/album/playlist URL
2. Select bitrate (192/320 kbps)
3. Click **EXEC** to start downloading
4. Real-time progress updates via SSE

### Albums
- Album tracks are automatically numbered (01.Song - Artist.mp3)
- Album cover art is applied to all tracks

### Failed Tracks
- Click **RETRY** on individual failed tracks or **RETRY ALL FAILED** for bulk retry
- Retried tracks preserve correct album numbering

## Tech Stack

- **Backend**: Python, FastAPI, uvicorn
- **Frontend**: Vanilla JS, CSS3 (Neon theme)
- **Download**: yt-dlp + FFmpeg
- **Metadata**: Mutagen (ID3v2.3 tags)
- **Search**: spotify_scraper (no API credentials needed)

## License

MIT
