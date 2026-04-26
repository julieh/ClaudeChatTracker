# ClaudeChatTracker

**Never lose a Claude Code conversation again.** A local web app that indexes, searches, and organizes every Claude Code session — from both the CLI *and* the Desktop app — so the prompt you wrote last month is one search away.

`Python 3.8+` · `Flask` · `SQLite FTS5` · `100% local`

<!-- TODO: add a screenshot of the Browse view here -->
<!-- ![Browse view](00ai/screenshot-browse.png) -->

---

## Sound familiar?

> *"Where's that great prompt I wrote last Tuesday?"*
> → Full-text search across **every message you've ever typed** to Claude Code.

> *"My best code-analysis prompts are scattered across half a dozen projects — I have no idea where I put them."*
> → **Tag the keepers** as you go (`code-review`, `refactor`, `debugging`) and pull up every tagged session across every project with one click — no matter which repo you originally ran it in.

> *"Which of these 14 sessions still needs my attention?"*
> → Mark sessions **Open** or **Complete**. Filter to just the ones that aren't done.

> *"I had a brilliant conversation from last month — and now Claude's cleanup wiped it."*
> → ClaudeChatTracker keeps its own copy. When the JSONL disappears from `~/.claude/projects/`, your transcript is still right here.

> *"I have 6 Claude sessions running right now — what's each one doing?"*
> → Optional live **Dashboard** shows what's *Working*, what's *Waiting* on you, and what just *Closed*.

> *"I wish I could star the good ones and forget the throwaway ones."*
> → 1–5 star ratings, free-form tags, and a soft-delete tab that's always recoverable.

---

## Features

### 🔎 Find
- **Full-text search** across every prompt and response (SQLite FTS5)
- **Filter** by date range, project, tag, or minimum star rating
- Press **`/`** anywhere to jump to search
- Click a result to see the full session, with a copy-ready `/resume` command

### 🗂️ Organize
- **Star** sessions 1–5 — granular curation, not just bookmark/no-bookmark
- **Tag** anything with autocomplete from your existing tags
- **Open / Complete** checkbox so you stop forgetting work-in-progress
- **Archive** to declutter without losing data
- **Soft-delete** — the "Deleted" tab keeps everything recoverable

### 📊 Survey
- **Browse** by project — single project, several, or everything at once
- **Timeline** — stacked bar chart of messages per day, color-coded by project
- **Stats** — top-level counts plus your most active days and projects
- **Live Dashboard** *(optional)* — see Claude Code sessions running right now: Working, Waiting, Recently Closed
- **Backup** — one-click snapshot of your database to `~/claudeChatBackups/`

---

## Getting Started

### Easy path (recommended — works for non-technical users)

1. Clone this repo using your favorite Git client (mine is https://fork.dev/)
2. Open the **Code tab** in Claude Desktop → **New Session** → select the cloned folder
3. Paste this prompt:
   ```
   Follow instructions in 00ai/SetupInstructionsForClaude.md
   ```

That's it. Claude will check Python, install dependencies, start the app, and walk you through it one step at a time. About 5 minutes.

### Manual path (for developers)

```bash
git clone git@github.com:julieh/ClaudeChatTracker.git
cd ClaudeChatTracker
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5111**.

First launch indexes all your transcripts (30–60s for large histories). After that, re-indexing is incremental — only changed files.

---

## Optional: Live Dashboard

The Dashboard view shows which Claude Code sessions are running right now and what state they're in. It's powered by four lightweight Claude Code hooks that fire-and-forget a `localhost` ping on session events.

- **Everything else (Search, Browse, Timeline, Stats) works fine without it.**
- The setup script (Step 6 of `00ai/SetupInstructionsForClaude.md`) installs the hooks safely: it backs up your `settings.json` first, validates the result, and auto-restores if anything goes wrong.

If you don't want it, just say "skip" when the setup prompts you.

---

## Your data stays local

ClaudeChatTracker runs entirely on your machine. It reads JSONL transcripts from `~/.claude/projects/`, writes to a local `transcripts.db`, and serves on `localhost:5111` only. **Nothing is sent anywhere.**

---

## Tech

Flask · SQLite + FTS5 · single-file vanilla-JS SPA (no bundler, no build step). Two Python files, one HTML template — easy to read, easy to hack on.

## Updating

```bash
git pull
python app.py
```

Schema migrations and re-indexing happen automatically.
