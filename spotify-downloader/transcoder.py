import asyncio
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


async def get_audio_info(file_path: str) -> dict:
    """Get audio file info via ffprobe."""
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {}


async def transcode(input_path: str, output_path: str, bitrate: str = "320") -> bool:
    """Transcode audio file to target bitrate MP3 using FFmpeg."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

    cmd = [
        ffmpeg,
        "-i", str(input_path),
        "-codec:a", "libmp3lame",
        "-b:a", f"{bitrate}k",
        "-y",
        str(output_path),
    ]

    logger.info(f"Transcoding: {input_path} -> {output_path} @ {bitrate}kbps")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"FFmpeg failed: {stderr.decode()[:500]}")
        return False

    logger.info(f"Transcoding complete: {output_path}")
    return True


async def transcode_to_bitrate(
    input_path: Path,
    output_dir: Path,
    bitrate: str = "320",
) -> Path | None:
    """Transcode a file to the desired bitrate, return output path or None on failure."""
    stem = input_path.stem
    output_path = output_dir / f"{stem}.mp3"

    if input_path.suffix == ".mp3":
        info = await get_audio_info(str(input_path))
        current_bitrate = "0"
        try:
            for stream in info.get("streams", []):
                if stream.get("codec_type") == "audio":
                    current_bitrate = str(int(stream.get("bit_rate", 0)) // 1000)
                    break
        except (ValueError, TypeError):
            pass

        if current_bitrate == bitrate:
            if input_path != output_path:
                import aiofiles
                async with aiofiles.open(output_path, "wb") as f:
                    async with aiofiles.open(input_path, "rb") as src:
                        await f.write(await src.read())
            return output_path

    success = await transcode(str(input_path), str(output_path), bitrate)
    if success and output_path.exists():
        return output_path
    return None
