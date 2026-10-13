"""
session_store.py — per-session in-memory DuckDB for "no-credential" mode.

When the Tableau extension can't (or shouldn't) connect to a live database, it
ships the worksheet data directly via /load-session. We dump those rows into a
short-lived DuckDB instance keyed by session_id, then run Claude-generated SQL
against it.

Sessions are evicted after SESSION_TTL_SECONDS of inactivity.
"""

import time
import threading
import logging
from typing import Any

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 60 * 60  # 1h — generous for a single dashboard sitting

# session_id -> {"conn": duckdb.Connection, "tables": [str], "last_used": float}
_SESSIONS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _evict_stale():
    """Drop sessions older than SESSION_TTL_SECONDS. Cheap; called on each touch."""
    now = time.time()
    stale = [sid for sid, s in _SESSIONS.items() if now - s["last_used"] > SESSION_TTL_SECONDS]
    for sid in stale:
        try:
            _SESSIONS[sid]["conn"].close()
        except Exception:
            pass
        _SESSIONS.pop(sid, None)
        logger.info(f"Evicted stale session {sid}")


def _safe_table_name(name: str) -> str:
    """DuckDB identifier — strip anything that isn't alnum/underscore."""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name).strip("_")
    if not safe:
        safe = "sheet"
    if safe[0].isdigit():
        safe = "t_" + safe
    return safe.lower()


def load_session(session_id: str, sheets: list[dict]) -> dict:
    """
    Materialize each worksheet snapshot as a DuckDB table.

    sheets schema (from extension):
      [{"name": "Regional Revenue",
        "columns": ["Region", "Net Revenue", ...],
        "rows": [["West", 1234.5, ...], ...]}]
    """
    with _LOCK:
        _evict_stale()

        # Fresh conn per session — keeps queries isolated, simpler eviction
        conn = duckdb.connect(database=":memory:")
        loaded_tables = []

        for sheet in sheets:
            sheet_name = sheet.get("name", "sheet")
            cols = sheet.get("columns", [])
            rows = sheet.get("rows", [])
            if not cols or not rows:
                continue

            table_name = _safe_table_name(sheet_name)
            try:
                df = pd.DataFrame(rows, columns=cols)
                # DuckDB can register a DataFrame zero-copy
                conn.register(f"_tmp_{table_name}", df)
                conn.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM _tmp_{table_name}')
                conn.unregister(f"_tmp_{table_name}")
                loaded_tables.append(table_name)
            except Exception as e:
                logger.warning(f"Failed to load sheet '{sheet_name}': {e}")

        _SESSIONS[session_id] = {
            "conn": conn,
            "tables": loaded_tables,
            "last_used": time.time(),
        }
        logger.info(f"Session {session_id} loaded with tables: {loaded_tables}")
        return {"session_id": session_id, "tables": loaded_tables}


def get_session(session_id: str) -> dict | None:
    """Touch + return a session's connection + table list. None if missing/expired."""
    with _LOCK:
        _evict_stale()
        s = _SESSIONS.get(session_id)
        if not s:
            return None
        s["last_used"] = time.time()
        return s


def execute(session_id: str, sql: str) -> list[dict]:
    """Run SQL against the session's DuckDB. Returns list of row dicts."""
    s = get_session(session_id)
    if not s:
        raise KeyError(f"No active session: {session_id}")
    cur = s["conn"].execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_schema(session_id: str) -> str:
    """Return a human-readable schema dump for prompt use."""
    s = get_session(session_id)
    if not s:
        return ""
    lines = []
    for table in s["tables"]:
        cur = s["conn"].execute(f'DESCRIBE "{table}"')
        cols = cur.fetchall()
        col_text = ", ".join(f'{c[0]} ({c[1]})' for c in cols)
        lines.append(f'Table "{table}": {col_text}')
    return "\n".join(lines)


def drop_session(session_id: str) -> bool:
    with _LOCK:
        s = _SESSIONS.pop(session_id, None)
        if not s:
            return False
        try:
            s["conn"].close()
        except Exception:
            pass
        return True
