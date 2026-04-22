# Claude Chats - Project Reference

## Overview

A Flask + SQLite + vanilla JS single-page app for searching, browsing, and organizing Claude Code chat transcripts. It indexes JSONL transcript files from `~/.claude/projects/` into a SQLite FTS5 database and provides a web UI at `localhost:5111`.

## Tech Stack

- **Backend**: Python Flask (`app.py`), SQLite with FTS5
- **Frontend**: Single HTML file (`templates/index.html`) with inline CSS and vanilla JS
- **Indexer**: `indexer.py` - parses JSONL transcripts into SQLite
- **No build step, no frontend framework, no external JS/CSS dependencies**

## File Structure

```
app.py                 # Flask server - all API routes
indexer.py             # JSONL parser + SQLite FTS5 indexer
templates/index.html   # Entire frontend (HTML + CSS + JS, ~900 lines)
transcripts.db         # SQLite database (generated, gitignored)
requirements.txt       # Python dependencies
```

## Database Schema

### Tables
- **messages** - Individual human messages (uuid, session_id, project, timestamp, content, cwd, git_branch, jsonl_file)
- **messages_fts** - FTS5 virtual table over messages (content, project)
- **sessions** - Aggregated session info (session_id, project, first_ts, last_ts, message_count, file_missing 0/1)
- **session_meta** - Per-session metadata (session_id, starred 0-5, archived 0/1, hidden 0/1)
- **session_tags** - Many-to-many session tags (session_id, tag)
- **index_meta** - Tracks which JSONL files have been indexed and their mtimes

### Key indexes
- `idx_messages_session`, `idx_messages_project`, `idx_messages_timestamp`
- `idx_session_tags_tag`, `idx_session_tags_session`

## API Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Serves the SPA |
| `/api/search?q=&project=&from=&to=&starred=&min_stars=&tag=&page=` | GET | FTS search with filters, paginated |
| `/api/projects` | GET | List all projects with counts, ordered by last_ts DESC |
| `/api/sessions?project=&archived=&starred=&min_stars=&tag=&sort=` | GET | Sessions list. `project` supports comma-separated multi-select. Sort: date_desc/date_asc/stars_desc/stars_asc |
| `/api/session/<id>` | GET | All messages in a session |
| `/api/session/<id>/meta` | GET | Starred/archived/tags for a session |
| `/api/session/<id>/star` | PUT | Set star rating (body: `{rating: 0-5}`) |
| `/api/session/<id>/archive` | PUT | Toggle archived flag |
| `/api/session/<id>/tags` | PUT | Replace tags (body: `{tags: [...]}`) |
| `/api/session/<id>/hide` | PUT | Soft-delete (set hidden=1) |
| `/api/session/<id>/unhide` | PUT | Restore a hidden session |
| `/api/tags` | GET | All tags with counts |
| `/api/timeline?granularity=day|week` | GET | Message counts by period and project |
| `/api/stats` | GET | Aggregate statistics |
| `/api/deleted?project=&starred=&min_stars=&tag=&sort=` | GET | List hidden/deleted sessions (same filters as /api/sessions) |
| `/api/deleted/projects` | GET | Projects that have at least one hidden session |
| `/api/reindex` | POST | Re-index transcripts |
| `/api/dashboard` | GET | Live session status. Returns `{active, recently_closed, generated_at}`. Reads in-memory state populated by Claude Code hooks — not from the DB. |
| `/api/hook/session-start` | POST | Hook endpoint: Claude Code `SessionStart`. Inserts/updates session, state=`waiting`. Accepts JSON body with `session_id` and `cwd`. |
| `/api/hook/user-prompt-submit` | POST | Hook endpoint: Claude Code `UserPromptSubmit`. Sets state=`working`. |
| `/api/hook/stop` | POST | Hook endpoint: Claude Code `Stop`. Sets state=`waiting`. |
| `/api/hook/session-end` | POST | Hook endpoint: Claude Code `SessionEnd`. Moves session to `recently_closed` (bounded to 5 most recent). |

## Frontend Architecture

### Views (tabs)
1. **Dashboard** (default) - Live view of currently-running Claude Code sessions, grouped by state (working / waiting / recently closed). Populated by Claude Code hooks POSTing to `/api/hook/*`. Auto-refreshes every 5s while visible; polling stops when switching views. In-memory only — resets when Flask restarts.
2. **Search** - FTS search with project/date/star/tag filters, paginated results
3. **Browse** - Left sidebar with project list (multi-select), right panel shows sessions
4. **Timeline** - Stacked bar chart of messages over time by project
5. **Stats** - Summary cards and tables
6. **Deleted** - Browse/restore soft-deleted (hidden) sessions, same sidebar+filters layout as Browse

### Key State Variables (Dashboard view)
- `dashTimer` - setInterval handle for auto-refresh (5s). Cleared when leaving the view.
- Server-side: `_live_sessions` (dict, session_id → {state, cwd, project, started_at, updated_at}) and `_recently_closed` (list, capped at 5). Guarded by `_live_lock`. In-memory; not persisted.

### Key State Variables (Browse view)
- `browseSelectedProjects` (Set) - Currently selected projects
- `browseAllProjects` (Array) - Cached project list from API
- `browseSortProjects` ('chrono' | 'alpha') - Sidebar sort order
- `browseShowArchived`, `browseStarredOnly`, `browseMinStars`, `browseTagFilter`, `browseSort` - Session filters
- `browseLastViewedSession` - Session ID to scroll back to after returning from detail view

### Key State Variables (Deleted view)
- `deletedSelectedProjects` (Set), `deletedAllProjects` (Array), `deletedSortProjects` - Mirror browse sidebar state
- `deletedStarredOnly`, `deletedMinStars`, `deletedTagFilter`, `deletedSort` - Session filters

### Key Functions
- `loadProjects()` - Fetches projects, stores in `browseAllProjects`, calls `renderProjectSidebar()`
- `renderProjectSidebar()` - Renders sidebar with toolbar (Select All, Clear, sort dropdown) and project list
- `toggleProject(name)` - Toggle a project in/out of selection
- `selectAllProjects()` / `clearProjectSelection()` - Bulk selection
- `loadBrowseSessions()` - Fetches and renders sessions for all selected projects
- `showSession(id)` - Shows full message list for a session
- `hideSession(id)` - Soft-delete a session (sets hidden=1, removes from all views except Deleted)
- `loadDeletedProjects()` / `renderDeletedSidebar()` / `loadDeletedSessions()` - Deleted view equivalents of browse
- `undeleteSession(id)` - Restore a hidden session (sets hidden=0)
- `showDeletedSession(id)` - View messages of a deleted session
- `renderStars(sessionId, rating, containerId)` - Star rating widget (1-5)
- `renderTagChips(tags, sessionId, editable)` - Tag pills with inline add/remove
- `esc(s)` - HTML-escapes text (use `JSON.stringify` for onclick attributes to avoid XSS)

### CSS
- Dark theme using CSS custom properties (`:root` vars)
- Monospace font throughout
- Key colors: `--bg` dark navy, `--green` teal accent, `--accent` red, `--yellow` star color

## Patterns and Conventions

- **No framework** - All DOM manipulation is innerHTML-based string templates
- **Global state** - State lives in top-level `let` variables, no state management library
- **Inline event handlers** - `onclick`, `onchange` etc. in HTML strings
- **XSS safety** - Use `esc()` for text content, `JSON.stringify()` for values in onclick attributes
- **API style** - Simple REST, JSON responses, query params for filters
- **SQL safety** - Parameterized queries with `?` placeholders everywhere
- **Session meta** - Stars/archives/tags/hidden are stored separately from indexed data (survive reindex)
- **Hidden sessions** - Filtered out via `NOT EXISTS` subqueries in all read endpoints; only shown in `/api/deleted`

## Running

```bash
pip install -r requirements.txt
python app.py
# Runs initial index, then serves at http://localhost:5111

# Stop the process already running on port 5111
lsof -ti:5111 | xargs kill
```

## Data Source

Transcripts come from `~/.claude/projects/` where each subfolder is a project (encoded path like `-Users-julie-projects-myproject`) containing `.jsonl` files. The indexer decodes folder names back to readable project paths and extracts only human-typed messages (type=user, has permissionMode, not meta, not tool-sourced).
