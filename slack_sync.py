"""Manual Slack sync: pulls only the authenticated user's own messages into
slack_messages. Read-only by design — no method in this module ever writes
to Slack. Token is loaded from SLACK_USER_TOKEN env var by the caller.

Sync model: enumerate every channel/DM/group the user belongs to via
users.conversations, fetch conversations.history since last_sync_ts, drop any
message whose user != self_user_id. For threads where the user authored a
reply, also fetch conversations.replies.
"""

import sqlite3
import time
import urllib.parse
import urllib.request
import urllib.error
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

SLACK_API = "https://slack.com/api"
DEFAULT_LOOKBACK_DAYS = 30  # First-ever sync goes back this far.
RUN_TIMEOUT_SECONDS = 5 * 60  # Cap any single sync click.
USER_AGENT = "claudechats-slack-sync/1.0"


class SlackError(Exception):
    pass


def _api(method: str, token: str, params: dict | None = None) -> dict:
    """Call a Slack Web API method with token. Honors Retry-After on 429."""
    params = dict(params or {})
    url = f"{SLACK_API}/{method}"
    body = urllib.parse.urlencode(params).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
    }
    for attempt in range(5):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After", "1"))
                time.sleep(retry_after + 1)
                continue
            raise SlackError(f"{method} HTTP {e.code}")
        except urllib.error.URLError as e:
            raise SlackError(f"{method} network error: {e.reason}")

        if not data.get("ok"):
            err = data.get("error", "unknown_error")
            raise SlackError(f"{method}: {err}")
        return data
    raise SlackError(f"{method}: rate-limited after retries")


def _meta_get(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM slack_sync_meta WHERE key = ?", [key]).fetchone()
    return row[0] if row else ""


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO slack_sync_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [key, value],
    )


def _resolve_self(conn: sqlite3.Connection, token: str) -> str:
    """Return self_user_id, verifying it matches the cached value if any."""
    auth = _api("auth.test", token)
    self_id = auth.get("user_id", "")
    if not self_id:
        raise SlackError("auth.test did not return user_id")
    cached = _meta_get(conn, "self_user_id")
    if cached and cached != self_id:
        raise SlackError(
            f"token identity changed (was {cached}, now {self_id}); aborting sync"
        )
    if not cached:
        _meta_set(conn, "self_user_id", self_id)
    return self_id


def _list_conversations(token: str) -> list[dict]:
    """Return every channel/DM/group the user is a member of."""
    out: list[dict] = []
    cursor = ""
    while True:
        params = {
            "types": "public_channel,private_channel,mpim,im",
            "limit": "200",
            "exclude_archived": "true",
        }
        if cursor:
            params["cursor"] = cursor
        data = _api("users.conversations", token, params)
        out.extend(data.get("channels", []))
        cursor = (data.get("response_metadata") or {}).get("next_cursor", "")
        if not cursor:
            break
    return out


def _user_name_cache(token: str) -> dict:
    """Lazy cache of user_id -> display name. Populated on demand."""
    return {}


def _resolve_user_name(token: str, user_id: str, cache: dict) -> str:
    if not user_id:
        return ""
    if user_id in cache:
        return cache[user_id]
    try:
        data = _api("users.info", token, {"user": user_id})
        u = data.get("user", {}) or {}
        profile = u.get("profile", {}) or {}
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or u.get("name")
            or user_id
        )
    except SlackError:
        name = user_id
    cache[user_id] = name
    return name


def _channel_label(conv: dict, token: str, user_cache: dict) -> tuple[str, str]:
    """Return (project_label, friendly_channel_name) for a conversation."""
    if conv.get("is_im"):
        peer = conv.get("user", "")
        peer_name = _resolve_user_name(token, peer, user_cache)
        return (f"slack:dm:{peer_name}", f"dm:{peer_name}")
    if conv.get("is_mpim"):
        name = conv.get("name", conv.get("id", ""))
        return (f"slack:mpim:{name}", f"mpim:{name}")
    name = conv.get("name", conv.get("id", ""))
    prefix = "#" if not conv.get("is_private") else "🔒"
    return (f"slack:{prefix}{name}", f"{prefix}{name}")


def _slack_ts_to_iso(ts: str) -> str:
    """Convert Slack ts ('1714512345.123456') to ISO 8601 UTC string."""
    epoch = float(ts)
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _clean_text(text: str, token: str, user_cache: dict) -> str:
    """Resolve <@Uxxx> mentions to names and strip <url> brackets."""
    if not text:
        return ""
    out = []
    i = 0
    while i < len(text):
        if text[i] == "<":
            end = text.find(">", i)
            if end == -1:
                out.append(text[i])
                i += 1
                continue
            inner = text[i + 1 : end]
            if inner.startswith("@U") or inner.startswith("@W"):
                user_id = inner[1:].split("|")[0]
                out.append("@" + _resolve_user_name(token, user_id, user_cache))
            elif inner.startswith("#C"):
                parts = inner[1:].split("|")
                out.append("#" + (parts[1] if len(parts) > 1 else parts[0]))
            elif "|" in inner:
                # <url|label> -> label
                out.append(inner.split("|", 1)[1])
            else:
                out.append(inner)
            i = end + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _fetch_history(
    token: str, channel_id: str, oldest_ts: str
) -> tuple[list[dict], list[str]]:
    """Return (messages, thread_parents). thread_parents is the list of ts values
    for messages with reply_count > 0 (caller may want to fetch replies)."""
    msgs: list[dict] = []
    threads: list[str] = []
    cursor = ""
    while True:
        params = {
            "channel": channel_id,
            "limit": "200",
            "oldest": oldest_ts or "0",
            "inclusive": "false",
        }
        if cursor:
            params["cursor"] = cursor
        try:
            data = _api("conversations.history", token, params)
        except SlackError as e:
            # not_in_channel / missing_scope on a single channel — skip it
            if "not_in_channel" in str(e) or "missing_scope" in str(e):
                return [], []
            raise
        for m in data.get("messages", []):
            msgs.append(m)
            if m.get("reply_count", 0) and m.get("thread_ts") == m.get("ts"):
                threads.append(m["ts"])
        cursor = (data.get("response_metadata") or {}).get("next_cursor", "")
        if not data.get("has_more") or not cursor:
            break
    return msgs, threads


def _fetch_replies(token: str, channel_id: str, thread_ts: str) -> list[dict]:
    msgs: list[dict] = []
    cursor = ""
    while True:
        params = {"channel": channel_id, "ts": thread_ts, "limit": "200"}
        if cursor:
            params["cursor"] = cursor
        try:
            data = _api("conversations.replies", token, params)
        except SlackError as e:
            if "thread_not_found" in str(e) or "not_in_channel" in str(e):
                return []
            raise
        for m in data.get("messages", []):
            # Skip the parent (already captured by history)
            if m.get("ts") == thread_ts:
                continue
            msgs.append(m)
        cursor = (data.get("response_metadata") or {}).get("next_cursor", "")
        if not cursor:
            break
    return msgs


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Idempotent — safe to call before any read/write."""
    from indexer import init_db
    init_db(conn)


def run_slack_sync(db_path: Path, token: str) -> dict:
    """Pull self-authored Slack messages since last sync. Returns stats dict."""
    if not token:
        raise SlackError("SLACK_USER_TOKEN is empty")

    t_start = time.time()
    deadline = t_start + RUN_TIMEOUT_SECONDS

    conn = sqlite3.connect(str(db_path))
    _ensure_tables(conn)
    self_id = _resolve_self(conn, token)

    last_sync_ts = _meta_get(conn, "last_sync_ts")
    if not last_sync_ts:
        # First run: bound the lookback so we don't pull the whole archive.
        cutoff = datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        last_sync_ts = f"{cutoff.timestamp():.6f}"

    user_cache = _user_name_cache(token)
    conversations = _list_conversations(token)

    inserted = 0
    skipped = 0
    highest_ts_seen = last_sync_ts
    truncated = False

    for conv in conversations:
        if time.time() > deadline:
            truncated = True
            break
        channel_id = conv.get("id", "")
        if not channel_id:
            continue
        project, channel_name = _channel_label(conv, token, user_cache)
        try:
            history, thread_parents = _fetch_history(token, channel_id, last_sync_ts)
        except SlackError:
            continue

        candidates = list(history)
        for parent_ts in thread_parents:
            if time.time() > deadline:
                truncated = True
                break
            try:
                candidates.extend(_fetch_replies(token, channel_id, parent_ts))
            except SlackError:
                continue

        for m in candidates:
            if m.get("user") != self_id:
                continue
            ts = m.get("ts", "")
            if not ts:
                continue
            text = m.get("text", "")
            if not text:
                continue  # ignore file-only / empty body messages
            cleaned = _clean_text(text, token, user_cache)
            iso = _slack_ts_to_iso(ts)
            edited_ts = (m.get("edited") or {}).get("ts", "")
            edited_iso = _slack_ts_to_iso(edited_ts) if edited_ts else ""
            cur = conn.execute(
                """INSERT OR IGNORE INTO slack_messages
                   (slack_ts, channel_id, channel_name, project, timestamp,
                    content, edited_at, thread_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [ts, channel_id, channel_name, project, iso, cleaned,
                 edited_iso, m.get("thread_ts", "")],
            )
            if cur.rowcount:
                inserted += 1
            else:
                # Already present — update content if edited since.
                conn.execute(
                    """UPDATE slack_messages
                       SET content = ?, edited_at = ?
                       WHERE slack_ts = ? AND COALESCE(edited_at, '') < ?""",
                    [cleaned, edited_iso, ts, edited_iso or ""],
                )
                skipped += 1
            if float(ts) > float(highest_ts_seen or 0):
                highest_ts_seen = ts

    if highest_ts_seen and not truncated:
        _meta_set(conn, "last_sync_ts", highest_ts_seen)
    elif highest_ts_seen and truncated:
        # Partial progress — still advance the cursor so the next click resumes.
        _meta_set(conn, "last_sync_ts", highest_ts_seen)
    _meta_set(conn, "last_sync_completed_at",
              datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    conn.commit()
    conn.close()

    return {
        "inserted": inserted,
        "skipped": skipped,
        "truncated": truncated,
        "elapsed_seconds": round(time.time() - t_start, 2),
        "last_sync": highest_ts_seen,
    }


def get_status(db_path: Path) -> dict:
    """Read sync metadata for the UI status display."""
    conn = sqlite3.connect(str(db_path))
    _ensure_tables(conn)
    last_sync_ts = _meta_get(conn, "last_sync_ts")
    last_completed = _meta_get(conn, "last_sync_completed_at")
    count_row = conn.execute("SELECT COUNT(*) FROM slack_messages").fetchone()
    conn.close()
    last_sync_iso = ""
    if last_sync_ts:
        try:
            last_sync_iso = _slack_ts_to_iso(last_sync_ts)
        except (ValueError, TypeError):
            last_sync_iso = ""
    return {
        "last_sync_cursor": last_sync_iso,
        "last_sync_completed_at": last_completed,
        "message_count": count_row[0] if count_row else 0,
    }
