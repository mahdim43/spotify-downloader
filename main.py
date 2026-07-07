import asyncio
import logging
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from tasks import TaskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.BASE_DIR / "logs" / "app.log"),
    ],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SpotDownMoz", version="1.0.0")

task_manager = TaskManager(
    download_dir=config.DOWNLOAD_DIR,
    max_concurrent=config.MAX_CONCURRENT_DOWNLOADS,
)


class DownloadRequest(BaseModel):
    url: str
    bitrate: str = "320"
    output_dir: str = ""


SPOTIFY_URL_RE = re.compile(
    r'https?://open\.spotify\.com/(track|playlist|album)/([a-zA-Z0-9]+)'
)


def validate_spotify_url(url: str) -> tuple[bool, str]:
    if not url or not url.strip():
        return False, "URL is required"
    if not SPOTIFY_URL_RE.search(url):
        return False, "Invalid Spotify URL. Must be a track, playlist, or album URL."
    return True, ""


@app.on_event("startup")
async def startup():
    issues = config.check_dependencies()
    for issue in issues:
        logger.warning(f"Dependency issue: {issue}")
    await task_manager.start_cleanup()
    logger.info(f"Server starting. Downloads dir: {config.DOWNLOAD_DIR}")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = config.BASE_DIR / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/api/download")
async def api_download(req: DownloadRequest):
    valid, error = validate_spotify_url(req.url)
    if not valid:
        return JSONResponse(status_code=400, content={"error": error})

    if req.bitrate not in ("192", "320"):
        return JSONResponse(status_code=400, content={"error": "Bitrate must be '192' or '320'"})

    output_dir = req.output_dir.strip() if req.output_dir else ""

    job = task_manager.create_job(req.url, req.bitrate, output_dir)
    logger.info(f"Job created: {job.id} for {req.url} @ {req.bitrate}kbps -> {output_dir or config.DOWNLOAD_DIR}")

    asyncio.create_task(task_manager.run_job(job))

    m = SPOTIFY_URL_RE.search(req.url)
    platform_type = m.group(1) if m else "track"
    is_playlist = platform_type in ("playlist", "album")

    return {
        "job_id": job.id,
        "status": "queued",
        "platform": "spotify",
        "is_playlist": is_playlist,
    }


@app.get("/api/progress/{job_id}")
async def api_progress(job_id: str):
    job = task_manager.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found"})

    queue = job.subscribe()

    async def event_generator():
        try:
            import json
            initial = f"event: status\ndata: {json.dumps(job.to_dict())}\n\n"
            yield initial

            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                    yield payload

                    if '"completed"' in payload or '"failed"' in payload:
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            job.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/files/{filename:path}")
async def api_files(filename: str):
    file_path = config.DOWNLOAD_DIR / filename
    if not file_path.exists():
        return JSONResponse(status_code=404, content={"error": "File not found"})

    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        filename=file_path.name,
    )


@app.get("/api/files")
async def api_list_files():
    files = []
    for f in config.DOWNLOAD_DIR.rglob("*.mp3"):
        rel = f.relative_to(config.DOWNLOAD_DIR)
        files.append({
            "name": f.name,
            "path": str(rel),
            "size": f.stat().st_size,
            "url": f"/files/{rel.as_posix()}",
        })
    return {"files": files}


@app.get("/api/health")
async def api_health():
    import shutil
    return {
        "status": "ok",
        "ffmpeg_available": shutil.which(config.FFMPEG_PATH) is not None,
        "spotdl_available": True,
        "ytdlp_available": shutil.which("yt-dlp") is not None,
        "download_dir": str(config.DOWNLOAD_DIR),
    }


app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
