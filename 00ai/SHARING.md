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

### Troubleshooting

- **"No module named flask"** — Run `pip3 install flask`.
- **No sessions showing up** — Make sure you have Claude Code transcripts in `~/.claude/projects/`. The app only indexes JSONL files from that directory.
- **Port 5111 in use** — Another instance may be running. Kill it or edit the port in `app.py`.
