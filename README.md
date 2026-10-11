# 🎵 Music Downloader

A friendly command-line tool to download music from (almost) anywhere on the
internet, powered by [**yt-dlp**](https://github.com/yt-dlp/yt-dlp) and
**ffmpeg**.

Give it a link or just type a song name — it finds the audio, converts it to
MP3 (or another format), and neatly tags it with the title, artist, and album
art.

---

## ✨ Features

- **Spotify & Deezer links** — paste a **track**, **album**, or **playlist** URL
  and the tool reads the song list, then finds each song on a streaming provider.
- **Multiple providers** — audio is fetched from whichever source works first
  (SoundCloud, YouTube, ...); pick one with `--source` or let it auto-fall-back.
- **Search by name** — `never gonna give you up` just works, no URL needed.
- **Many sites** — YouTube, SoundCloud, Bandcamp, Audiomack, Yandex Music and
  1000+ more via yt-dlp.
- **Audio-only by default** — strips video and keeps just the music.
- **Format choice** — MP3, M4A, Opus, FLAC, WAV, Vorbis.
- **Auto tagging** — title, artist, and embedded cover art (correct metadata for
  tracks coming from a Spotify/Deezer link). Short previews are skipped when the
  real song length is known.
- **Playlists** — grab a whole album/playlist in one command.
- **Batch mode** — download a whole list of songs from a text file.
- **Organised output** — files sorted into `<artist>/<title> [<id>].mp3`.

---

## 🎧 Spotify & Deezer support

You can point the downloader straight at Spotify or Deezer links:

```bash
# A single song
./download.sh "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
./download.sh "https://www.deezer.com/track/986646892"

# A whole album
./download.sh "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy"
./download.sh "https://www.deezer.com/en/album/185386862"

# A whole playlist
./download.sh "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
./download.sh "https://www.deezer.com/us/playlist/6298161304"
```

`spotify:` URIs and country-prefixed links (e.g. `.../intl-de/track/<id>`,
`.../en/album/<id>`) are also accepted.

**How it works:** Spotify and Deezer audio is DRM-protected and cannot be
downloaded directly. The tool therefore reads the public **metadata** (song
titles, artists, album names, cover art, durations) from those services, then
locates a matching audio track on a streaming provider with yt-dlp and saves it
with the correct tags. No login or API key is required.

> **Note:** because it matches against providers such as YouTube, a bot-check
> can occasionally block a request. See the troubleshooting section below for
> passing your browser cookies or forcing another provider.

---

## 🌐 Providers

For **search-by-name** and for **Spotify/Deezer** tracks, the tool looks the
song up on a streaming provider. By default it tries **SoundCloud first**, then
**YouTube**, and returns the first one that downloads — so if one site is
blocked or a result is DRM-protected, it automatically falls through to the
next.

Pick a provider explicitly with `--source`:

```bash
# Only use YouTube
./download.sh -s "daft punk one more time" --source youtube

# Only use SoundCloud
./download.sh -s "daft punk one more time" --source soundcloud
```

Direct URLs for **Bandcamp**, **Audiomack**, **Yandex Music**, etc. can be
passed straight to yt-dlp as usual (e.g. `./download.sh "<bandcamp url>"`).

---

## 📦 Requirements

| Tool    | Notes                                             |
| ------- | ------------------------------------------------- |
| Python  | 3.8 or newer                                      |
| ffmpeg  | Must be on your `PATH` — <https://ffmpeg.org/>    |
| yt-dlp  | Installed automatically into the virtual env      |
| requests| Installed automatically (used for Spotify/Deezer) |
| mutagen | Installed automatically (used for retagging)      |

> **Optional — YouTube sign-in workaround:** recent yt-dlp needs a JavaScript
> runtime (Deno or Node.js) on your `PATH` to solve some of YouTube's signature
> challenges. The tool auto-detects one; if none is found it still works but
> some YouTube formats may be unavailable. Install **Deno** (`curl -fsSL
> https://deno.land/install.sh | sh`) or **Node.js** to get the best YouTube
> results.

### Install ffmpeg

- **Fedora / RHEL:** `sudo dnf install ffmpeg`
- **Debian / Ubuntu:** `sudo apt install ffmpeg`
- **macOS (Homebrew):** `brew install ffmpeg`
- **Windows:** download a build from <https://ffmpeg.org/download.html>

---

## 🚀 Quick start

The easiest way is the included wrapper script, which sets everything up for
you on first run:

```bash
# Download a single song by searching for it
./download.sh -s "daft punk one more time"

# Download straight from a URL
./download.sh "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Manual setup (optional)

If you prefer to manage the environment yourself:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python music_downloader.py -s "your favourite song"
```

---

## 🎛️ Usage

```
python music_downloader.py [OPTIONS] [TARGET]
```

| Option            | Description                                             |
| ----------------- | ------------------------------------------------------- |
| `-s`, `--search`  | Treat the target as a search query, not a URL.          |
| `-o`, `--output-dir DIR` | Where to save files (default: `downloads`).      |
| `-f`, `--format FMT`     | Audio format: mp3, m4a, opus, wav, flac, vorbis. |
| `-q`, `--quality N`      | Quality `0` (best) – `10` (worst). Default `0`. |
| `--playlist`      | Download an entire playlist, not just one track.        |
| `--video`         | Download the full video (≤1080p) instead of audio.      |
| `--no-thumbnail`  | Skip embedding cover art.                               |
| `--no-metadata`   | Skip writing metadata tags.                             |
| `--source PROVIDER` | Where to fetch audio: `auto`, `soundcloud`, or `youtube`. |
| `--cookies-from-browser BROWSER` | Load cookies from a browser (e.g. `chrome`, `firefox:Default`) so yt-dlp can use your logged-in session. |
| `--batch FILE`    | Read targets from a file, one per line.                 |
| `--quiet`         | Suppress progress output.                               |
| `-h`, `--help`    | Show the full help message.                             |

### Examples

```bash
# Best-quality MP3 from a search term
python music_downloader.py -s "bohemian rhapsody queen"

# Download a playlist as FLAC
python music_downloader.py "PLAYLIST_URL" --playlist -f flac

# Save the full music video instead of audio
python music_downloader.py "VIDEO_URL" --video

# Batch download a list of songs
python music_downloader.py --batch my_songs.txt

# Download a Spotify track / album / playlist
python music_downloader.py "https://open.spotify.com/album/<id>"

# Use your Chrome login to get past YouTube's bot check
python music_downloader.py -s "some song" --cookies-from-browser chrome
```

> **🔑 About browser cookies** — `--cookies-from-browser chrome` tells yt-dlp to
> read the cookies from an installed browser so it can act as *your* logged-in
> session. This is the official, consented way to get past YouTube's
> *"Sign in to confirm you're not a bot"* block, and only works with a browser
> you're already signed into. **It applies to YouTube and other yt-dlp
> providers — not to Deezer**, whose full audio is DRM-encrypted (Deezer is used
> for metadata only, so cookies can't unlock Deezer downloads).

### Batch file format

Create a plain text file with one URL or search term per line. Lines starting
with `#` are ignored:

```text
# my favourites
https://www.youtube.com/watch?v=dQw4w9WgXcQ
daft punk one more time
nujabes aruarian dance
```

---

## 📁 Where do files go?

Downloads are written to the output directory (default `downloads/`), grouped
by artist/channel:

```
downloads/
└── RickAstleyVEVO/
    └── Never Gonna Give You Up [dQw4w9WgXcQ].mp3
```

---

## ⚠️ Notes & troubleshooting

- **YouTube "Sign in to confirm you're not a bot"?**
  YouTube actively blocks automated downloads. Options:
  - Pass your browser cookies:
    `yt-dlp --cookies-from-browser chrome "URL"`
    (The `MusicDownloader` accepts extra yt-dlp options via `config.extra`.)
  - Use a source that is less restrictive (SoundCloud, Bandcamp, archive.org).
- **"ffmpeg not found"?** Install ffmpeg (see above) and make sure it is on
  your `PATH`.
- **Only respect the law & creators' rights.** Download only content you own
  or that is freely licensed (public domain, Creative Commons, etc.).

---

## 🧩 Project layout

| File                  | Purpose                                          |
| --------------------- | ------------------------------------------------ |
| `music_downloader.py` | The main application and CLI.                    |
| `spotify.py`          | Reads Spotify track/album/playlist metadata.     |
| `deezer.py`           | Reads Deezer track/album/playlist metadata.      |
| `providers.py`        | Audio-source registry & fallback ordering.       |
| `download.sh`         | Convenience wrapper (auto-sets-up the venv).     |
| `requirements.txt`    | Python dependencies.                             |
| `.venv/`              | Auto-created virtual environment.                |

---

## 📄 License

This project is a thin wrapper around [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(Unlicense). Please comply with yt-dlp's terms and the terms of any site you
download from. Use responsibly.
