"""Flask server for Claude Chats search app."""

import sqlite3
from flask import Flask, jsonify, request, render_template
from indexer import run_index, DB_PATH

app = Flask(__name__)


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
            SELECT m.*, snippet(messages_fts, 0, '<mark>', '</mark>', '...', 40) as snippet
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
        first_msg = conn.execute("""
            SELECT content FROM messages WHERE session_id = ? ORDER BY timestamp ASC LIMIT 1
        """, [d["session_id"]]).fetchone()
        d["first_message"] = first_msg["content"][:300] if first_msg else ""
        result.append(d)

    _attach_session_meta(conn, result)
    conn.close()
    return jsonify(result)


@app.route("/api/session/<session_id>")
def session_detail(session_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC
    """, [session_id]).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


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
        first_msg = conn.execute("""
            SELECT content FROM messages WHERE session_id = ? ORDER BY timestamp ASC LIMIT 1
        """, [d["session_id"]]).fetchone()
        d["first_message"] = first_msg["content"][:300] if first_msg else ""
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


@app.route("/api/reindex", methods=["POST"])
def reindex():
    stats = run_index(full_rebuild=False)
    return jsonify(stats)


if __name__ == "__main__":
    print("Running initial index...")
    stats = run_index()
    print(f"Indexed {stats['total_messages']} messages in {stats['elapsed_seconds']}s")
    print("Starting server at http://localhost:5111")
    app.run(host="127.0.0.1", port=5111, debug=False)
