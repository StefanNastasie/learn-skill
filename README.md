# /learn

A [Claude Code](https://claude.com/claude-code) skill that turns any link into notes you'll actually use.

Paste a YouTube video, an X thread, a Reddit post, a podcast, a GitHub repo or an article. `/learn` fetches the full content (transcribing videos locally when there are no captions), pulls out the core idea, key insights, frameworks and quotes, says how it applies to *your* work, and files it in a categorized markdown knowledge base on your machine.

```
/learn https://www.youtube.com/watch?v=...
/learn https://x.com/someone/status/...
/learn https://www.reddit.com/r/ClaudeAI/comments/...
/learn [pasted text]
```

What you get back:

```
Saved: [title of the video]
Filed under: AI trends, Implementation ideas
Tags: claude-code, agents, workflows

Core idea: ...
Top insight: ...
Apply now: ...
```

And in `~/.claude/knowledge/`, one markdown file per category with every entry in full, plus an `INDEX.md`.

## Why it's different from "summarise this link"

- **It gets the real content.** One router script picks the right route per platform and falls back when one fails: captions or local Whisper for video, the whole author thread for X, post plus top comments for Reddit, README plus issues for GitHub. No paid APIs needed.
- **It knows who you are.** A short `CONTEXT.md` (your work, your projects) makes every "Applications" line specific to you.
- **It compounds.** Entries land in plain markdown files you own. Point your `CLAUDE.md` at the index and every Claude session can draw on what you've learned.
- **It's cheap.** It runs as a forked Sonnet subagent, so it doesn't fill your main conversation.

## Install

```bash
git clone https://github.com/StefanNastasie/learn-skill ~/.claude/skills/learn
cp ~/.claude/skills/learn/CONTEXT.example.md ~/.claude/skills/learn/CONTEXT.md
```

Then edit `CONTEXT.md`: a few lines about who you are and what you're working on. That's it, `/learn` is available in every Claude Code session.

### Dependencies

Articles, X, Reddit and pasted text work with just Python 3. For the rest:

| For | Install (macOS) |
|---|---|
| Video and podcasts | `brew install yt-dlp ffmpeg` |
| Videos without captions (local transcription) | `brew install whisper-cpp`, then download a model (below) |
| GitHub links | `brew install gh` and `gh auth login` |

Whisper model (about 1.6 GB, runs fully offline):

```bash
mkdir -p ~/.local/share/whisper
curl -L -o ~/.local/share/whisper/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
```

Use a different model by setting `WHISPER_MODEL=/path/to/model.bin`.

On Linux, install the same tools with your package manager (or `pipx install yt-dlp`, and build [whisper.cpp](https://github.com/ggerganov/whisper.cpp)).

## Platforms

| Platform | How |
|---|---|
| YouTube, Vimeo, Loom, TED, Apple Podcasts, SoundCloud, Twitch (and ~1,800 more) | captions, else audio + local Whisper |
| Instagram, TikTok, Facebook | caption + transcript (Instagram and Facebook need `LEARN_COOKIES_BROWSER=chrome`) |
| X / Twitter | fxtwitter thread API, free |
| Reddit | RSS (post + comments) |
| GitHub | gh CLI |
| Articles, blogs, Substack, PDFs | Jina Reader, then direct fetch |
| LinkedIn | blocked anonymously, so paste the text |

More detail and optional unlocks in [PLATFORMS.md](PLATFORMS.md). You can also run the fetcher on its own:

```bash
python3 ~/.claude/skills/learn/scripts/fetch.py "https://..." /tmp/learn
```

## Customise

- **Categories**: list your own in `CONTEXT.md`, or edit Step 4 of `SKILL.md`.
- **Where notes go**: `KB_DIR` in `CONTEXT.md` (default `~/.claude/knowledge/`). Put it inside an Obsidian vault if you use one.
- **The template**: Step 3 of `SKILL.md`.

Update with `git -C ~/.claude/skills/learn pull`. Your `CONTEXT.md` is git-ignored and stays put.

## Credits

Platform routes follow the pattern from [Agent Reach](https://github.com/Panniantong/Agent-Reach). Transcription by [whisper.cpp](https://github.com/ggerganov/whisper.cpp), downloads by [yt-dlp](https://github.com/yt-dlp/yt-dlp), article extraction by [Jina Reader](https://jina.ai/reader).

Made by Stefan Tei at [Tiliaris](https://tiliaris.io), hands-on AI training for small and medium teams. I use this every day to keep up with AI. Free to use, MIT licensed.
