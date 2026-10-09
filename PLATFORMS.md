# Platform access

`scripts/fetch.py` routes every link. The routes follow
[Agent Reach](https://github.com/Panniantong/Agent-Reach): each platform has an
ordered backend list, and switching paths means reordering the list in its
`chain(...)` call.

## Works with no login

| Platform | Backend |
|---|---|
| YouTube and ~1,800 yt-dlp sites | yt-dlp captions, else local whisper.cpp |
| TikTok | yt-dlp caption + whisper |
| X / Twitter | api.fxtwitter.com (thread endpoint); X API bearer key as backup (paid per call) |
| Reddit | `<post-url>/.rss` (post + comments). JSON and api.reddit.com answer 403. RSS rate-limits after many hits; the script backs off |
| GitHub | gh CLI |
| Articles, PDFs, docs | Jina Reader (`r.jina.ai`) > direct fetch |

## Optional unlocks

| Platform | Unlock | Notes |
|---|---|---|
| Instagram, Facebook | `LEARN_COOKIES_BROWSER=chrome` per run | Borrows your Chrome cookies; macOS asks for the keychain, so interactive runs only |
| X API fallback | Bearer token in `~/.claude/x-api-key` | Only used when fxtwitter fails. Paid per call |
| Reddit (full) | [OpenCLI](https://www.npmjs.com/package/@jackwener/opencli) on PATH, plus its Chrome extension | Rides your logged-in Chrome session. Consider a secondary account |
| X search and timelines | twitter-cli + `TWITTER_AUTH_TOKEN` / `TWITTER_CT0` cookies | Only needed beyond single posts and threads |
| LinkedIn posts | none: paste the text | Anonymous access is almost always blocked |

## When a route dies

Platforms change. Debug `fetch.py` first, check how Agent Reach handles that
platform now (`agent_reach/channels/<platform>.py`), then reorder or add a
backend in the platform's `chain(...)`.
