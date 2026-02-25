# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Flask web app for searching and browsing Claude Code conversation transcripts. It indexes JSONL transcript files from `~/.claude/projects/` into a SQLite FTS5 database and serves a single-page UI.

## Commands

```bash
# Run the app (indexes on startup, serves at http://localhost:5111)
python app.py

# Re-index transcripts without starting server
python indexer.py          # incremental (only changed files)
python indexer.py --full   # full rebuild
```

## Architecture

Two Python files, one HTML template, no build step:

- **`indexer.py`** — Parses JSONL transcripts from `~/.claude/projects/*/` and populates SQLite (`transcripts.db`). Filters for human-typed messages only (`is_human_message`). Maintains FTS5 index (`messages_fts`) and a `sessions` summary table. Uses `index_meta` to track file mtimes for incremental indexing.
- **`app.py`** — Flask server with REST API endpoints. Imports `run_index` and `DB_PATH` from indexer. All endpoints return JSON except `/` which serves the template.
- **`templates/index.html`** — Self-contained SPA (no frameworks, no bundler). All CSS, JS, and HTML in one file. Views: Search, Browse, Timeline, Stats, Deleted.

## Database Schema (transcripts.db)

Key tables: `messages` (indexed content + metadata), `messages_fts` (FTS5 virtual table), `sessions` (aggregated per-session), `session_meta` (starred/archived/hidden flags), `session_tags` (many-to-many tags). Schema migrations are handled inline in `init_db()` via `ALTER TABLE` with exception catching.

## API Endpoints

All under `/api/`. Main ones: `/api/search` (FTS query with filters), `/api/sessions` (browse with project/star/tag/sort filters), `/api/session/<id>` (messages), `/api/session/<id>/star|archive|hide|tags` (mutations), `/api/reindex` (POST), `/api/timeline`, `/api/stats`, `/api/deleted`.

Hidden sessions are filtered out via `NOT EXISTS` subqueries throughout all read endpoints.
