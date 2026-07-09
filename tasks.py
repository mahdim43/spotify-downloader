import asyncio
import json
import logging
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


class Job:
    def __init__(self, url: str, bitrate: str = "320", output_dir: str = "", embed_lyrics: bool = False, parallel: int = 1):
        self.id = str(uuid.uuid4())
        self.url = url
        self.bitrate = bitrate
        self.output_dir = output_dir
        self.embed_lyrics = embed_lyrics
        self.parallel = parallel
        self.status = "queued"
        self.total = 0
        self.completed = 0
        self.failed = 0
        self.files: list[str] = []
        self.skipped_files: list[str] = []
        self.failed_tracks: list[dict] = []
        self.errors: list[str] = []
        self.current_track = ""
        self.subscribers: list[asyncio.Queue] = []
        self.stop_event = asyncio.Event()
        self.start_index = 0
        self.progress_file = Path(f".job_progress_{self.id}.json")

    def to_dict(self) -> dict:
        return {
            "job_id": self.id,
            "status": self.status,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "files": self.files,
            "failed_tracks": self.failed_tracks,
            "errors": self.errors,
            "current_track": self.current_track,
            "bitrate": self.bitrate,
            "parallel": self.parallel,
        }

    def save_progress(self):
        """Save current progress to file for resume."""
        try:
            data = {
                "url": self.url,
                "bitrate": self.bitrate,
                "output_dir": self.output_dir,
                "embed_lyrics": self.embed_lyrics,
                "parallel": self.parallel,
                "start_index": self.completed + len(self.skipped_files),
                "files": self.files,
                "skipped_files": self.skipped_files,
                "failed_tracks": self.failed_tracks,
            }
            self.progress_file.write_text(json.dumps(data))
            logger.info(f"Job {self.id}: Progress saved at index {data['start_index']}")
        except Exception as e:
            logger.error(f"Job {self.id}: Failed to save progress: {e}")

    def load_progress(self) -> bool:
        """Load progress from file. Returns True if progress was loaded."""
        try:
            if self.progress_file.exists():
                data = json.loads(self.progress_file.read_text())
                self.start_index = data.get("start_index", 0)
                self.files = data.get("files", [])
                self.skipped_files = data.get("skipped_files", [])
                self.failed_tracks = data.get("failed_tracks", [])
                self.parallel = data.get("parallel", 1)
                logger.info(f"Job {self.id}: Loaded progress from index {self.start_index}")
                return True
        except Exception as e:
            logger.error(f"Job {self.id}: Failed to load progress: {e}")
        return False

    def cleanup_progress(self):
        """Remove progress file after completion."""
        try:
            if self.progress_file.exists():
                self.progress_file.unlink()
        except Exception:
            pass

    def broadcast(self, event: str, data: dict):
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        for q in self.subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)


class TaskManager:
    def __init__(self, download_dir: Path, max_concurrent: int = 5):
        self.download_dir = download_dir
        self.jobs: dict[str, Job] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._cleanup_task: asyncio.Task | None = None

    async def start_cleanup(self):
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(300)
            to_remove = []
            for job_id, job in self.jobs.items():
                if job.status in ("completed", "failed"):
                    to_remove.append(job_id)
            for job_id in to_remove:
                del self.jobs[job_id]

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def create_job(self, url: str, bitrate: str = "320", output_dir: str = "", embed_lyrics: bool = False, parallel: int = 1) -> Job:
        job = Job(url, bitrate, output_dir, embed_lyrics, parallel)
        self.jobs[job.id] = job
        return job

    async def run_job(self, job: Job):
        async with self.semaphore:
            job.status = "processing"
            job.stop_event.clear()
            job.broadcast("status", {"status": "processing"})

            if job.output_dir:
                output_dir = Path(job.output_dir)
            else:
                output_dir = self.download_dir

            output_dir.mkdir(parents=True, exist_ok=True)

            # Load progress if resuming
            if job.start_index > 0:
                job.load_progress()

            try:
                from downloader import download_spotify

                result = await download_spotify(
                    url=job.url,
                    output_dir=output_dir,
                    bitrate=job.bitrate,
                    embed_lyrics=job.embed_lyrics,
                    stop_event=job.stop_event,
                    start_index=job.start_index,
                    parallel=job.parallel,
                    on_progress=lambda cur, total, track: self._on_progress(job, cur, total, track),
                    on_file=lambda name: self._on_file(job, name),
                    on_error=lambda msg: self._on_error(job, msg),
                )

                # Check if stopped
                if job.stop_event.is_set():
                    job.status = "stopped"
                    job.save_progress()
                    job.broadcast("stopped", {
                        "status": "stopped",
                        "current": job.completed,
                        "total": job.total,
                    })
                    logger.info(f"Job {job.id} stopped at index {job.completed}")
                    return

                job.files = result.get("files", [])
                job.skipped_files = result.get("skipped", [])
                job.failed_tracks = result.get("failed", [])
                job.status = "completed"
                job.cleanup_progress()
                job.broadcast("complete", {
                    "status": "completed",
                    "files": job.files,
                    "skipped_files": job.skipped_files,
                    "failed_tracks": job.failed_tracks,
                    "total": job.total,
                    "downloaded": len(job.files),
                    "skipped": len(job.skipped_files),
                    "failed": job.failed,
                })
                logger.info(f"Job {job.id} completed: {len(job.files)} downloaded, {len(job.skipped_files)} skipped, {job.failed} failed")

            except Exception as e:
                logger.error(f"Job {job.id} failed: {e}", exc_info=True)
                job.status = "failed"
                job.errors.append(str(e))
                job.broadcast("error", {"status": "failed", "error": str(e)})

    def _on_progress(self, job: Job, current: int, total: int, track: str):
        job.total = total
        job.completed = current
        job.current_track = track
        job.broadcast("progress", {
            "status": "downloading",
            "current": current,
            "total": total,
            "track": track,
        })

    def _on_file(self, job: Job, name: str):
        job.files.append(name)
        job.broadcast("file", {
            "status": "downloading",
            "current": job.completed,
            "total": job.total,
            "track": name,
        })

    def _on_error(self, job: Job, msg: str):
        job.errors.append(msg)
        job.failed += 1
