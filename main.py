import asyncio
import sys
import logging
import re
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
        logging.StreamHandler(stream=sys.stdout),
        logging.FileHandler(config.BASE_DIR / "logs" / "app.log"),
    ],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SPOTDOWN", version="1.0.0")

task_manager = TaskManager(
    download_dir=config.DOWNLOAD_DIR,
    max_concurrent=config.MAX_CONCURRENT_DOWNLOADS,
)


class DownloadRequest(BaseModel):
    url: str
    bitrate: str = "320"
    output_dir: str = ""
    embed_lyrics: bool = False


class RetryRequest(BaseModel):
    tracks: list[dict]
    is_album: bool = False


class SearchRequest(BaseModel):
    query: str


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

    job = task_manager.create_job(req.url, req.bitrate, output_dir, req.embed_lyrics)
    logger.info(f"Job created: {job.id} for {req.url} @ {req.bitrate}kbps -> {output_dir or config.DOWNLOAD_DIR} lyrics={req.embed_lyrics}")

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


@app.post("/api/stop/{job_id}")
async def stop_job(job_id: str):
    """Stop a running download job."""
    job = task_manager.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    
    if job.status != "processing":
        return JSONResponse(status_code=400, content={"error": "Job is not processing"})
    
    job.stop_event.set()
    return {"status": "stopping", "job_id": job_id}


@app.post("/api/resume/{job_id}")
async def resume_job(job_id: str):
    """Resume a stopped download job."""
    job = task_manager.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    
    if job.status != "stopped":
        return JSONResponse(status_code=400, content={"error": "Job is not stopped"})
    
    # Load progress and restart
    job.load_progress()
    job.status = "queued"
    job.stop_event.clear()
    asyncio.create_task(task_manager.run_job(job))
    
    return {"status": "resumed", "job_id": job_id, "start_index": job.start_index}


@app.post("/api/retry/{job_id}")
async def retry_failed_tracks(job_id: str, req: RetryRequest):
    """Retry specific failed tracks."""
    job = task_manager.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found"})

    if not req.tracks:
        return JSONResponse(status_code=400, content={"error": "No tracks to retry"})

    output_dir = Path(job.output_dir) if job.output_dir else task_manager.download_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    async def run_retry():
        from downloader import retry_single_track
        job.status = "processing"
        job.broadcast("status", {"status": "retrying"})

        retry_files = []
        retry_failed = []

        for track in req.tracks:
            if job.stop_event.is_set():
                break

            track_name = track.get("title", "")
            track_artist = track.get("artist", "")
            track_num = track.get("track_num", 0)

            result = await retry_single_track(
                output_dir=output_dir,
                bitrate=job.bitrate,
                track_name=track_name,
                track_artist=track_artist,
                track_num=track_num,
                is_album=req.is_album,
                embed_lyrics=job.embed_lyrics,
                on_progress=lambda cur, total, t: job.broadcast("progress", {
                    "status": "retrying",
                    "current": cur,
                    "total": total,
                    "track": t,
                }),
                on_file=lambda name: job.broadcast("file", {
                    "status": "retrying",
                    "track": name,
                }),
                on_error=lambda msg: job.broadcast("error", {"error": msg}),
            )

            retry_files.extend(result.get("files", []))
            retry_failed.extend(result.get("failed", []))

        # Update job state
        for f in retry_files:
            if f not in job.files:
                job.files.append(f)
        for ft in req.tracks:
            job.failed_tracks = [f for f in job.failed_tracks if f.get("title") != ft.get("title") or f.get("artist") != ft.get("artist")]
        for f in retry_failed:
            if f not in job.failed_tracks:
                job.failed_tracks.append(f)

        job.status = "completed"
        job.broadcast("retry_complete", {
            "status": "completed",
            "files": job.files,
            "failed_tracks": job.failed_tracks,
        })
        logger.info(f"Job {job.id} retry completed: {len(retry_files)} downloaded, {len(retry_failed)} still failed")

    asyncio.create_task(run_retry())

    return {"status": "retrying", "job_id": job_id, "tracks": len(req.tracks)}


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


@app.get("/api/browse-folder")
async def browse_folder():
    """Open OS folder picker dialog and return selected path."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder = filedialog.askdirectory(title="Select Download Folder")
        root.destroy()
        
        if folder:
            return {"path": folder}
        return {"path": ""}
    except ImportError:
        return JSONResponse(status_code=500, content={"error": "tkinter not available"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/health")
async def api_health():
    import shutil
    return {
        "status": "ok",
        "ffmpeg_available": shutil.which(config.FFMPEG_PATH) is not None,
        "ytdlp_available": shutil.which("yt-dlp") is not None,
        "download_dir": str(config.DOWNLOAD_DIR),
    }


@app.post("/api/search")
async def api_search(req: SearchRequest):
    """Search Spotify for tracks by name/artist."""
    query = req.query.strip()
    if not query:
        return JSONResponse(status_code=400, content={"error": "Search query is required"})

    from downloader import search_spotify
    results = await asyncio.to_thread(search_spotify, query, 10)
    return {"results": results, "query": query}


app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
