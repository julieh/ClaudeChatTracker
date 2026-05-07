# Claude Chats — Features

A skim-friendly reference for everything this app does. If you've forgotten
what a button is for, you should be able to find it in here in under a minute.

For setup instructions, see [`00ai/SetupInstructionsForClaude.md`](00ai/SetupInstructionsForClaude.md).
For Slack-token setup specifically, see the *Slack sync (optional)* section in
[`README.md`](README.md).

---

## What this is

A Flask single-page app that runs locally at <http://localhost:5111>. It
indexes the JSONL transcripts Claude Code writes under `~/.claude/projects/`
into a SQLite FTS5 database so you can search, browse, rate, tag, and export
your past conversations — long after Claude Code has rotated the original
files off disk.

Everything is local: nothing is sent anywhere. Optional Slack sync (read-only)
brings your own Slack messages into the same DB so the timesheet export can
include them.

---

## The six views (tabs)

The tab bar runs across the top. Tabs in order: **Dashboard, Search, Browse,
Timeline, Stats, Deleted**. Dashboard is the default.

### Dashboard

Live view of which Claude Code sessions are running right now. Three sections:

- **Working** (green pulsing dot) — Claude is currently doing something.
- **Waiting for you** (yellow dot) — Claude finished its turn; the ball is in your court.
- **Recently closed** (gray dot) — last 10 sessions that ended.

Auto-refreshes every 5 seconds while you're on the tab. Per-card actions:

- **Browse ↗** — jump to that session in Browse.
- **▸ Expand transcript** — inline expand the full conversation (up to 400px tall, scrollable).
- **✕** — dismiss the card (doesn't delete the session, just removes it from the live list).
- **Refresh** button at top — manually re-scans `~/.claude/projects/` to pick up sessions started before the server was running.

Populated by Claude Code hooks (set up via [`SetupInstructionsForClaude.md`](00ai/SetupInstructionsForClaude.md)
Step 6). Without hooks, the dashboard falls back to a 24-hour disk scan of
`~/.claude/projects/` at server startup.

### Search

Full-text search across **both** what you typed and what Claude said back.
Matches are highlighted inline with `<mark>`.

Filters (stack as many as you want):

- Project dropdown
- Date range (From / To)
- Tag dropdown
- Starred-only toggle
- Min stars (1+, 2+, …, 5)
- Reset button to clear all

Filter-only search works — you don't need a query if you have at least one
filter active. 20 results per page; Prev / Next.

Per-result card: star widget, project, git branch, timestamp, your message
snippet, the matching Claude snippet (if any), tag chips, Copy button, and a
View-session link that drops you into the full conversation.

### Browse

The home view for organizing. Project sidebar on the left, sessions on the right.

**Sidebar:**

- Single-click a project to focus only that one.
- Cmd/Ctrl-click to multi-select (or use **Select All** / **Clear**).
- Sort: Recent first or A → Z.

**Filter bar (top of right pane):**

- **Open / Complete / All** — `Open` is the default and shows only sessions you haven't marked done. The driver of day-to-day use.
- Starred-only toggle, Min stars dropdown
- Sort: Newest, Oldest, Most stars, Fewest stars
- Show archived toggle
- Tag dropdown

**Session card:** message count, first-message preview, project (when
multi-project), date range, star widget, Complete checkbox (top right), tag
chips, **Show Last** toggle (reveals last message on hover), Archive button,
Delete button.

A **dashed border** + 🚫 icon means the source JSONL has been deleted from
disk by Claude Code's rotation — but the transcript is still here.

Clicking a card opens the full session detail (see *Per-session features*).

### Timeline

Stacked bar chart of message volume over time, colored by project.

- Granularity dropdown: **Daily** or **Weekly**.
- Hover a bar segment → tooltip with project + count.
- Hover a legend item → bars from other projects fade so you can isolate one project.

### Stats

Three big numbers at the top (total messages, total sessions, total projects),
then a per-project table and a most-active-days table. Static; no filters.

### Deleted

Same layout as Browse but for soft-deleted sessions. Session cards show an
**Undelete** button that restores them to Browse. Tag chips are read-only here.

---

## Per-session features

These are available inside both Browse-session-detail and Search-result clicks.

- **5-star rating** — click a star to rate. Click the **same** star again to clear it.
- **Tag chips** — purple pills. Click `x` to remove. Type into the dashed `+tag` input to add (Enter commits, Esc cancels). Autocomplete shows the top 8 existing tags.
- **Open / Complete checkbox** — yellow square in the top-right of cards and inline in the detail header. Default is Open. Mark Complete when the task is done; Browse's Open filter then hides it. Click the gray check to reopen.
- **Soft-delete** — the **Delete** button hides the session from every view except *Deleted*. Restore from the Deleted tab.
- **Archive** — lighter than delete. Hides from Browse unless **Show archived** is on. (Does not move the session to Deleted.)
- **`/resume <session-id>` block** — a code box in the session detail header with a Copy button. Paste into Claude Code to drop right back into that conversation.
- **Copy** button on each user message — copies the full original prompt.
- **Collapsible You / Claude blocks** — click the role label or caret to fold a long message.

Per-session metadata (stars, tags, complete, archived, hidden) lives in
`session_meta` / `session_tags` and **survives reindex** — you won't lose
ratings or tags by clicking Reindex.

---

## Top-bar buttons

### Reindex

Re-scans `~/.claude/projects/` for any JSONL files that have changed since the
last indexing run. Incremental and cheap (compares disk mtimes against
`index_meta`); safe to click whenever you suspect new conversations haven't
shown up yet.

### Backup

Copies `transcripts.db` to `~/claudeChatBackups/<YYYY-MM-DD-HHMM>_transcripts.db`.
A modal confirms the path. No retention policy — old backups stay until you
delete them.

### Sync Slack

Pulls **only your own** Slack messages into the local `slack_messages` table.
First run goes back 30 days; subsequent runs are incremental from
`slack_sync_meta.last_sync_ts`. Other people's messages are dropped server-
side before they ever touch SQLite.

Disabled (grayed out) if `SLACK_USER_TOKEN` isn't set — see [`README.md`](README.md)
for how to create the token. The token has read-only scopes; no code path in
this repo calls a write API.

A 5-minute soft timeout means very large backfills may finish in two clicks
(button shows `partial` then `Synced N new`).

### Dump Timesheet

Exports the **last 4 New York-local calendar days** (today + 3 prior) of your
messages — both Claude prompts **and** synced Slack messages — to:

- `00ai/timedumps/<YYYY-MM-DD-HHMM>_timesheet.csv`
- `00ai/timedumps/<YYYY-MM-DD-HHMM>_timesheet.xlsx`

Columns: date, weekday, time, project, session title, session id, minutes
since previous message, human-readable gap (`2h 15m`), char count, message
text. The XLSX color-codes rows by project and includes a *Project Colors*
legend sheet.

Internal system noise (`<task-notification>`, `<local-command-stdout>`,
`<bash-stdout>`) is filtered out.

### Kill Process

Confirms, then shuts down the Flask server (kills whatever is listening on
port 5111). Use this when you'd otherwise be hunting for the terminal it's
running in.

---

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `/` | Focus the search input (works from any view, except inside form fields) |
| Enter (in tag input) | Commit the tag |
| Esc (in tag input) | Cancel and clear the tag input |

---

## Keeping the data up to date

Four separate sync mechanisms. Listed in the order you'll use them.

### 1. Claude transcripts (the main index)

- **Automatic on app startup.** Incremental — only re-parses JSONL files whose mtime has changed.
- **Manual refresh:** click **Reindex** in the top bar.
- **From the CLI:** `python indexer.py` (incremental) or `python indexer.py --full` (full rebuild — wipes `messages` and `index_meta`, re-parses every file). You'd want `--full` after pulling a schema change, or if you suspect the index is corrupt.
- **What gets indexed:** human-typed messages and `/slash-commands`. Each human message is stored alongside the next assistant response as `assistant_response` so search can match Claude's text too.

### 2. Live Dashboard

- **Hooks (recommended):** if you set up the four hooks in `~/.claude/settings.json` (see [`SetupInstructionsForClaude.md`](00ai/SetupInstructionsForClaude.md) Step 6), every Claude Code session sends `SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd` pings to localhost. The dashboard reflects them in near-real-time.
- **Disk-scan fallback:** dashboard state is in-memory only, so a server restart wipes it. On startup the app does a 24-hour scan of `~/.claude/projects/` to repopulate Active and Recently Closed from JSONL mtimes (sessions idle > 5 minutes are treated as closed).
- **Manual repopulate:** click **Refresh** on the Dashboard tab to re-run the disk scan.

### 3. Slack messages

- **Manual only:** click **Sync Slack** when you want fresh Slack data.
- **First run** pulls the past 30 days. **Subsequent runs** pull only since `slack_sync_meta.last_sync_ts`.
- **To backfill more history,** open `transcripts.db` and either delete the `last_sync_ts` row from `slack_sync_meta` (resets to 30-day default) or set it to an earlier Slack `ts` value.
- **Token:** requires `SLACK_USER_TOKEN=xoxp-...` in the environment when you launch `python app.py`. If unset, the button is disabled but everything else still works.

### 4. Backups

- **Manual only:** click **Backup**. There's no scheduler.
- Backups are timestamped, so multiple in one day are fine.
- Cleanup is manual: delete files in `~/claudeChatBackups/` when you no longer want them.

---

## Where things live on disk

| Path | What it is |
|------|-----------|
| `~/.claude/projects/*/*.jsonl` | Claude Code transcripts. Source of truth — Claude rotates these off disk over time. |
| `~/.claude/sessions/*.json` | Terminal-window session names. Read-only by this app, used for friendly labels. |
| `~/.claude/settings.json` | Where the optional Dashboard hooks are installed. |
| `transcripts.db` (in this repo) | The app's SQLite index. Gitignored. |
| `~/claudeChatBackups/` | Output of the Backup button. |
| `00ai/timedumps/` | Output of the Dump Timesheet button. |
