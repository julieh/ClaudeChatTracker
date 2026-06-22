# Claude Chats — Setup Instructions for Claude

You are running in the Code tab of Claude Desktop, in a folder where the user
has just cloned the Claude Chats repo using Fork. The user is non-technical:
proficient at clicking and pasting in Claude Desktop, but uncomfortable with
terminals and command lines. Your job is to set up and run this Flask app for
them, walking through one step at a time.

## How to behave throughout

- **Run commands yourself** — don't ask the user to type into a terminal. They
  approve commands via the standard Claude Code permission prompts.
- **One step at a time.** After each step, tell the user what just happened in
  plain English and confirm before moving on.
- **No jargon walls.** "Installing the libraries the app needs" beats
  "running pip install against requirements.txt."
- **When something fails**, parse the error and respond specifically. If you
  genuinely can't tell what's wrong, ask the user to copy-paste exactly what
  they see on screen — including any red text.

## Pre-flight checks (do silently before greeting the user)

1. **Confirm you're in the right folder.** Look for `app.py`, `indexer.py`, and
   `requirements.txt` at the current working directory. If any are missing,
   stop and ask the user to confirm they opened the cloned repo folder itself
   (not its parent or a subfolder).
2. **Detect OS.** Use `uname -s` or check `sys.platform`. Adjust commands for
   Mac vs Windows vs Linux throughout. (`python3` on Mac/Linux; `python` on
   Windows. `pip3` on Mac/Linux; `pip` on Windows.)
3. **Note the Python command that works** — try `python3 --version` first,
   then `python --version`. Use whichever responds in all later steps.

Then greet the user briefly: "I'll get Claude Chats set up for you. About 4
quick steps, ~5 minutes. I'll handle the commands; you just confirm as we go."

---

## Step 1 — Verify Python 3 is installed

**Run:** the version command you identified above.

**Success:** output starts with `Python 3.` (3.8 or newer is fine).

**If it fails:**
- *"command not found" / "is not recognized"* — Python isn't installed (or
  isn't on PATH). Tell the user:
  - Go to https://www.python.org/downloads/
  - Click the big yellow "Download Python 3.x" button
  - **Windows only:** on the first installer screen, check the box that says
    "Add python.exe to PATH" — this is the most-missed step
  - Run the installer with all defaults
  - Quit and reopen Claude Desktop, then paste the original setup prompt to
    resume
- *Python 2.x* — tell the user to install Python 3 from python.org (same
  instructions as above).

When Python is confirmed working, tell the user the version you found, and
move on.

## Step 2 — Install the libraries the app needs

**Run:** `pip3 install -r requirements.txt` (Mac/Linux) or
`pip install -r requirements.txt` (Windows).

**Success:** output ends with `Successfully installed flask-...` or
`Requirement already satisfied: flask...`.

**If it fails:**
- *"pip: command not found"* — try `python3 -m pip install -r requirements.txt`
  (or the `python` variant on Windows).
- *Permissions error* — add `--user` to the command.
- *SSL / network / timeout error* — ask the user if they're on a corporate
  network, work VPN, or restrictive Wi-Fi. These commonly block pip. Suggest
  trying again from a different network (e.g., personal Wi-Fi or hotspot).
- *Anything else* — ask the user to paste the full error text.

## Step 3 — Start the app

**Run** `python3 app.py` (or `python app.py` on Windows) **as a background
process** using your tool environment's background-execution capability. Do
NOT run it in a way that blocks the conversation.

**Success:** within ~10 seconds, the process logs something like
`Running on http://127.0.0.1:5111`. Note: on first run the app indexes the
user's Claude Code transcripts, which can take 30-60 seconds. Mention this so
the user isn't worried by the pause.

**If it fails:**
- *"Address already in use"* — the app is already running from a previous
  session. Tell the user to just visit http://localhost:5111; it's already up.
- *ImportError / ModuleNotFoundError* — Step 2 didn't fully succeed. Re-run
  Step 2 and watch the output carefully for errors.
- *Any other crash* — ask the user to paste the full traceback, then diagnose.

## Step 4 — Confirm the user can see it

Tell the user to open their web browser and visit **http://localhost:5111**.

Ask: "Do you see the Claude Chats search interface?"

- **Yes:** great — move on.
- **No, "site can't be reached":** the app isn't actually running. Check
  whether your background process is still alive; if it died, restart it and
  inspect the output for an error.
- **Yes but it looks empty / no sessions:** that's normal if the user has few
  Claude Code transcripts, or if the indexer is still running. Wait 30-60
  seconds and have them refresh.

## Step 5 — Teach stop / start

Briefly explain:

- **To stop the app:** if you (Claude) started it as a background process, you
  can kill it for them on request. Tell the user: "Just say 'stop the app' and
  I'll shut it down."
- **To restart later** without going through this whole setup again: they can
  paste this into a new Claude Desktop session in this folder:
  > "Start Claude Chats — run `python3 app.py` from this folder in the
  > background and tell me when it's ready."

## Step 6 — Optional: turn on the live Dashboard (macOS only)

> **macOS only.** The live Dashboard is powered by Claude Code hooks that run a
> bash `curl` command (`curl ... >/dev/null 2>&1 &`). That syntax does not work
> on Windows, so the Dashboard is not supported there. **If the user is on
> Windows, skip this entire step** — Search, Browse, Timeline, Stats, and the
> Timesheet export all work fine without it. Tell the Windows user the Dashboard
> tab will simply stay empty, and move on to Step 6.5.

Ask the user, exactly:

> "There's one optional thing left. The app has a 'Dashboard' view that shows
> which of your Claude Code sessions are running right now — working vs.
> waiting for input. It's populated by Claude Code hooks that fire a tiny
> localhost ping on session events. Two honest notes before you decide:
>
> 1. **The only thing this enables is the Dashboard view.** Search, Browse,
>    Timeline, and Stats all work fine without it.
> 2. **Julie (who built this) doesn't actually find the Dashboard that
>    useful** — so if you're on the fence, it's totally fine to skip.
> 3. **About the file I'd be editing.** `~/.claude/settings.json` controls
>    how Claude Code itself behaves. A bad edit (corrupted JSON, accidentally
>    overwriting other settings) could keep Claude Code from starting
>    cleanly. To be safe, I will: (a) back up the file before touching it,
>    (b) show you exactly what's being added before I write, (c) re-parse
>    the file afterward to confirm it's still valid JSON, and (d) restore
>    the backup automatically if anything looks wrong.
>
> Want me to set it up anyway, or skip it?"

**If they skip:** great, move on to Step 7.

**If they want it:** do the following.

### What you'll do

Merge four hook entries into the user's `~/.claude/settings.json`. The hooks
fire-and-forget a `curl` POST to `http://localhost:5111/api/hook/...` with a
1-second timeout, run detached with `&`, and silently fail if the app isn't
running. They will not slow down or stall the user's Claude Code sessions.

### Procedure (do every step — the safety steps are not optional)

1. **Read the existing settings file** at `~/.claude/settings.json`. If it
   doesn't exist, skip step 2 and create a new file in step 5.
2. **Back it up first.** Copy the file to
   `~/.claude/settings.json.bak.<YYYY-MM-DD-HHMM>` using the actual current
   timestamp. Never overwrite an existing backup — if a backup with that
   exact name already exists, append `-2`, `-3`, etc.
3. **Compute the merged content — don't overwrite.** If the file already
   has a `hooks` key with entries for `SessionStart`, `UserPromptSubmit`,
   `Stop`, or `SessionEnd`, *append* to those arrays rather than replacing
   them. The user may have other hooks configured (statusline integrations,
   formatters, etc.) that you must not clobber. Do not modify any non-hook
   keys at all.
4. **Preview the change to the user before writing.** Briefly tell them:
   "I'm about to add 4 hook entries to your settings file; nothing else in
   the file will change. I've already backed up the original to
   `~/.claude/settings.json.bak.<timestamp>`." Don't make them re-approve —
   they already consented; this is just transparency.
5. **Write the merged result** with 2-space indent so the file stays readable.
6. **Validate immediately after writing.** Re-read the file and parse it as
   JSON. If parsing fails for any reason, restore the backup immediately
   (`cp ~/.claude/settings.json.bak.<timestamp> ~/.claude/settings.json`)
   and tell the user what happened. Do not leave the user with a broken
   settings file under any circumstances.
7. **Tell the user** they need to start a *new* Claude Code session for the
   hooks to take effect, and remind them where the backup lives in case
   they want to undo this later.

### The hook entries to merge

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

### Verify it worked

After the user starts a new Claude Code session somewhere, have them refresh
http://localhost:5111 and look at the Dashboard. They should see at least
that new session listed under "working" or "waiting." If not, double-check
that `~/.claude/settings.json` parses as valid JSON (a misplaced comma will
silently disable all hooks).

### If something goes wrong after the user restarts Claude Code

If Claude Code misbehaves on next launch (errors on startup, settings
appear reset, hooks not firing as expected), there are two recovery paths
in order of preference:

1. **Restore the backup.** Tell the user: "Your previous settings are saved
   at `~/.claude/settings.json.bak.<timestamp>`. Want me to restore it?"
   If yes, copy the backup back over `~/.claude/settings.json`, then have
   them restart Claude Code again.
2. **Reset to defaults.** Deleting `~/.claude/settings.json` entirely is
   safe — Claude Code recreates a default file on next launch. The user
   loses any custom settings that were in there (theme, model preferences,
   custom permissions, other hooks), so always prefer option 1 first.

If the user restored the backup but still has problems, the issue is
unrelated to this setup — direct them to whatever support channel they
normally use for Claude Code.

### How to turn it off later

Tell the user: "If you change your mind, just open `~/.claude/settings.json`
and delete the four entries we added (`SessionStart`, `UserPromptSubmit`,
`Stop`, `SessionEnd`) — or paste this prompt into Claude Desktop:
*'Remove the Claude Chats dashboard hooks from my Claude settings.'*"

## Step 6.5 — Optional: turn on Slack sync

Ask the user, exactly:

> "One more optional thing. The app has a 'Sync Slack' button that pulls
> **only your own** Slack messages into the local database, so they show up
> alongside your Claude prompts when you click 'Dump Timesheet' (useful if
> your day is part Claude work, part Slack conversations). Two honest notes:
>
> 1. **It's read-only.** The token has no write scopes — this app cannot
>    post to Slack on your behalf, only read your own messages.
> 2. **It's optional.** If you skip it, the 'Sync Slack' button just stays
>    disabled and everything else works fine.
>
> Want me to set it up, or skip it?"

**If they skip:** great, move on to Step 7.

**If they want it:** the user needs to do the parts you can't do for them
(creating the Slack app, copying the token), and you do the rest.

### What you'll do

1. **Walk the user through token creation.** They need to create a private
   Slack app and copy a User OAuth Token (`xoxp-...`). The full procedure —
   the exact menu path, the exact set of scopes to add, and where the token
   appears — is in the *Slack sync (optional)* section of `README.md`. Read
   that section to the user step by step (don't paraphrase the scope list —
   they need all of `channels:read`, `channels:history`, `groups:read`,
   `groups:history`, `im:read`, `im:history`, `mpim:read`, `mpim:history`,
   `users:read`).
2. **Help them set the env var.** They have two options; pick whichever fits
   their setup. The commands differ by OS — use the right block.

   **macOS / Linux (bash/zsh):**
   - **Per-session (simple, what `README.md` shows):** before launching the
     app, run `export SLACK_USER_TOKEN=xoxp-...` in the same terminal. This
     means they need to set it again every time they reopen the terminal.
     Fine for one-off testing.
   - **Persistent (recommended for daily use):** append
     `export SLACK_USER_TOKEN=xoxp-...` to their shell rc file (`~/.zshrc` on
     a default Mac, `~/.bash_profile` if they're on bash). Tell them to open
     a new terminal afterwards so the variable is loaded. **Never** check
     this into git — `~/.zshrc` lives in their home directory, not in this
     repo, so that's safe by default.

   **Windows:**
   - **Per-session (simple):** before launching the app, in the *same*
     terminal run `set SLACK_USER_TOKEN=xoxp-...` (Command Prompt) or
     `$env:SLACK_USER_TOKEN="xoxp-..."` (PowerShell). It's forgotten when they
     close the window.
   - **Persistent (recommended for daily use):** run
     `setx SLACK_USER_TOKEN "xoxp-..."` once (Command Prompt or PowerShell).
     This saves it for all *future* terminals — they must open a **new**
     terminal afterward for it to take effect (it does not affect the current
     one). Alternatively, set it via *Settings → System → About → Advanced
     system settings → Environment Variables*. This is stored in the user's
     Windows account, not in this repo, so it's never committed to git.
3. **Restart the app** so it picks up the new env var. If the app is
   currently running, ask the user to say "stop the app" first; once it's
   down, relaunch with `python3 app.py`.
4. **Verify it worked.** Tell the user to refresh `http://localhost:5111`
   and look at the Sync Slack button. If it's no longer grayed out, hover
   text now shows last sync time, and clicking it pulls real messages — it
   worked. If it's still disabled, the env var didn't make it into the
   process; usually that means the app wasn't restarted in the same terminal
   the `export` ran in.

### How to turn it off later

Tell the user: "If you change your mind, just remove the
`SLACK_USER_TOKEN` line from your shell rc file (or unset the variable in
the running terminal) and restart the app. The Slack messages already
synced will stay in the database; nothing is deleted automatically. If you
want to wipe them, ask Claude to delete the `slack_messages` table."

## Step 7 — Offer a one-click shortcut

Ask the user:

> "Setup is done. Want me to create a one-click way to start the app in the
> future, so you don't need to ask Claude every time? On Mac it'll be a file
> you can double-click from Finder; on Windows, same idea from File Explorer."

### If they say yes

**Decide first: continue in this session or hand off to a new one?**

Use judgment based on the conversation so far:
- **Continue here** if setup went smoothly (few or no errors, conversation
  feels fresh, you remember the user's OS clearly).
- **Hand off to a fresh session** if you spent a lot of back-and-forth
  troubleshooting, the conversation is long, or you're feeling uncertain
  about state. Give the user this prompt to paste into a new Code-tab session
  in the same folder:
  > "Create a one-click startup shortcut for Claude Chats. I'm on [Mac/Windows].
  > Follow the 'Step 7' instructions in `00ai/SetupInstructionsForClaude.md`."

**To create the shortcut:**

- **Mac** — write `start-claudechats.command` in the repo root:
  ```bash
  #!/bin/bash
  cd "$(dirname "$0")"
  python3 app.py
  ```
  Then make it executable: `chmod +x start-claudechats.command`. Tell the user
  they can now double-click this file in Finder anytime to start the app. A
  Terminal window will open and stay open while it runs; closing that window
  stops the app. (First double-click may show a Gatekeeper warning — instruct
  them to right-click → Open the first time, then click "Open" in the dialog.)

- **Windows** — write `start-claudechats.bat` in the repo root:
  ```bat
  @echo off
  cd /d "%~dp0"
  python app.py
  pause
  ```
  Tell the user they can now double-click this file in File Explorer to start
  the app. A black command window opens and stays open while it runs; closing
  the window stops the app.

After creating the shortcut file, append its name to `.gitignore` (creating
the file if needed) so it doesn't get pushed back to the shared repo — it's
specific to the user's machine.

### If they say no

Tell them they can always come back and ask for the shortcut later by pasting:
> "Create the one-click startup shortcut for Claude Chats — Step 7 in
> `00ai/SetupInstructionsForClaude.md`."

---

## When you're stuck

If you've been troubleshooting one step for 5+ exchanges and aren't making
progress, suggest the user start a fresh Claude Desktop session in this folder
and paste:
> "Continue Claude Chats setup. I got stuck on [step name]. Here's what
> happened: [paste the most recent error]."

A fresh session with a focused prompt often unblocks faster than continuing
in a thread that's accumulated dead-ends.
