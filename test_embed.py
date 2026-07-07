import asyncio, sys, os
sys.path.insert(0, r'C:\Users\mhd0g\Desktop\bot_downloader')

from downloader import (
    _fetch_tracks_by_ids, download_cover_image, embed_metadata,
    _build_search_query, _parse_title_artist
)
from pathlib import Path
import subprocess

async def test():
    # Get track metadata
    tracks = await _fetch_tracks_by_ids(['5hVghJ4KaYES3BFUATCYn0'])
    t = tracks[0]
    print(f"Track: {t['artist']} - {t['title']}")
    print(f"Cover URL: {t['cover']}")

    # Download cover
    cover = download_cover_image(t['cover'])
    print(f"Cover data: {len(cover) if cover else 0} bytes")

    # Download audio
    search = _build_search_query(t['title'], t['artist'])
    out = r'C:\Users\mhd0g\Desktop\bot_downloader\downloads\test_cover.mp3'
    args = [
        "yt-dlp", "--no-playlist",
        "-f", "bestaudio/best",
        "--extract-audio", "--audio-format", "mp3", "--audio-quality", "320k",
        "-o", out,
        "--no-warnings", "--no-check-certificates",
        "--match-filter", "duration<600",
        "--no-update",
        "--extractor-args", "youtube:player_client=android_vr",
        f"ytsearch:{search}",
    ]
    print(f"Searching: {search}")
    result = subprocess.run(args, capture_output=True, timeout=300)
    print(f"yt-dlp exit: {result.returncode}")
    if result.returncode != 0:
        print(f"Error: {result.stderr.decode(errors='replace')[:500]}")
        return

    # Find the file
    for f in Path(out).parent.iterdir():
        if f.suffix == '.mp3' and 'test_cover' not in f.name:
            out = str(f)
            break

    print(f"Downloaded: {out}")

    # Embed metadata
    meta = {
        "title": t['title'],
        "artist": t['artist'],
        "album": "Test Album",
        "track_num": "1",
    }
    embed_metadata(Path(out), meta, cover)

    # Verify
    from mutagen.id3 import ID3
    tags = ID3(out)
    print(f"\nTags: {list(tags.keys())}")
    apic = tags.getall('APIC')
    if apic:
        print(f"APIC: mime={apic[0].mime}, size={len(apic[0].data)} bytes")
        print(f"JPEG valid: {apic[0].data[:2] == bytes([0xff, 0xd8])}")
    else:
        print("NO APIC!")
    print(f"TIT2: {tags.get('TIT2')}")
    print(f"TPE1: {tags.get('TPE1')}")
    print(f"TALB: {tags.get('TALB')}")

asyncio.run(test())
