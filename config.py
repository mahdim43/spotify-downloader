import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "./downloads")).resolve()
if not DOWNLOAD_DIR.exists():
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

MAX_CONCURRENT_DOWNLOADS = 5
JOB_CLEANUP_SECONDS = 1800

def check_dependencies():
    issues = []

    import shutil
    if not shutil.which(FFMPEG_PATH):
        issues.append("FFmpeg not found in PATH")

    try:
        import spotdl
    except ImportError:
        issues.append("spotdl not installed")

    if not shutil.which("yt-dlp"):
        issues.append("yt-dlp not found in PATH")

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        issues.append("SPOTIFY_CLIENT_ID/SECRET not set in .env (optional for single tracks, required for playlist metadata)")

    return issues
