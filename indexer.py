"""JSONL transcript parser + SQLite FTS5 indexer for Claude Code conversations."""

import json
import os
import re
import sqlite3
import time
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
DB_PATH = Path(__file__).parent / "transcripts.db"


def decode_folder_name(folder: str) -> str:
    """Convert folder name like -Users-julie-projects-myapp to projects/myapp."""
    # Strip the home-directory prefix portion
    parts = folder.split("-")
    # Find the meaningful suffix after the home dir segments
    # Pattern: -Users-<user>-... we want the project-relevant tail
    home = str(Path.home()).strip("/").split("/")  # e.g. ['Users', 'julie']
    remaining = parts[1:]  # skip leading empty from first dash
    # Skip parts that match the home directory
    idx = 0
    for segment in home:
        if idx < len(remaining) and remaining[idx] == segment:
            idx += 1
    remaining = remaining[idx:]
    if not remaining:
        return folder
    return "/".join(remaining)


def is_human_message(record: dict) -> bool:
    """Check if a JSONL record is a genuine human-typed message."""
    return (
        record.get("type") == "user"
        and "permissionMode" in record
        and not record.get("isMeta", False)
        and "sourceToolAssistantUUID" not in record
    )


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
            cwd TEXT,
            git_branch TEXT,
            jsonl_file TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            project TEXT,
            first_ts TEXT,
            last_ts TEXT,
            message_count INTEGER DEFAULT 0,
            file_missing INTEGER DEFAULT 0
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
            hidden INTEGER DEFAULT 0
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
    # FTS5 virtual table
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
            USING fts5(content, project, content_rowid='id', tokenize='porter unicode61');
        """)
    except sqlite3.OperationalError:
        pass  # already exists


def index_file(conn: sqlite3.Connection, jsonl_path: str, project: str):
    """Parse a single JSONL file and insert human messages."""
    # Remove old messages from this file
    conn.execute("DELETE FROM messages WHERE jsonl_file = ?", (jsonl_path,))

    messages = []
    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not is_human_message(record):
                    continue
                content = extract_content(record)
                if not content:
                    continue
                messages.append((
                    record.get("uuid", ""),
                    record.get("sessionId", ""),
                    project,
                    record.get("timestamp", ""),
                    content,
                    record.get("cwd", ""),
                    record.get("gitBranch", ""),
                    jsonl_path,
                ))
    except (OSError, UnicodeDecodeError):
        return

    if messages:
        conn.executemany("""
            INSERT OR REPLACE INTO messages
            (uuid, session_id, project, timestamp, content, cwd, git_branch, jsonl_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, messages)


def rebuild_fts(conn: sqlite3.Connection):
    """Rebuild the FTS index from the messages table."""
    conn.execute("DELETE FROM messages_fts")
    conn.execute("""
        INSERT INTO messages_fts(rowid, content, project)
        SELECT id, content, project FROM messages
    """)


def rebuild_sessions(conn: sqlite3.Connection):
    """Rebuild session summary table, marking sessions whose source files are missing."""
    conn.execute("DELETE FROM sessions")
    conn.execute("""
        INSERT INTO sessions (session_id, project, first_ts, last_ts, message_count, file_missing)
        SELECT session_id, project, MIN(timestamp), MAX(timestamp), COUNT(*), 0
        FROM messages
        GROUP BY session_id
    """)
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


def run_index(full_rebuild: bool = False) -> dict:
    """Run indexing. Returns stats dict."""
    t0 = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    init_db(conn)

    if full_rebuild:
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM index_meta")

    # Get existing mtimes
    existing = {}
    for row in conn.execute("SELECT jsonl_file, mtime FROM index_meta"):
        existing[row[0]] = row[1]

    files_indexed = 0
    if PROJECTS_DIR.exists():
        for folder in sorted(PROJECTS_DIR.iterdir()):
            if not folder.is_dir():
                continue
            project = decode_folder_name(folder.name)
            for jsonl_file in folder.glob("*.jsonl"):
                fpath = str(jsonl_file)
                mtime = jsonl_file.stat().st_mtime
                if not full_rebuild and fpath in existing and existing[fpath] >= mtime:
                    continue
                index_file(conn, fpath, project)
                conn.execute(
                    "INSERT OR REPLACE INTO index_meta (jsonl_file, mtime, indexed_at) VALUES (?, ?, ?)",
                    (fpath, mtime, time.time()),
                )
                files_indexed += 1

    rebuild_fts(conn)
    rebuild_sessions(conn)
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
