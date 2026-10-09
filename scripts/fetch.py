#!/usr/bin/env python3
"""Fetch any link's content as text for /learn, picking the route by platform.

Routes follow Agent Reach (github.com/Panniantong/Agent-Reach): every platform has
an ordered backend list, the first one that returns real content wins. Free,
no-login routes come first; login-backed tools (opencli, rdt, twitter-cli) are
used only when installed.

  YouTube and other video/audio hosts -> yt_transcript.py (captions, else local whisper)
  Instagram / TikTok / Facebook       -> yt-dlp caption (+ transcript for videos)
  X / Twitter                         -> fxtwitter thread API > X API (bearer) > twitter-cli
  Reddit                              -> Reddit RSS (post + comments) > opencli > rdt
  GitHub                              -> gh CLI (repo + README, issue, PR) > Jina
  LinkedIn                            -> Jina (else BLOCKED: paste the text)
  anything else (articles, PDFs, RSS) -> Jina Reader > direct fetch

Usage: fetch.py <url> [out_dir]
Prints ROUTE: and CONTENT: (plus META: for media). Exit 0 ok, 1 error,
2 BLOCKED (the platform needs a login or tool that is not set up; the message says which).
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
X_KEY = Path.home() / ".claude/x-api-key"
COOKIES = os.environ.get("LEARN_COOKIES_BROWSER")  # e.g. chrome; may prompt for the keychain
MEDIA_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "loom.com", "twitch.tv", "soundcloud.com",
               "podcasts.apple.com", "ted.com", "dailymotion.com", "rumble.com", "wistia.com")
SOCIAL_VIDEO = ("instagram.com", "tiktok.com", "facebook.com", "fb.watch")


class Blocked(Exception):
    pass


def http(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def strip_html(s):
    s = re.sub(r"<(br|/p|/div|/li|/h\d)[^>]*>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(s)).strip()


def save(out, name, text, route, meta=None):
    if len(text.strip()) < 80:
        raise ValueError(f"{route}: almost no content ({len(text.strip())} chars)")
    p = out / f"{name}.txt"
    p.write_text(text)
    print(f"ROUTE: {route}")
    if meta:
        print(f"META: {meta}")
    print(f"CONTENT: {p}")


def chain(out, name, routes):
    """Try (label, fn) routes in order; fn returns text or raises. First real content wins."""
    errors = []
    for label, fn in routes:
        try:
            save(out, name, fn(), label)
            return
        except Blocked:
            raise
        except Exception as e:  # noqa: BLE001 - any failure means: next backend
            errors.append(f"{label}: {str(e)[:160]}")
    raise RuntimeError(" | ".join(errors))


# --- Web ---------------------------------------------------------------------

def jina(url):
    # Jina answers 403 to browser user agents, so it gets a plain one.
    text = http(f"https://r.jina.ai/{url}", {"Accept": "text/plain", "User-Agent": "tiliaris-learn/1.0"}, timeout=60)
    if re.search(r'"code":\s*4\d\d|Target URL returned error 4\d\d|AbuseAlleviationError', text[:600]):
        raise ValueError(text[:200].replace("\n", " "))
    return text


def direct(url):
    page = http(url)
    page = re.sub(r"(?is)<(script|style|nav|footer|header|svg)[^>]*>.*?</\1>", "", page)
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    return f"Title: {strip_html(title.group(1)) if title else ''}\nURL: {url}\n\n{strip_html(page)}"


# --- X / Twitter -------------------------------------------------------------

def fx_text(t):
    parts = [f"@{t['author']['screen_name']} ({t['author'].get('name')}), {t.get('created_at')}",
             t.get("text") or ""]
    art = t.get("article")
    if art:
        parts.append(f"ARTICLE: {art.get('title', '')}\n{art.get('preview_text') or art.get('content') or ''}")
    if t.get("quote"):
        q = t["quote"]
        parts.append(f"QUOTING @{q['author']['screen_name']}: {q.get('text')}")
    links = re.findall(r"https?://\S+", t.get("text") or "")
    if links:
        parts.append("LINKS: " + " ".join(links))
    return "\n".join(p for p in parts if p)


def x_fxtwitter(tid):
    d = json.loads(http(f"https://api.fxtwitter.com/2/thread/{tid}"))
    if d.get("code") != 200:
        raise ValueError(f"fxtwitter code {d.get('code')}")
    posts = d.get("thread") or [d["status"]]
    if d["status"]["id"] not in {p["id"] for p in posts}:
        posts = [d["status"]] + posts
    s = d["status"]
    head = f"X post by @{s['author']['screen_name']}, {s.get('likes')} likes, {s.get('views')} views\n"
    return head + "\n\n---\n\n".join(fx_text(p) for p in posts)


def x_api(tid):
    if not X_KEY.exists():
        raise ValueError("no X API key")
    h = {"Authorization": f"Bearer {X_KEY.read_text().strip()}"}
    d = json.loads(http(f"https://api.twitter.com/2/tweets/{tid}?expansions=author_id"
                        "&tweet.fields=text,created_at,conversation_id,note_tweet&user.fields=username", h))
    t = d["data"]
    return (t.get("note_tweet") or {}).get("text") or t["text"]


def x_cli(tid):
    if not shutil.which("twitter") or not os.environ.get("TWITTER_AUTH_TOKEN"):
        raise ValueError("twitter-cli not set up")
    r = run(["twitter", "tweet", tid])
    if r.returncode:
        raise ValueError(r.stderr[-200:])
    return r.stdout


def do_x(url, out):
    m = re.search(r"/status(?:es)?/(\d+)", url)
    if not m:
        return chain(out, "x-page", [("jina", lambda: jina(url))])
    tid = m.group(1)
    chain(out, f"x-{tid}", [("fxtwitter thread", lambda: x_fxtwitter(tid)),
                            ("X API", lambda: x_api(tid)), ("twitter-cli", lambda: x_cli(tid))])


# --- Reddit ------------------------------------------------------------------

def reddit_rss(url):
    u = urllib.parse.urlsplit(url)
    feed = f"https://www.reddit.com{u.path.rstrip('/')}/.rss?limit=100"
    for i in range(3):
        try:
            xml = http(feed)
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == 2:
                raise
            time.sleep(10 * (i + 1))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml)
    rows = []
    for e in root.findall("a:entry", ns):
        who = e.findtext("a:author/a:name", "", ns)
        title = e.findtext("a:title", "", ns)
        body = strip_html(e.findtext("a:content", "", ns))
        rows.append(f"{who}: {title}\n{body}")
    if not rows:
        raise ValueError("empty feed")
    label = "POST, then top comments" if "/comments/" in u.path else "LISTING"
    return f"Reddit {u.path} ({label})\n\n" + "\n\n---\n\n".join(rows)


def reddit_opencli(url):
    if not shutil.which("opencli"):
        raise ValueError("opencli not installed")
    r = run(["opencli", "reddit", "read", url, "-f", "yaml"])
    if r.returncode:
        raise ValueError(r.stderr[-200:])
    return r.stdout


def reddit_rdt(url):
    if not shutil.which("rdt"):
        raise ValueError("rdt not installed")
    r = run(["rdt", "read", url])
    if r.returncode:
        raise ValueError(r.stderr[-200:])
    return r.stdout


def do_reddit(url, out):
    pid = re.search(r"/comments/(\w+)", url)
    chain(out, f"reddit-{pid.group(1) if pid else 'page'}",
          [("reddit rss", lambda: reddit_rss(url)), ("opencli", lambda: reddit_opencli(url)),
           ("rdt-cli", lambda: reddit_rdt(url))])


# --- GitHub ------------------------------------------------------------------

def gh(url):
    if not shutil.which("gh"):
        raise ValueError("gh not installed")
    p = urllib.parse.urlsplit(url).path.strip("/").split("/")
    if len(p) < 2:
        raise ValueError("not a repo URL")
    repo = f"{p[0]}/{p[1]}"
    if len(p) >= 4 and p[2] in ("issues", "pull"):
        kind = "issue" if p[2] == "issues" else "pr"
        r = run(["gh", kind, "view", p[3], "-R", repo, "--comments"])
    else:
        r = run(["gh", "repo", "view", repo])
    if r.returncode:
        raise ValueError(r.stderr[-200:])
    return r.stdout


def do_github(url, out):
    name = "gh-" + "-".join(urllib.parse.urlsplit(url).path.strip("/").split("/")[:4])
    blob = "/blob/" in url or "/tree/" in url
    routes = [("jina", lambda: jina(url))] if blob else [("gh cli", lambda: gh(url)), ("jina", lambda: jina(url))]
    chain(out, name, routes)


# --- LinkedIn ------------------------------------------------------------------

def do_linkedin(url, out):
    try:
        chain(out, "linkedin", [("jina", lambda: jina(url))])
    except RuntimeError as e:
        # No tool reads LinkedIn posts without a login (Agent Reach's LinkedIn MCP covers
        # profiles, companies and jobs only), so a pasted text is the route.
        raise Blocked(f"LinkedIn blocks anonymous reads. Paste the post text. Tried: {e}")


# --- Media ---------------------------------------------------------------------

def do_media(url, out):
    r = run([sys.executable, str(HERE / "yt_transcript.py"), url, str(out)], 5400)
    sys.stdout.write(r.stdout)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-400:])


def do_social(url, out):
    """IG / TikTok / FB: the caption carries most of the post; transcribe videos too."""
    cookies = ["--cookies-from-browser", COOKIES] if COOKIES else []
    r = run(["yt-dlp", "--skip-download", "--dump-single-json", "--no-warnings", *cookies, url], 120)
    if r.returncode:
        err = next((l for l in r.stderr.splitlines() if "ERROR" in l), r.stderr.strip()[-300:])[:300]
        if re.search(r"login|cookies|rate-limit|private", err, re.I):
            hint = "" if COOKIES else " Retry with LEARN_COOKIES_BROWSER=chrome (keychain prompt, interactive runs only)."
            raise Blocked(f"{err}{hint}")
        raise RuntimeError(err)
    d = json.loads(r.stdout)
    entries = d.get("entries") or [d]
    vid = d.get("id") or "post"
    meta = out / f"{vid}.meta.txt"
    meta.write_text(f"TITLE: {d.get('title')}\nUPLOADER: {d.get('uploader') or d.get('channel')}\n"
                    f"UPLOADED: {d.get('upload_date')}\nLIKES: {d.get('like_count')}\nURL: {d.get('webpage_url') or url}\n"
                    f"ITEMS: {len(entries)} ({', '.join(sorted({e.get('ext') or '?' for e in entries}))})\n"
                    f"\nCAPTION:\n{d.get('description') or ''}\n")
    print(f"META: {meta}")
    has_video = any(e.get("duration") for e in entries)
    if has_video and len(entries) == 1:
        tr = run([sys.executable, str(HERE / "yt_transcript.py"), url, str(out)], 3600)
        if tr.returncode == 0:
            print("\n".join(l for l in tr.stdout.splitlines() if l.startswith(("ROUTE", "TRANSCRIPT"))))
            return
        print(f"NOTE: transcript failed, caption only: {tr.stderr.strip()[-200:]}")
    print("ROUTE: yt-dlp caption" + ("" if has_video else " (image post: download slides to read them)"))


# --- Main ------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("usage: fetch.py <url> [out_dir]", file=sys.stderr)
        sys.exit(1)
    url = sys.argv[1].strip()
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/learn")
    out.mkdir(parents=True, exist_ok=True)
    host = re.sub(r"^(www\.|m\.|old\.)", "", urllib.parse.urlsplit(url).netloc.lower())
    on = lambda *hs: any(host == h or host.endswith("." + h) for h in hs)  # noqa: E731
    try:
        if on("x.com", "twitter.com", "fxtwitter.com", "vxtwitter.com"):
            do_x(url, out)
        elif on("reddit.com", "redd.it"):
            do_reddit(url, out)
        elif on("github.com"):
            do_github(url, out)
        elif on("linkedin.com"):
            do_linkedin(url, out)
        elif on(*SOCIAL_VIDEO):
            do_social(url, out)
        elif on(*MEDIA_HOSTS):
            do_media(url, out)
        else:
            chain(out, re.sub(r"[^\w.-]+", "-", host + urllib.parse.urlsplit(url).path)[:80].strip("-"),
                  [("jina", lambda: jina(url)), ("direct", lambda: direct(url))])
    except Blocked as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
