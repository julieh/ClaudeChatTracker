"""Flask server for Claude Chats search app."""

import shutil
import sqlite3
import threading
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, jsonify, request, render_template
from indexer import (
    run_index, DB_PATH, PROJECTS_DIR,
    is_human_message, is_command_message, format_command_content, extract_content,
    load_session_names, decode_folder_name,
)

app = Flask(__name__)

# Live session state (in-memory, ephemeral). Populated by Claude Code hooks.
_live_lock = threading.Lock()
_live_sessions = {}          # session_id -> dict
_recently_closed = []        # list of dicts, most-recent first, max 10
_RECENTLY_CLOSED_MAX = 10


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _project_from_cwd(cwd):
    if not cwd:
        return ""
    return cwd.rstrip("/").split("/")[-1] if cwd else ""


def _hook_payload():
    """Extract session info from hook JSON body. Claude Code hook payloads
    include session_id, cwd, and transcript_path among other fields."""
    data = request.get_json(silent=True) or {}
    return {
        "session_id": data.get("session_id") or data.get("sessionId") or "",
        "cwd": data.get("cwd") or "",
        "transcript_path": data.get("transcript_path") or data.get("transcriptPath") or "",
    }


def _upsert_live(session_id, state, cwd="", transcript_path=""):
    if not session_id:
        return
    now = _now_iso()
    existing = _live_sessions.get(session_id)
    if existing:
        existing["state"] = state
        existing["updated_at"] = now
        if cwd:
            existing["cwd"] = cwd
            existing["project"] = _project_from_cwd(cwd)
        if transcript_path:
            existing["transcript_path"] = transcript_path
    else:
        _live_sessions[session_id] = {
            "session_id": session_id,
            "state": state,
            "cwd": cwd,
            "project": _project_from_cwd(cwd),
            "transcript_path": transcript_path,
            "started_at": now,
            "updated_at": now,
        }


@app.route("/api/hook/session-start", methods=["POST"])
def hook_session_start():
    p = _hook_payload()
    with _live_lock:
        _upsert_live(p["session_id"], "waiting", p["cwd"], p["transcript_path"])
    return jsonify({"ok": True})


@app.route("/api/hook/user-prompt-submit", methods=["POST"])
def hook_user_prompt_submit():
    p = _hook_payload()
    with _live_lock:
        _upsert_live(p["session_id"], "working", p["cwd"], p["transcript_path"])
    return jsonify({"ok": True})


@app.route("/api/hook/stop", methods=["POST"])
def hook_stop():
    p = _hook_payload()
    with _live_lock:
        _upsert_live(p["session_id"], "waiting", p["cwd"], p["transcript_path"])
    return jsonify({"ok": True})


@app.route("/api/hook/session-end", methods=["POST"])
def hook_session_end():
    p = _hook_payload()
    sid = p["session_id"]
    if not sid:
        return jsonify({"ok": True})
    with _live_lock:
        entry = _live_sessions.pop(sid, None)
        if entry is None:
            entry = {
                "session_id": sid,
                "cwd": p["cwd"],
                "project": _project_from_cwd(p["cwd"]),
                "started_at": _now_iso(),
            }
        entry["state"] = "closed"
        entry["updated_at"] = _now_iso()
        _recently_closed.insert(0, entry)
        del _recently_closed[_RECENTLY_CLOSED_MAX:]
    return jsonify({"ok": True})


def _scan_transcript(transcript_path):
    """Yield parsed JSONL records from a transcript file, skipping bad lines."""
    if not transcript_path:
        return
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
    except (FileNotFoundError, IOError, OSError):
        return


_STALE_SECONDS = 5 * 60  # Transcripts idle this long are treated as closed.


def _iso_from_epoch(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _infer_live_entry(path):
    """Inspect a JSONL transcript; return (entry_dict, is_stale) or (None, None) if unusable."""
    try:
        st = path.stat()
    except OSError:
        return None, None
    mtime = st.st_mtime
    sid = path.stem

    cwd = ""
    last_role = ""  # "assistant" | "human" | "command"
    for rec in _scan_transcript(str(path)):
        if not cwd:
            rc = rec.get("cwd")
            if isinstance(rc, str) and rc:
                cwd = rc
        if rec.get("type") == "assistant":
            last_role = "assistant"
        elif is_human_message(rec):
            last_role = "human"
        elif is_command_message(rec):
            last_role = "command"

    if not cwd:
        cwd = "/" + decode_folder_name(path.parent.name)

    is_stale = (time.time() - mtime) > _STALE_SECONDS
    if is_stale:
        state = "closed"
    elif last_role == "assistant":
        state = "waiting"
    elif last_role in ("human", "command"):
        state = "working"
    else:
        state = "waiting"

    entry = {
        "session_id": sid,
        "state": state,
        "cwd": cwd,
        "project": _project_from_cwd(cwd),
        "transcript_path": str(path),
        "started_at": _iso_from_epoch(st.st_ctime),
        "updated_at": _iso_from_epoch(mtime),
    }
    return entry, is_stale


def _scan_live_from_disk(hours=24):
    """Walk PROJECTS_DIR for JSONL transcripts modified within `hours` and populate
    _live_sessions / _recently_closed for any session_ids we don't already track.
    Hook-populated entries are never overwritten."""
    if not PROJECTS_DIR.exists():
        return {"scanned": 0, "added_active": 0, "added_closed": 0}
    cutoff = time.time() - hours * 3600

    candidates = []  # list of Path
    for folder in PROJECTS_DIR.iterdir():
        if not folder.is_dir():
            continue
        for jsonl in folder.glob("*.jsonl"):
            try:
                if jsonl.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            candidates.append(jsonl)

    added_active = 0
    added_closed = 0
    for path in candidates:
        sid = path.stem
        with _live_lock:
            if sid in _live_sessions:
                continue
            if any(s.get("session_id") == sid for s in _recently_closed):
                continue
        entry, is_stale = _infer_live_entry(path)
        if entry is None:
            continue
        with _live_lock:
            if sid in _live_sessions or any(s.get("session_id") == sid for s in _recently_closed):
                continue
            if is_stale:
                _recently_closed.insert(0, entry)
                del _recently_closed[_RECENTLY_CLOSED_MAX:]
                added_closed += 1
            else:
                _live_sessions[sid] = entry
                added_active += 1
    return {"scanned": len(candidates), "added_active": added_active, "added_closed": added_closed}


def _first_prompt_from_transcript(transcript_path, limit=200):
    for entry in _scan_transcript(transcript_path):
        if is_human_message(entry):
            text = extract_content(entry)
            if text:
                return text[:limit]
        elif is_command_message(entry):
            cmd = format_command_content(extract_content(entry))
            if cmd and cmd.strip().split()[0] != "/clear":
                return cmd[:limit]
    return ""


def _last_exchange_from_transcript(transcript_path, limit=200):
    """Return (last_human_text, last_assistant_text), each <= limit chars."""
    last_human = ""
    last_assistant = ""
    for entry in _scan_transcript(transcript_path):
        if entry.get("type") == "assistant":
            text = extract_content(entry)
            if text:
                last_assistant = text
        elif is_human_message(entry):
            text = extract_content(entry)
            if text:
                last_human = text
        elif is_command_message(entry):
            cmd = format_command_content(extract_content(entry))
            if cmd:
                last_human = cmd
    return last_human[:limit], last_assistant[:limit]


def _enrich_session(session, live_names=None):
    """Add name, message_count, first_prompt, last_human, last_assistant fields.
    Prefers the live terminal-window name from ~/.claude/sessions/*.json over DB name/slug."""
    enriched = dict(session)
    sid = enriched.get("session_id", "")
    transcript_path = enriched.get("transcript_path", "")
    if not transcript_path and sid:
        cwd = enriched.get("cwd", "")
        if cwd:
            candidate = PROJECTS_DIR / cwd.replace("/", "-") / f"{sid}.jsonl"
            if candidate.exists():
                transcript_path = str(candidate)

    # DB lookup for name/slug/message_count.
    db_name = ""
    db_slug = ""
    message_count = 0
    if sid:
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT name, slug, message_count FROM sessions WHERE session_id = ?",
                [sid],
            ).fetchone()
            conn.close()
            if row:
                db_name = row["name"] or ""
                db_slug = row["slug"] or ""
                message_count = row["message_count"] or 0
        except sqlite3.Error:
            pass
    live_name = (live_names or {}).get(sid, "") if sid else ""
    enriched["name"] = live_name or db_name or db_slug
    enriched["message_count"] = message_count

    # Transcript scan for prompts.
    enriched["first_prompt"] = _first_prompt_from_transcript(transcript_path)
    last_human, last_assistant = _last_exchange_from_transcript(transcript_path)
    enriched["last_human"] = last_human
    enriched["last_assistant"] = last_assistant
    return enriched


@app.route("/api/dashboard")
def dashboard_api():
    with _live_lock:
        active = sorted(_live_sessions.values(), key=lambda s: s["updated_at"], reverse=True)
        closed = list(_recently_closed)
    live_names = load_session_names()
    return jsonify({
        "active": [_enrich_session(s, live_names) for s in active],
        "recently_closed": [_enrich_session(s, live_names) for s in closed],
        "generated_at": _now_iso(),
    })


@app.route("/api/dashboard/session/<session_id>/transcript")
def dashboard_session_transcript(session_id):
    """Full human+assistant transcript for inline expand on Dashboard.
    Prefers indexed DB rows; falls back to scanning the JSONL for live sessions."""
    # Try DB first.
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT timestamp, content, assistant_response
            FROM messages WHERE session_id = ? ORDER BY timestamp ASC
        """, [session_id]).fetchall()
        conn.close()
    except sqlite3.Error:
        rows = []

    messages = []
    for r in rows:
        if r["content"]:
            messages.append({"role": "human", "text": r["content"], "ts": r["timestamp"]})
        if r["assistant_response"]:
            messages.append({"role": "assistant", "text": r["assistant_response"], "ts": r["timestamp"]})

    if messages:
        return jsonify({"messages": messages, "source": "db"})

    # Fallback: scan JSONL from live session state.
    with _live_lock:
        session = _live_sessions.get(session_id) or next(
            (s for s in _recently_closed if s.get("session_id") == session_id), None
        )
    transcript_path = session.get("transcript_path", "") if session else ""
    pending_human = None
    for entry in _scan_transcript(transcript_path):
        ts = entry.get("timestamp", "")
        if entry.get("type") == "assistant":
            text = extract_content(entry)
            if text:
                messages.append({"role": "assistant", "text": text, "ts": ts})
        elif is_human_message(entry):
            text = extract_content(entry)
            if text:
                messages.append({"role": "human", "text": text, "ts": ts})
        elif is_command_message(entry):
            cmd = format_command_content(extract_content(entry))
            if cmd:
                messages.append({"role": "human", "text": cmd, "ts": ts})
    return jsonify({"messages": messages, "source": "jsonl"})


@app.route("/api/dashboard/scan", methods=["POST"])
def dashboard_scan():
    """Walk ~/.claude/projects and populate _live_sessions from any recent transcripts
    we don't already know about. Useful after a server restart, which drops in-memory state."""
    hours = request.args.get("hours", 24, type=int)
    return jsonify(_scan_live_from_disk(hours=hours))


@app.route("/api/dashboard/session/<session_id>", methods=["DELETE"])
def dashboard_delete_session(session_id):
    """Manually remove a session from the live dashboard (active or recently closed)."""
    with _live_lock:
        _live_sessions.pop(session_id, None)
        _recently_closed[:] = [s for s in _recently_closed if s.get("session_id") != session_id]
    return jsonify({"ok": True})


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    return render_template("index.html")


def _attach_session_meta(conn, results, session_id_key="session_id"):
    """Attach starred/archived/tags info to a list of result dicts."""
    session_ids = list({r[session_id_key] for r in results if r.get(session_id_key)})
    if not session_ids:
        return results
    placeholders = ",".join("?" * len(session_ids))
    # Get meta
    meta_map = {}
    for row in conn.execute(f"SELECT session_id, starred, archived FROM session_meta WHERE session_id IN ({placeholders})", session_ids):
        meta_map[row["session_id"]] = {"starred": row["starred"] or 0, "archived": bool(row["archived"])}
    # Get tags
    tags_map = {}
    for row in conn.execute(f"SELECT session_id, tag FROM session_tags WHERE session_id IN ({placeholders})", session_ids):
        tags_map.setdefault(row["session_id"], []).append(row["tag"])
    for r in results:
        sid = r.get(session_id_key, "")
        meta = meta_map.get(sid, {})
        r["starred"] = meta.get("starred", 0)
        r["archived"] = meta.get("archived", False)
        r["tags"] = tags_map.get(sid, [])
    return results


@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    project = request.args.get("project", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()
    starred = request.args.get("starred", "").strip()
    min_stars = request.args.get("min_stars", "").strip()
    tag = request.args.get("tag", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db()

    where_clauses = ["NOT EXISTS (SELECT 1 FROM session_meta sh WHERE sh.session_id = m.session_id AND sh.hidden = 1)"]
    params = []

    if project:
        where_clauses.append("m.project = ?")
        params.append(project)
    if date_from:
        where_clauses.append("m.timestamp >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("m.timestamp <= ?")
        params.append(date_to + "T23:59:59Z")
    if min_stars:
        try:
            min_stars_int = int(min_stars)
        except ValueError:
            return jsonify({"error": "min_stars must be an integer"}), 400
        where_clauses.append("EXISTS (SELECT 1 FROM session_meta sm WHERE sm.session_id = m.session_id AND sm.starred >= ?)")
        params.append(min_stars_int)
    elif starred == "1":
        where_clauses.append("EXISTS (SELECT 1 FROM session_meta sm WHERE sm.session_id = m.session_id AND sm.starred >= 1)")
    if tag:
        where_clauses.append("EXISTS (SELECT 1 FROM session_tags st WHERE st.session_id = m.session_id AND st.tag = ?)")
        params.append(tag)

    # If no query text and no filters besides the hidden check, return empty
    has_filters = project or date_from or date_to or min_stars or starred == "1" or tag
    if not q and not has_filters:
        return jsonify({"results": [], "total": 0, "page": page})

    where_sql = " AND ".join(where_clauses)

    if q:
        fts_query = q.replace('"', '""')
        count_sql = f"""
            SELECT COUNT(*) FROM messages_fts fts
            JOIN messages m ON m.id = fts.rowid
            WHERE messages_fts MATCH ? AND {where_sql}
        """
        total = conn.execute(count_sql, [fts_query] + params).fetchone()[0]

        results_sql = f"""
            SELECT m.*, snippet(messages_fts, 0, '<mark>', '</mark>', '...', 40) as snippet,
                   snippet(messages_fts, 1, '<mark>', '</mark>', '...', 40) as assistant_snippet
            FROM messages_fts fts
            JOIN messages m ON m.id = fts.rowid
            WHERE messages_fts MATCH ? AND {where_sql}
            ORDER BY m.timestamp DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(results_sql, [fts_query] + params + [per_page, offset]).fetchall()
    else:
        count_sql = f"SELECT COUNT(*) FROM messages m WHERE {where_sql}"
        total = conn.execute(count_sql, params).fetchone()[0]

        results_sql = f"""
            SELECT m.*, substr(m.content, 1, 200) as snippet
            FROM messages m
            WHERE {where_sql}
            ORDER BY m.timestamp DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(results_sql, params + [per_page, offset]).fetchall()

    results = _attach_session_meta(conn, [dict(r) for r in rows])
    conn.close()
    return jsonify({"results": results, "total": total, "page": page, "per_page": per_page})


@app.route("/api/projects")
def projects():
    conn = get_db()
    rows = conn.execute("""
        SELECT project, COUNT(*) as message_count,
               COUNT(DISTINCT session_id) as session_count,
               MIN(timestamp) as first_ts, MAX(timestamp) as last_ts
        FROM messages
        WHERE NOT EXISTS (SELECT 1 FROM session_meta sh WHERE sh.session_id = messages.session_id AND sh.hidden = 1)
        GROUP BY project ORDER BY last_ts DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/sessions")
def sessions():
    project = request.args.get("project", "").strip()
    show_archived = request.args.get("archived", "").strip()
    starred_only = request.args.get("starred", "").strip()
    min_stars = request.args.get("min_stars", "").strip()
    tag = request.args.get("tag", "").strip()
    sort = request.args.get("sort", "date_desc").strip()
    conn = get_db()

    where = ["NOT EXISTS (SELECT 1 FROM session_meta sh WHERE sh.session_id = s.session_id AND sh.hidden = 1)"]
    params = []
    if project:
        projects = [p.strip() for p in project.split(",") if p.strip()]
        if len(projects) == 1:
            where.append("s.project = ?")
            params.append(projects[0])
        elif projects:
            placeholders = ",".join("?" * len(projects))
            where.append(f"s.project IN ({placeholders})")
            params.extend(projects)
    if min_stars:
        try:
            min_stars_int = int(min_stars)
        except ValueError:
            return jsonify({"error": "min_stars must be an integer"}), 400
        where.append("EXISTS (SELECT 1 FROM session_meta sm WHERE sm.session_id = s.session_id AND sm.starred >= ?)")
        params.append(min_stars_int)
    elif starred_only == "1":
        where.append("EXISTS (SELECT 1 FROM session_meta sm WHERE sm.session_id = s.session_id AND sm.starred >= 1)")
    if tag:
        where.append("EXISTS (SELECT 1 FROM session_tags st WHERE st.session_id = s.session_id AND st.tag = ?)")
        params.append(tag)
    if show_archived != "1":
        where.append("NOT EXISTS (SELECT 1 FROM session_meta sm WHERE sm.session_id = s.session_id AND sm.archived = 1)")

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sort_map = {
        "date_desc": "s.last_ts DESC",
        "date_asc": "s.last_ts ASC",
        "stars_desc": "COALESCE(sm2.starred, 0) DESC, s.last_ts DESC",
        "stars_asc": "COALESCE(sm2.starred, 0) ASC, s.last_ts DESC",
    }
    order_sql = sort_map.get(sort, "s.last_ts DESC")
    join_sql = " LEFT JOIN session_meta sm2 ON sm2.session_id = s.session_id" if sort.startswith("stars") else ""
    rows = conn.execute(f"SELECT s.* FROM sessions s{join_sql}{where_sql} ORDER BY {order_sql}", params).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        first_msgs = conn.execute("""
            SELECT content FROM messages WHERE session_id = ? ORDER BY timestamp ASC LIMIT 2
        """, [d["session_id"]]).fetchall()
        first_content = ""
        if first_msgs:
            first_content = first_msgs[0]["content"]
            if first_content.strip() == "/clear" and len(first_msgs) > 1:
                first_content = first_msgs[1]["content"]
        d["first_message"] = first_content[:300]
        result.append(d)

    _attach_session_meta(conn, result)
    conn.close()
    return jsonify(result)


@app.route("/api/session/<session_id>")
def session_detail(session_id):
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", [session_id]).fetchone()
    rows = conn.execute("""
        SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC
    """, [session_id]).fetchall()
    conn.close()
    return jsonify({
        "session": dict(session) if session else {},
        "messages": [dict(r) for r in rows],
    })


@app.route("/api/timeline")
def timeline():
    granularity = request.args.get("granularity", "day")
    conn = get_db()
    hidden_filter = "AND NOT EXISTS (SELECT 1 FROM session_meta sh WHERE sh.session_id = messages.session_id AND sh.hidden = 1)"
    if granularity == "week":
        # Group by ISO week
        rows = conn.execute(f"""
            SELECT strftime('%Y-W%W', timestamp) as period,
                   project, COUNT(*) as count
            FROM messages WHERE timestamp != '' {hidden_filter}
            GROUP BY period, project ORDER BY period
        """).fetchall()
    else:
        rows = conn.execute(f"""
            SELECT substr(timestamp, 1, 10) as period,
                   project, COUNT(*) as count
            FROM messages WHERE timestamp != '' {hidden_filter}
            GROUP BY period, project ORDER BY period
        """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats")
def stats():
    conn = get_db()
    hidden_filter = "WHERE NOT EXISTS (SELECT 1 FROM session_meta sh WHERE sh.session_id = messages.session_id AND sh.hidden = 1)"
    hidden_filter_and = "AND NOT EXISTS (SELECT 1 FROM session_meta sh WHERE sh.session_id = messages.session_id AND sh.hidden = 1)"
    total_messages = conn.execute(f"SELECT COUNT(*) FROM messages {hidden_filter}").fetchone()[0]
    total_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE NOT EXISTS (SELECT 1 FROM session_meta sh WHERE sh.session_id = sessions.session_id AND sh.hidden = 1)").fetchone()[0]
    total_projects = conn.execute(f"SELECT COUNT(DISTINCT project) FROM messages {hidden_filter}").fetchone()[0]

    per_project = conn.execute(f"""
        SELECT project, COUNT(*) as messages, COUNT(DISTINCT session_id) as sessions,
               MIN(timestamp) as first_ts, MAX(timestamp) as last_ts
        FROM messages {hidden_filter} GROUP BY project ORDER BY messages DESC
    """).fetchall()

    most_active = conn.execute(f"""
        SELECT substr(timestamp, 1, 10) as day, COUNT(*) as count
        FROM messages WHERE timestamp != '' {hidden_filter_and}
        GROUP BY day ORDER BY count DESC LIMIT 10
    """).fetchall()

    conn.close()
    return jsonify({
        "total_messages": total_messages,
        "total_sessions": total_sessions,
        "total_projects": total_projects,
        "per_project": [dict(r) for r in per_project],
        "most_active_days": [dict(r) for r in most_active],
    })


@app.route("/api/session/<session_id>/meta")
def session_meta(session_id):
    conn = get_db()
    meta = conn.execute("SELECT starred, archived FROM session_meta WHERE session_id = ?", [session_id]).fetchone()
    tags = [r["tag"] for r in conn.execute("SELECT tag FROM session_tags WHERE session_id = ?", [session_id]).fetchall()]
    conn.close()
    return jsonify({
        "starred": (meta["starred"] or 0) if meta else 0,
        "archived": bool(meta["archived"]) if meta else False,
        "tags": tags,
    })


@app.route("/api/session/<session_id>/star", methods=["PUT"])
def set_star(session_id):
    data = request.get_json() or {}
    rating = data.get("rating")
    conn = get_db()
    row = conn.execute("SELECT starred FROM session_meta WHERE session_id = ?", [session_id]).fetchone()
    if rating is not None:
        # Explicit rating provided: if same as current, clear it; otherwise set it
        try:
            rating = max(0, min(5, int(rating)))
        except (ValueError, TypeError):
            conn.close()
            return jsonify({"error": "rating must be an integer 0-5"}), 400
        if row and row["starred"] == rating:
            new_val = 0
        else:
            new_val = rating
    else:
        # Legacy toggle behavior
        new_val = 0 if (row and row["starred"]) else 1
    if row:
        conn.execute("UPDATE session_meta SET starred = ? WHERE session_id = ?", [new_val, session_id])
    else:
        conn.execute("INSERT INTO session_meta (session_id, starred, archived) VALUES (?, ?, 0)", [session_id, new_val])
    conn.commit()
    conn.close()
    return jsonify({"starred": new_val})


@app.route("/api/session/<session_id>/archive", methods=["PUT"])
def toggle_archive(session_id):
    conn = get_db()
    row = conn.execute("SELECT archived FROM session_meta WHERE session_id = ?", [session_id]).fetchone()
    if row:
        new_val = 0 if row["archived"] else 1
        conn.execute("UPDATE session_meta SET archived = ? WHERE session_id = ?", [new_val, session_id])
    else:
        new_val = 1
        conn.execute("INSERT INTO session_meta (session_id, starred, archived) VALUES (?, 0, 1)", [session_id])
    conn.commit()
    conn.close()
    return jsonify({"archived": bool(new_val)})


@app.route("/api/session/<session_id>/hide", methods=["PUT"])
def hide_session(session_id):
    conn = get_db()
    row = conn.execute("SELECT hidden FROM session_meta WHERE session_id = ?", [session_id]).fetchone()
    if row:
        conn.execute("UPDATE session_meta SET hidden = 1 WHERE session_id = ?", [session_id])
    else:
        conn.execute("INSERT INTO session_meta (session_id, starred, archived, hidden) VALUES (?, 0, 0, 1)", [session_id])
    conn.commit()
    conn.close()
    return jsonify({"hidden": True})


@app.route("/api/session/<session_id>/unhide", methods=["PUT"])
def unhide_session(session_id):
    conn = get_db()
    conn.execute("UPDATE session_meta SET hidden = 0 WHERE session_id = ?", [session_id])
    conn.commit()
    conn.close()
    return jsonify({"hidden": False})


@app.route("/api/deleted")
def deleted_sessions():
    """List hidden/deleted sessions with same filters as /api/sessions."""
    project = request.args.get("project", "").strip()
    starred_only = request.args.get("starred", "").strip()
    min_stars = request.args.get("min_stars", "").strip()
    tag = request.args.get("tag", "").strip()
    sort = request.args.get("sort", "date_desc").strip()
    conn = get_db()

    where = ["EXISTS (SELECT 1 FROM session_meta sh WHERE sh.session_id = s.session_id AND sh.hidden = 1)"]
    params = []
    if project:
        projects = [p.strip() for p in project.split(",") if p.strip()]
        if len(projects) == 1:
            where.append("s.project = ?")
            params.append(projects[0])
        elif projects:
            placeholders = ",".join("?" * len(projects))
            where.append(f"s.project IN ({placeholders})")
            params.extend(projects)
    if min_stars:
        try:
            min_stars_int = int(min_stars)
        except ValueError:
            return jsonify({"error": "min_stars must be an integer"}), 400
        where.append("EXISTS (SELECT 1 FROM session_meta sm WHERE sm.session_id = s.session_id AND sm.starred >= ?)")
        params.append(min_stars_int)
    elif starred_only == "1":
        where.append("EXISTS (SELECT 1 FROM session_meta sm WHERE sm.session_id = s.session_id AND sm.starred >= 1)")
    if tag:
        where.append("EXISTS (SELECT 1 FROM session_tags st WHERE st.session_id = s.session_id AND st.tag = ?)")
        params.append(tag)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sort_map = {
        "date_desc": "s.last_ts DESC",
        "date_asc": "s.last_ts ASC",
        "stars_desc": "COALESCE(sm2.starred, 0) DESC, s.last_ts DESC",
        "stars_asc": "COALESCE(sm2.starred, 0) ASC, s.last_ts DESC",
    }
    order_sql = sort_map.get(sort, "s.last_ts DESC")
    join_sql = " LEFT JOIN session_meta sm2 ON sm2.session_id = s.session_id" if sort.startswith("stars") else ""
    rows = conn.execute(f"SELECT s.* FROM sessions s{join_sql}{where_sql} ORDER BY {order_sql}", params).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        first_msgs = conn.execute("""
            SELECT content FROM messages WHERE session_id = ? ORDER BY timestamp ASC LIMIT 2
        """, [d["session_id"]]).fetchall()
        first_content = ""
        if first_msgs:
            first_content = first_msgs[0]["content"]
            if first_content.strip() == "/clear" and len(first_msgs) > 1:
                first_content = first_msgs[1]["content"]
        d["first_message"] = first_content[:300]
        result.append(d)

    _attach_session_meta(conn, result)
    conn.close()
    return jsonify(result)


@app.route("/api/deleted/projects")
def deleted_projects():
    """List projects that have at least one hidden session."""
    conn = get_db()
    rows = conn.execute("""
        SELECT s.project, COUNT(*) as session_count, SUM(s.message_count) as message_count,
               MIN(s.first_ts) as first_ts, MAX(s.last_ts) as last_ts
        FROM sessions s
        WHERE EXISTS (SELECT 1 FROM session_meta sh WHERE sh.session_id = s.session_id AND sh.hidden = 1)
        GROUP BY s.project ORDER BY last_ts DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/session/<session_id>/tags", methods=["PUT"])
def set_tags(session_id):
    data = request.get_json() or {}
    tags = data.get("tags", [])
    conn = get_db()
    conn.execute("DELETE FROM session_tags WHERE session_id = ?", [session_id])
    for tag in tags:
        tag = tag.strip()
        if tag:
            conn.execute("INSERT OR IGNORE INTO session_tags (session_id, tag) VALUES (?, ?)", [session_id, tag])
    conn.commit()
    result_tags = [r["tag"] for r in conn.execute("SELECT tag FROM session_tags WHERE session_id = ?", [session_id]).fetchall()]
    conn.close()
    return jsonify({"tags": result_tags})


@app.route("/api/tags")
def all_tags():
    conn = get_db()
    rows = conn.execute("SELECT tag, COUNT(*) as count FROM session_tags GROUP BY tag ORDER BY count DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/backup", methods=["POST"])
def backup():
    backup_dir = Path.home() / "claudeChatBackups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    backup_path = backup_dir / f"{timestamp}_transcripts.db"
    shutil.copy2(str(DB_PATH), str(backup_path))
    return jsonify({"path": str(backup_path)})


@app.route("/api/reindex", methods=["POST"])
def reindex():
    stats = run_index(full_rebuild=False)
    return jsonify(stats)


if __name__ == "__main__":
    print("Running initial index...")
    stats = run_index()
    print(f"Indexed {stats['total_messages']} messages in {stats['elapsed_seconds']}s")
    scan = _scan_live_from_disk()
    print(f"Scanned {scan['scanned']} recent transcripts "
          f"({scan['added_active']} active, {scan['added_closed']} closed)")
    print("Starting server at http://localhost:5111")
    app.run(host="127.0.0.1", port=5111, debug=False)
