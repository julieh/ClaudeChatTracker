# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Flask web app for searching and browsing Claude Code conversation transcripts. It indexes JSONL transcript files from `~/.claude/projects/` into a SQLite FTS5 database and serves a single-page UI.

For user-visible behavior (every button, every view, every sync mechanism), see `FEATURES.md`. This file focuses on architecture for someone editing the code.

## Running the app (read this first)

This app must run on the user's own machine: it reads transcripts from the local `~/.claude/projects/` and serves a browser UI at `http://localhost:5111`. It will NOT work from the Cowork tab's sandbox, which is an isolated Linux environment that cannot see the local `~/.claude` data and whose `localhost` the user's browser cannot reach.

**If the user asks to "run the app" (or similar) from the Cowork tab, do not try to start it. Instead, tell them:**

> To run this app, switch to the **Code** tab in Claude Desktop, change to this folder (`ClaudeChatTracker`), and prompt: **"run this app"**. Claude Code will ask for permission, then start the server at http://localhost:5111.

In the Code tab, running `python app.py` directly is the correct way to start it.

## Platform notes

The core app (Search, Browse, Timeline, Stats, Timesheet, Slack sync) is cross-platform — Windows, macOS, and Linux. Keep it that way: always pass `encoding="utf-8"` when opening transcript files (Windows defaults to cp1252 and chokes on non-ASCII), and use `pathlib`/the home-prefix helpers rather than hardcoded `/` path math. Two features are intentionally **macOS/Unix-only** and are documented as such: the **Kill Process** button (`/api/kill` shells out to `lsof`/`kill`) and the **live Dashboard** (its Claude Code hooks are bash `curl` commands). `COWORK_DIR` is platform-conditional (see `_cowork_dir()` in `indexer.py`).

## Commands

```bash
# Run the app (indexes on startup, serves at http://localhost:5111)
python app.py

# Re-index transcripts without starting server
python indexer.py          # incremental (only changed files)
python indexer.py --full   # full rebuild
```

## Architecture

Four Python files, one HTML template, no build step:

- **`indexer.py`** — Parses JSONL transcripts from `~/.claude/projects/*/` and populates SQLite (`transcripts.db`). Filters for human-typed messages only (`is_human_message`) plus `/slash-commands` (`is_command_message`). Maintains FTS5 index (`messages_fts`) and a `sessions` summary table. Uses `index_meta` to track file mtimes for incremental indexing. Sets `sessions.file_missing = 1` when the source JSONL has been deleted from disk. `load_session_names()` reads `~/.claude/sessions/*.json` for friendly terminal-window names.
- **`app.py`** — Flask server with REST API endpoints. Imports `run_index` and `DB_PATH` from indexer; also imports `timesheet` and `slack_sync`. All endpoints return JSON except `/` which serves the template. Holds in-memory live-Dashboard state (`_live_sessions`, `_recently_closed`, guarded by `_live_lock`); reset on every server restart and repopulated by a 24-hour disk scan in `_scan_live_from_disk()`.
- **`slack_sync.py`** — Optional read-only Slack capture. Pulls only the authenticated user's own messages into `slack_messages` since `slack_sync_meta.last_sync_ts`. First run defaults to 30 days back. Respects 429 rate limits and a 5-minute soft timeout.
- **`timesheet.py`** — CSV/XLSX export of recent messages (default: last 4 NY-local calendar days). Unions `messages` and `slack_messages`, computes per-row gap to previous message, color-codes XLSX rows by project with a *Project Colors* legend sheet. Filters out `<task-notification>`, `<local-command-stdout>`, `<bash-stdout>` rows.
- **`templates/index.html`** — Self-contained SPA (no frameworks, no bundler). All CSS, JS, and HTML in one file. Views: Dashboard, Search, Browse, Timeline, Stats, Deleted.

## Database Schema (transcripts.db)

Key tables:
- `messages` — indexed content + metadata (includes `assistant_response` so search hits Claude's text too)
- `messages_fts` — FTS5 virtual table over `messages.content` and `messages.assistant_response`
- `sessions` — aggregated per-session info (includes `name`, `slug`, `file_missing`)
- `session_meta` — per-session flags: `starred` (0–5), `archived`, `hidden`, `complete`
- `session_tags` — many-to-many tags
- `index_meta` — tracks JSONL file mtimes for incremental indexing
- `slack_messages` — user's own Slack messages (separate from `messages`; never appears in Claude search/stats)
- `slack_sync_meta` — Slack sync cursor (`last_sync_ts`)

Schema migrations are handled inline in `init_db()` via `ALTER TABLE` with exception catching.

## API Endpoints

All under `/api/`. Grouped by purpose:

- **Search / browse / detail:** `/api/search`, `/api/sessions`, `/api/projects`, `/api/session/<id>`, `/api/session/<id>/meta`, `/api/timeline`, `/api/stats`, `/api/tags`
- **Per-session mutations:** `/api/session/<id>/star`, `/archive`, `/complete`, `/hide`, `/unhide`, `/tags` (all PUT)
- **Soft-delete views:** `/api/deleted`, `/api/deleted/projects`
- **Live dashboard:** `/api/dashboard` (GET), `/api/dashboard/scan` (POST), `/api/dashboard/session/<id>/transcript` (GET), `/api/dashboard/session/<id>` (DELETE)
- **Hook ingestion:** `/api/hook/session-start`, `/user-prompt-submit`, `/stop`, `/session-end` (all POST)
- **Maintenance / export:** `/api/reindex` (POST), `/api/backup` (POST), `/api/dump-timesheet` (POST), `/api/kill` (POST)
- **Slack:** `/api/slack/status` (GET), `/api/slack/sync` (POST)

Hidden sessions are filtered out via `NOT EXISTS` subqueries throughout all read endpoints.
