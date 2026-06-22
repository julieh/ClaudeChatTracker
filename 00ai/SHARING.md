# Sharing Claude Chats App

## For the sender (Julie)

1. Make sure you're in the project directory:
   ```bash
   cd ~/claudechats
   ```

2. Create a zip that includes the git history but excludes generated files:
   ```bash
   zip -r claudechats.zip . -x "transcripts.db" "__pycache__/*" "*.pyc" ".DS_Store" "00ai/*"
   ```

3. Send `claudechats.zip` to your teammate however you like (Slack, email, etc.).

## For the recipient (teammate)

### Prerequisites

- Python 3.10+ (check with `python3 --version`)
- Flask (`pip3 install flask`)

### Setup

1. Unzip the file:
   ```bash
   unzip claudechats.zip -d claudechats
   cd claudechats
   ```

2. Verify git history is intact:
   ```bash
   git log --oneline
   ```

3. Run the app:
   ```bash
   python3 app.py
   ```

4. Open http://localhost:5111 in your browser.

### What to expect

- On first run, the app indexes your local Claude Code transcripts from `~/.claude/projects/`.
- Each person sees **their own** conversation history — the data is not shared, only the app is.
- The SQLite database (`transcripts.db`) is generated locally and excluded from git.
- Subsequent runs re-index incrementally (only new/changed files).

### Optional: Enable live Dashboard

The Dashboard view shows which of your Claude Code sessions are currently **working** vs **waiting for input**. It's populated by Claude Code hooks that fire-and-forget a localhost POST on session events. Hooks are per-session or per-turn (never per-tool), and run detached with a 1-second timeout — they won't slow your Claude sessions down or stall them if the Flask app is stopped.

Add this to `~/.claude/settings.json` (merge with existing `hooks` if you have them):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "curl -s --max-time 1 -X POST http://localhost:5111/api/hook/session-start -H 'Content-Type: application/json' -d \"$CLAUDE_HOOK_JSON\" >/dev/null 2>&1 &"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "curl -s --max-time 1 -X POST http://localhost:5111/api/hook/user-prompt-submit -H 'Content-Type: application/json' -d \"$CLAUDE_HOOK_JSON\" >/dev/null 2>&1 &"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "curl -s --max-time 1 -X POST http://localhost:5111/api/hook/stop -H 'Content-Type: application/json' -d \"$CLAUDE_HOOK_JSON\" >/dev/null 2>&1 &"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "curl -s --max-time 1 -X POST http://localhost:5111/api/hook/session-end -H 'Content-Type: application/json' -d \"$CLAUDE_HOOK_JSON\" >/dev/null 2>&1 &"
          }
        ]
      }
    ]
  }
}
```

Restart (or start new) Claude Code sessions to pick up the hooks. The Dashboard only reflects sessions that started after hooks were installed.

**Why these specific hooks?** `SessionStart` and `SessionEnd` bracket a session; `UserPromptSubmit` means "Claude is now working"; `Stop` means "Claude finished its response, back to waiting." `PreToolUse`/`PostToolUse` are deliberately not used — they fire on every tool call and would add cumulative latency.

**Disabling:** just remove the hook entries from `~/.claude/settings.json`. The app continues to work; the Dashboard will simply show no live sessions.

### Troubleshooting

- **"No module named flask"** — Run `pip3 install flask`.
- **No sessions showing up** — Make sure you have Claude Code transcripts in `~/.claude/projects/`. The app only indexes JSONL files from that directory.
- **Port 5111 in use** — Another instance may be running. Kill it or edit the port in `app.py`.

## Updating (after git pull)

Normally: just restart `python3 app.py`. Schema migrations and re-indexing are automatic.

Manual steps are listed below, newest first. Find the entry just after your last pull and do everything from there upward.

- **2026-06-22** (a34d68c) — Claude desktop **Cowork** sessions now indexed alongside Code CLI sessions. No manual step — the `source` column migration and Cowork discovery (from the platform's Claude app-support dir — `~/Library/Application Support/Claude/local-agent-mode-sessions/` on macOS, `%APPDATA%\Claude\local-agent-mode-sessions\` on Windows, `~/.config/Claude/local-agent-mode-sessions/` on Linux) run automatically on startup/reindex. Adds a Source filter on Search and Browse, a COWORK badge on session/result rows, and a Cowork sessions stat card.
- **2026-05-01** (49245bb) — Slack sync now available. Optional. To enable, set `SLACK_USER_TOKEN=xoxp-...` before launching `python app.py` (see the *Slack sync (optional)* section in `README.md` for token + scopes). Without the env var, the Sync Slack button just stays disabled — search, browse, dashboard, timesheet (Claude rows only) all keep working. This commit also added a Kill Process button and started including Slack rows in the timesheet dump; neither needs a manual step.
- **2026-04-30** (31bc649) — Dump Timesheet button. No manual step. Output lands in `00ai/timedumps/`.
- **2026-04-22** (c7ef914) — New Dashboard view. To populate it with live sessions, add the 4 hooks from the "Optional: Enable live Dashboard" section above to `~/.claude/settings.json` and restart your Claude Code sessions. Skipping this is fine — the Dashboard just stays empty.
