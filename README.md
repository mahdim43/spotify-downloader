# SPOTDOWN

A cyberpunk-themed Spotify music downloader with a neon-glowing web UI.

## Features

- Download Spotify tracks, albums, and playlists as MP3
- Full metadata embedding (title, artist, album, cover art)
- 192/320 kbps bitrate selection
- Cyberpunk/neon-themed responsive UI
- Real-time SSE progress updates
- Output directory selector
- Playlist/album support with unlimited track fetching (pagination)
- High-resolution cover art (640x640)

## Requirements

- Python 3.10+
- FFmpeg (must be in PATH)
- yt-dlp

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/mahdim43/spotdownmoz.git
   cd spotdownmoz
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

4. (Optional) Create `.env` file for Spotify API credentials:
   ```
   SPOTIFY_CLIENT_ID=your_id
   SPOTIFY_CLIENT_SECRET=your_secret
   ```

5. Run the server:
   ```bash
   python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

6. Open http://localhost:8000 in your browser.

## Usage

1. Paste a Spotify track/album/playlist URL
2. Select bitrate (192/320 kbps)
3. Click **EXEC** to start downloading
4. Real-time progress updates via SSE

## Tech Stack

- **Backend**: Python, FastAPI, uvicorn
- **Frontend**: Vanilla JS, CSS3 (Neon theme)
- **Download**: yt-dlp + FFmpeg
- **Metadata**: Mutagen (ID3 tags)

## License

MIT
