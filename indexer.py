"""JSONL transcript parser + SQLite FTS5 indexer for Claude Code conversations."""

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
SESSIONS_DIR = Path.home() / ".claude" / "sessions"


def _cowork_dir() -> Path:
    """Claude desktop "Cowork" tab: each session runs the Claude Code CLI inside a
    per-session sandbox, so its transcript is a standard CC JSONL nested under the
    sandbox home, alongside a local_<sid>.json metadata file. The sandboxes live in
    the platform's per-user app-support directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Claude" / "local-agent-mode-sessions"
    return Path.home() / ".config" / "Claude" / "local-agent-mode-sessions"


COWORK_DIR = _cowork_dir()
DB_PATH = Path(__file__).parent / "transcripts.db"


def decode_folder_name(folder: str) -> str:
    """Convert a Claude Code project folder name into a readable project path.

    Claude Code encodes a cwd into the folder name by replacing path separators with
    '-': macOS/Linux '/Users/julie/projects/myapp' -> '-Users-julie-projects-myapp';
    Windows 'C:\\Users\\julie\\projects\\myapp' -> 'C--Users-julie-projects-myapp'
    (both ':' and '\\' become '-'). We strip the encoded home-directory prefix and
    return the remainder with '-' turned back into '/', e.g. 'projects/myapp'.

    Cross-platform: the home dir is encoded the same way before stripping, so it works
    regardless of separator. If the prefix doesn't match (unexpected encoding), the
    folder name is returned unchanged — a degraded label, never a crash.
    """
    home_encoded = re.sub(r"[/\\:]", "-", str(Path.home()))
    rest = folder
    if rest.startswith(home_encoded):
        rest = rest[len(home_encoded):]
    rest = rest.strip("-")
    if not rest:
        return folder
    return rest.replace("-", "/")


def is_human_message(record: dict) -> bool:
    """Check if a JSONL record is a genuine human-typed message."""
    return (
        record.get("type") == "user"
        and "permissionMode" in record
        and not record.get("isMeta", False)
        and "sourceToolAssistantUUID" not in record
    )


def is_command_message(record: dict) -> bool:
    """Check if a JSONL record is a slash command or skill invocation."""
    if record.get("type") != "user":
        return False
    if record.get("isMeta", False):
        return False
    if "sourceToolAssistantUUID" in record:
        return False
    if "permissionMode" in record:
        return False  # already handled by is_human_message
    content = extract_content(record)
    return "<command-name>" in content


def is_plan_answer_message(record: dict) -> bool:
    """User answer to AskUserQuestion: type=user with toolUseResult.answers."""
    if record.get("type") != "user":
        return False
    if record.get("isMeta", False):
        return False
    tur = record.get("toolUseResult")
    if not isinstance(tur, dict):
        return False
    answers = tur.get("answers")
    return isinstance(answers, dict) and bool(answers)


def format_plan_answer_content(record: dict) -> str:
    """Render AskUserQuestion answers as a single Q/A block for indexing."""
    tur = record.get("toolUseResult", {}) or {}
    answers = tur.get("answers", {}) or {}
    annotations = tur.get("annotations", {}) or {}
    lines = ["[Plan mode answer]"]
    for q, a in answers.items():
        lines.append(f"Q: {q}")
        lines.append(f"A: {a}")
        ann = annotations.get(q)
        notes = ann.get("notes", "") if isinstance(ann, dict) else ""
        if notes and notes != a:
            lines.append(f"Notes: {notes}")
    return "\n".join(lines)


def is_skip_first_command(content: str) -> bool:
    """True if a command line should not count as a session's 'first message'."""
    if not content or not content.strip():
        return False
    head = content.strip().split()[0]
    return head in ("/clear", "/model")


def format_command_content(content: str) -> str:
    """Extract a clean slash command string from XML-tagged content."""
    match = re.search(r"<command-name>(.*?)</command-name>", content)
    if match:
        cmd = match.group(1)
        args_match = re.search(r"<command-args>(.*?)</command-args>", content, re.DOTALL)
        args = args_match.group(1).strip() if args_match else ""
        return f"{cmd} {args}".strip() if args else cmd
    return content


def extract_content(record: dict) -> str:
    """Extract text content from a message record."""
    content = record.get("message", {}).get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return " ".join(t for t in texts if t).strip()
    return ""


def init_db(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT UNIQUE,
            session_id TEXT,
            project TEXT,
            timestamp TEXT,
            content TEXT,
            assistant_response TEXT DEFAULT '',
            cwd TEXT,
            git_branch TEXT,
            jsonl_file TEXT,
            source TEXT DEFAULT 'code'
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            project TEXT,
            first_ts TEXT,
            last_ts TEXT,
            message_count INTEGER DEFAULT 0,
            file_missing INTEGER DEFAULT 0,
            name TEXT DEFAULT '',
            slug TEXT DEFAULT '',
            source TEXT DEFAULT 'code'
        );
        CREATE TABLE IF NOT EXISTS index_meta (
            jsonl_file TEXT PRIMARY KEY,
            mtime REAL,
            indexed_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_messages_project ON messages(project);
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
        CREATE TABLE IF NOT EXISTS session_meta (
            session_id TEXT PRIMARY KEY,
            starred INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0,
            hidden INTEGER DEFAULT 0,
            complete INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS session_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            UNIQUE(session_id, tag)
        );
        CREATE INDEX IF NOT EXISTS idx_session_tags_tag ON session_tags(tag);
        CREATE INDEX IF NOT EXISTS idx_session_tags_session ON session_tags(session_id);
    """)
    # Migrate: add file_missing column if missing (for existing databases)
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN file_missing INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Migrate: add hidden column if missing (for existing databases)
    try:
        conn.execute("ALTER TABLE session_meta ADD COLUMN hidden INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Migrate: add complete column if missing (for existing databases)
    try:
        conn.execute("ALTER TABLE session_meta ADD COLUMN complete INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Migrate: add assistant_response column if missing (for existing databases)
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN assistant_response TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Migrate: add name/slug columns to sessions if missing
    for col in ("name", "slug"):
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    # Migrate: add source column (code vs cowork) to messages and sessions
    for tbl in ("messages", "sessions"):
        try:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN source TEXT DEFAULT 'code'")
        except sqlite3.OperationalError:
            pass
    # FTS5 virtual table — drop and recreate if schema changed (e.g. added assistant_response)
    try:
        result = conn.execute("PRAGMA table_info(messages_fts)").fetchall()
        col_names = [r[1] for r in result]
        if 'assistant_response' not in col_names:
            conn.execute("DROP TABLE IF EXISTS messages_fts")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
            USING fts5(content, assistant_response, project, content_rowid='id', tokenize='porter unicode61');
        """)
    except sqlite3.OperationalError:
        pass  # already exists
    # Slack sync tables — separate from `messages` so Slack rows don't leak into
    # search/sessions/projects/timeline/stats endpoints.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS slack_messages (
            slack_ts TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            project TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            content TEXT NOT NULL,
            edited_at TEXT DEFAULT '',
            thread_ts TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_slack_messages_timestamp ON slack_messages(timestamp);
        CREATE INDEX IF NOT EXISTS idx_slack_messages_channel ON slack_messages(channel_id);
        CREATE TABLE IF NOT EXISTS slack_sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)


def load_session_names() -> dict:
    """Read ~/.claude/sessions/*.json and return {sessionId: name}."""
    names = {}
    if not SESSIONS_DIR.exists():
        return names
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sid = data.get("sessionId", "")
            name = data.get("name", "")
            if sid and name:
                names[sid] = name
        except (json.JSONDecodeError, OSError):
            continue
    return names


def _extract_slug(jsonl_path: str, session_slugs: dict):
    """Quick scan of first few lines to grab sessionId and slug."""
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 5:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = record.get("sessionId", "")
                slug = record.get("slug", "")
                if sid and slug:
                    session_slugs[sid] = slug
                    return
    except (OSError, UnicodeDecodeError):
        pass


def _extract_name(jsonl_path: str, session_names: dict):
    """Scan JSONL for the last custom-title record and record sessionId -> title.

    Claude Code emits {"type":"custom-title","customTitle":...,"sessionId":...} on /rename.
    These records are durable in the transcript, so they survive terminal close —
    unlike ~/.claude/sessions/{pid}.json which is keyed by PID and inconsistently populated.
    """
    last_sid = ""
    last_name = ""
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if '"custom-title"' not in line:
                    continue
                try:
                    record = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "custom-title":
                    continue
                title = record.get("customTitle", "")
                sid = record.get("sessionId", "")
                if title:
                    last_name = title
                if sid:
                    last_sid = sid
    except (OSError, UnicodeDecodeError):
        return
    if last_sid and last_name:
        session_names[last_sid] = last_name


def index_file(conn: sqlite3.Connection, jsonl_path: str, project: str, source: str = "code"):
    """Parse a single JSONL file and insert human messages with assistant responses.
    Returns (session_id, slug, custom_title) extracted from records.

    `source` tags every row as 'code' (Claude Code CLI) or 'cowork' (desktop Cowork tab).

    Re-indexing relies on INSERT OR REPLACE keyed on `uuid` to update existing rows.
    We intentionally do NOT bulk-delete rows by jsonl_file first — if Claude Code
    truncates a transcript in place during cleanup, the messages that disappear
    from the file must remain in the DB as tombstones (see 'Survives Claude's
    cleanup' in demo-walkthrough.md).
    """
    # Collect human messages and pair each with the assistant response that follows it
    human_messages = []  # list of [uuid, session_id, project, ts, content, cwd, branch, file, assistant_response]
    last_assistant_text = ""
    slug = ""
    file_session_id = ""
    custom_title = ""
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not slug and record.get("slug"):
                    slug = record["slug"]
                if not file_session_id and record.get("sessionId"):
                    file_session_id = record["sessionId"]
                if record.get("type") == "custom-title":
                    title = record.get("customTitle", "")
                    if title:
                        custom_title = title

                if record.get("type") == "assistant":
                    text = extract_content(record)
                    if text:
                        last_assistant_text = text
                elif is_human_message(record):
                    # Attach accumulated assistant response to the PREVIOUS human message
                    if human_messages and last_assistant_text:
                        human_messages[-1][-1] = last_assistant_text
                    last_assistant_text = ""
                    content = extract_content(record)
                    if not content:
                        continue
                    human_messages.append([
                        record.get("uuid", ""),
                        record.get("sessionId", ""),
                        project,
                        record.get("timestamp", ""),
                        content,
                        record.get("cwd", ""),
                        record.get("gitBranch", ""),
                        jsonl_path,
                        "",  # assistant_response placeholder
                    ])
                elif is_command_message(record):
                    if human_messages and last_assistant_text:
                        human_messages[-1][-1] = last_assistant_text
                    last_assistant_text = ""
                    content = format_command_content(extract_content(record))
                    if not content:
                        continue
                    human_messages.append([
                        record.get("uuid", ""),
                        record.get("sessionId", ""),
                        project,
                        record.get("timestamp", ""),
                        content,
                        record.get("cwd", ""),
                        record.get("gitBranch", ""),
                        jsonl_path,
                        "",  # assistant_response placeholder
                    ])
                elif is_plan_answer_message(record):
                    if human_messages and last_assistant_text:
                        human_messages[-1][-1] = last_assistant_text
                    last_assistant_text = ""
                    content = format_plan_answer_content(record)
                    if not content:
                        continue
                    human_messages.append([
                        record.get("uuid", ""),
                        record.get("sessionId", ""),
                        project,
                        record.get("timestamp", ""),
                        content,
                        record.get("cwd", ""),
                        record.get("gitBranch", ""),
                        jsonl_path,
                        "",  # assistant_response placeholder
                    ])
    except (OSError, UnicodeDecodeError):
        return "", "", ""

    # Attach final assistant response to the last human message
    if human_messages and last_assistant_text:
        human_messages[-1][-1] = last_assistant_text

    if human_messages:
        rows = [row + [source] for row in human_messages]
        conn.executemany("""
            INSERT OR REPLACE INTO messages
            (uuid, session_id, project, timestamp, content, cwd, git_branch, jsonl_file, assistant_response, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)

    return file_session_id, slug, custom_title


def rebuild_fts(conn: sqlite3.Connection):
    """Rebuild the FTS index from the messages table."""
    conn.execute("DELETE FROM messages_fts")
    conn.execute("""
        INSERT INTO messages_fts(rowid, content, assistant_response, project)
        SELECT id, content, COALESCE(assistant_response, ''), project FROM messages
    """)


def rebuild_sessions(conn: sqlite3.Connection, session_names=None, session_slugs=None):
    """Rebuild session summary table, marking sessions whose source files are missing."""
    conn.execute("DELETE FROM sessions")
    conn.execute("""
        INSERT INTO sessions (session_id, project, first_ts, last_ts, message_count, file_missing, source)
        SELECT session_id, project, MIN(timestamp), MAX(timestamp), COUNT(*), 0, MAX(source)
        FROM messages
        GROUP BY session_id
    """)
    if session_slugs:
        for sid, s in session_slugs.items():
            conn.execute("UPDATE sessions SET slug = ? WHERE session_id = ?", (s, sid))
    if session_names:
        for sid, n in session_names.items():
            conn.execute("UPDATE sessions SET name = ? WHERE session_id = ?", (n, sid))
    # Mark sessions whose JSONL source files no longer exist on disk
    rows = conn.execute("""
        SELECT DISTINCT session_id, jsonl_file FROM messages
    """).fetchall()
    missing_sessions = set()
    for session_id, jsonl_file in rows:
        if not os.path.exists(jsonl_file):
            missing_sessions.add(session_id)
    if missing_sessions:
        placeholders = ",".join("?" * len(missing_sessions))
        conn.execute(
            f"UPDATE sessions SET file_missing = 1 WHERE session_id IN ({placeholders})",
            list(missing_sessions),
        )


def iter_cowork_sessions():
    """Yield (jsonl_path, project, cli_session_id, title, mtime) for each Cowork session.

    Cowork stores per-session metadata at <group>/<sub>/local_<sid>.json. The actual
    transcript is a standard Claude Code JSONL the sandboxed CLI wrote underneath that
    sandbox, keyed by the metadata's `cliSessionId`. The friendly project name comes
    from the user's first selected folder (the transcript's own cwd is the sandbox path).
    """
    if not COWORK_DIR.exists():
        return
    for meta_path in COWORK_DIR.glob("*/*/local_*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        cli_sid = meta.get("cliSessionId")
        if not cli_sid:
            continue
        sandbox = meta_path.with_suffix("")  # strip .json -> .../local_<sid>/
        hits = list(sandbox.glob(f".claude/projects/*/{cli_sid}.jsonl"))
        if not hits:
            continue
        jsonl_path = hits[0]
        try:
            mtime = jsonl_path.stat().st_mtime
        except OSError:
            continue
        folders = meta.get("userSelectedFolders") or []
        if folders:
            project = decode_folder_name("-" + folders[0].replace("\\", "/").strip("/").replace("/", "-"))
        else:
            project = "cowork"
        yield str(jsonl_path), project, cli_sid, meta.get("title", ""), mtime


def run_index(full_rebuild: bool = False) -> dict:
    """Run indexing. Returns stats dict."""
    t0 = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    init_db(conn)

    # Auto-detect if assistant_response column was just added and needs backfill
    msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    if not full_rebuild and msg_count > 0:
        has_any = conn.execute("SELECT COUNT(*) FROM messages WHERE assistant_response != ''").fetchone()[0]
        if has_any == 0:
            full_rebuild = True

    if full_rebuild:
        # Wipe index_meta so every existing file gets re-processed. We deliberately
        # do NOT delete from `messages`: index_file uses INSERT OR REPLACE on uuid,
        # so re-indexing updates rows in place. Tombstones (rows whose source file
        # is gone, or rows whose uuid was truncated out of an existing file) survive.
        conn.execute("DELETE FROM index_meta")

    # Get existing mtimes
    existing = {}
    for row in conn.execute("SELECT jsonl_file, mtime FROM index_meta"):
        existing[row[0]] = row[1]

    files_indexed = 0
    session_slugs = {}
    session_names_from_jsonl = {}
    if PROJECTS_DIR.exists():
        for folder in sorted(PROJECTS_DIR.iterdir()):
            if not folder.is_dir():
                continue
            project = decode_folder_name(folder.name)
            for jsonl_file in folder.glob("*.jsonl"):
                fpath = str(jsonl_file)
                mtime = jsonl_file.stat().st_mtime
                if not full_rebuild and fpath in existing and existing[fpath] >= mtime:
                    # Still extract slug + custom-title from skipped files for rebuild_sessions
                    _extract_slug(fpath, session_slugs)
                    _extract_name(fpath, session_names_from_jsonl)
                    continue
                sid, slug, custom_title = index_file(conn, fpath, project)
                if sid and slug:
                    session_slugs[sid] = slug
                if sid and custom_title:
                    session_names_from_jsonl[sid] = custom_title
                conn.execute(
                    "INSERT OR REPLACE INTO index_meta (jsonl_file, mtime, indexed_at) VALUES (?, ?, ?)",
                    (fpath, mtime, time.time()),
                )
                files_indexed += 1

    # Cowork sessions (Claude desktop "Cowork" tab) — same JSONL format, nested in a
    # per-session sandbox. Tagged source='cowork' so the UI can filter them apart.
    for fpath, project, cli_sid, title, mtime in iter_cowork_sessions():
        if title:
            session_names_from_jsonl[cli_sid] = title
        if not full_rebuild and fpath in existing and existing[fpath] >= mtime:
            continue
        index_file(conn, fpath, project, source="cowork")
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (jsonl_file, mtime, indexed_at) VALUES (?, ?, ?)",
            (fpath, mtime, time.time()),
        )
        files_indexed += 1

    rebuild_fts(conn)
    pid_names = load_session_names()
    merged_names = {**pid_names, **session_names_from_jsonl}  # JSONL custom-title wins
    rebuild_sessions(conn, session_names=merged_names, session_slugs=session_slugs)
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    elapsed = time.time() - t0
    return {"files_indexed": files_indexed, "total_messages": total, "elapsed_seconds": round(elapsed, 2)}


if __name__ == "__main__":
    import sys
    full = "--full" in sys.argv
    stats = run_index(full_rebuild=full)
    print(f"Indexed {stats['files_indexed']} files, {stats['total_messages']} messages in {stats['elapsed_seconds']}s")
