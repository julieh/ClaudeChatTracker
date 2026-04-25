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

## Step 6 — Offer a one-click shortcut

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
  > Follow the 'Step 6' instructions in `00ai/SetupInstructionsForClaude.md`."

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
> "Create the one-click startup shortcut for Claude Chats — Step 6 in
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
