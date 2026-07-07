import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

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

    if not shutil.which("yt-dlp"):
        issues.append("yt-dlp not found in PATH")

    return issues
