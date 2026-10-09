#!/usr/bin/env python3
"""Get a YouTube video's metadata and transcript without getting stuck on 429s.

YouTube rate-limits its subtitle endpoint (timedtext) hard, but the audio
streams still download. So: try captions once, and on any failure download the
audio and transcribe it locally with whisper.cpp (model path in WHISPER_MODEL).

Usage: yt_transcript.py <url> [out_dir]
Prints the paths of <id>.meta.txt and <id>.transcript.txt, and which route worked.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Optional: a browser to borrow YouTube cookies from on the last try (macOS may ask
# for the keychain, so leave unset for unattended runs). e.g. LEARN_COOKIES_BROWSER=chrome
COOKIES = os.environ.get("LEARN_COOKIES_BROWSER")
MODEL = Path(os.environ.get("WHISPER_MODEL", Path.home() / ".local/share/whisper/ggml-large-v3-turbo.bin"))


def run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def vtt_to_text(vtt: str) -> str:
    lines, last = [], None
    for line in vtt.splitlines():
        if not line.strip() or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        # Auto captions repeat each line as it scrolls; keep each once.
        if line and line != last:
            lines.append(line)
            last = line
    return " ".join(lines)


def main():
    if len(sys.argv) < 2:
        die("usage: yt_transcript.py <url> [out_dir]")
    url = sys.argv[1]
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/learn")
    out.mkdir(parents=True, exist_ok=True)
    if not shutil.which("yt-dlp"):
        die("yt-dlp missing (brew install yt-dlp)")

    # Instagram and Facebook answer nothing without a session, so borrow cookies on every call there.
    login = COOKIES and re.search(r"instagram\.com|facebook\.com|fb\.watch", url)
    session = ["--cookies-from-browser", COOKIES] if login else []

    # 1. Metadata (the watch page itself is not rate-limited the way captions are).
    r = run(["yt-dlp", "--skip-download", "--dump-single-json", "--no-warnings", *session, url], 90)
    if r.returncode != 0:
        die(f"metadata failed: {r.stderr.strip()[-300:]}")
    info = json.loads(r.stdout)
    vid = info["id"]
    chapters = "\n".join(f"  {int(c['start_time'])//60}:{int(c['start_time'])%60:02d} {c['title']}" for c in info.get("chapters") or [])
    meta = out / f"{vid}.meta.txt"
    meta.write_text(
        f"TITLE: {info.get('title')}\nCHANNEL: {info.get('channel') or info.get('uploader')}\n"
        f"UPLOADED: {info.get('upload_date')}\nDURATION: {info.get('duration_string')}\nURL: {info.get('webpage_url')}\n"
        + (f"CHAPTERS:\n{chapters}\n" if chapters else "")
        + f"\nDESCRIPTION:\n{info.get('description') or ''}\n"
    )
    transcript = out / f"{vid}.transcript.txt"

    # 2. Captions, one quick try. Manual subs first, then auto, English or Romanian.
    r = run(["yt-dlp", *session, "--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "en.*,ro.*",
             "--sub-format", "vtt", "--no-warnings", "-o", str(out / f"{vid}.%(ext)s"), url], 60)
    vtts = sorted(out.glob(f"{vid}*.vtt"))
    if vtts:
        text = vtt_to_text(vtts[0].read_text(errors="ignore"))
        if len(text) > 200:
            transcript.write_text(text)
            print(f"ROUTE: captions ({vtts[0].name})\nMETA: {meta}\nTRANSCRIPT: {transcript}")
            return

    # 3. Audio + local whisper. Only this route needs ffmpeg and whisper.cpp, so
    # captioned videos work with yt-dlp alone.
    for b in ("ffmpeg", "whisper-cli"):
        if not shutil.which(b):
            die(f"no usable captions, and transcribing needs {b} (brew install {'whisper-cpp' if b == 'whisper-cli' else b})")
    if not MODEL.exists():
        die(f"no usable captions, and the whisper model is missing: {MODEL}")
    # YouTube 403s audio URLs intermittently; a retry a few seconds later usually
    # gets a fresh URL that works. Format 18 (360p mp4 with sound) is the last resort.
    audio, errors = None, []
    for i, fmt in enumerate(["ba[abr<=96]/ba", "ba[abr<=96]/ba", "18/worst"]):
        if i:
            time.sleep(8 * i)
        cookies = ["--cookies-from-browser", COOKIES] if COOKIES and (login or i == 2) else []
        r = run(["yt-dlp", "-f", fmt, *cookies, "--no-warnings", "--no-playlist", "--retries", "5",
                 "--fragment-retries", "5", "-o", str(out / f"{vid}.audio.%(ext)s"), url], 900)
        audio = next((a for a in out.glob(f"{vid}.audio.*") if not a.name.endswith(".part")), None)
        if r.returncode == 0 and audio:
            break
        errors.append(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"exit {r.returncode}")
        for a in out.glob(f"{vid}.audio.*"):
            a.unlink(missing_ok=True)
        audio = None
    if audio is None:
        die("captions and audio both failed after 3 tries: " + " | ".join(errors)[-500:])
    wav = out / f"{vid}.wav"
    r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio), "-ar", "16000", "-ac", "1", str(wav)], 600)
    if r.returncode != 0:
        die(f"ffmpeg failed: {r.stderr.strip()[-300:]}")
    base = out / f"{vid}.whisper"
    r = run(["whisper-cli", "-m", str(MODEL), "-l", "auto", "-mc", "0", "-nt", "-otxt", "-of", str(base), "-f", str(wav)], 3600)
    txt = Path(f"{base}.txt")
    if r.returncode != 0 or not txt.exists():
        die(f"whisper failed: {r.stderr.strip()[-300:]}")
    transcript.write_text(" ".join(txt.read_text().split()))
    for p in (audio, wav, txt):
        p.unlink(missing_ok=True)
    print(f"ROUTE: local whisper (captions were blocked)\nMETA: {meta}\nTRANSCRIPT: {transcript}")


if __name__ == "__main__":
    main()
