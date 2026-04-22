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
