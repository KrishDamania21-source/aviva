"""
n8n_broker.py — credential-broker pattern.

Aviva never holds DB credentials. Instead it POSTs {connection, sql} to a single
n8n webhook. n8n looks up the named credential in its vault and executes the
query against the right database (Snowflake, BigQuery, Postgres, etc.).

The n8n workflow JSON is in n8n_workflows/execute_query.json.
"""

import logging
import httpx

from config import N8N_QUERY_WEBHOOK, N8N_QUERY_SECRET, KNOWN_CONNECTIONS

logger = logging.getLogger(__name__)


class BrokerError(Exception):
    pass


def is_configured() -> bool:
    """True iff the n8n broker URL is set in env. Cheap check used by /query."""
    return bool(N8N_QUERY_WEBHOOK)


def list_connections() -> list[dict]:
    """Names + labels for the extension's connection picker."""
    return [
        {"name": name, "label": meta.get("label", name), "type": meta.get("type", "unknown")}
        for name, meta in KNOWN_CONNECTIONS.items()
    ]


async def fetch_schema(connection: str) -> str:
    """
    Ask n8n for the connection's schema dump. The workflow handles the
    information_schema query per DB dialect. Returns a printable string
    Aviva pastes into the SQL-gen prompt.

    PLACEHOLDER — the n8n workflow needs a "schema" mode branch. Until that
    exists this just returns an empty string and SQL gen falls back to the
    workbook context for field names.
    """
    if not is_configured():
        return ""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                N8N_QUERY_WEBHOOK,
                headers=_headers(),
                json={"mode": "schema", "connection": connection},
            )
            if r.status_code >= 300:
                logger.warning(f"n8n schema fetch returned {r.status_code}: {r.text[:200]}")
                return ""
            payload = r.json()
            return payload.get("schema", "")
    except Exception as e:
        logger.warning(f"n8n schema fetch failed: {e}")
        return ""


async def execute(connection: str, sql: str) -> list[dict]:
    """Execute SQL via n8n broker. Raises BrokerError on failure."""
    if not is_configured():
        raise BrokerError("N8N_QUERY_WEBHOOK is not configured")
    if connection not in KNOWN_CONNECTIONS:
        raise BrokerError(f"Unknown connection: {connection}")

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                N8N_QUERY_WEBHOOK,
                headers=_headers(),
                json={"mode": "query", "connection": connection, "sql": sql},
            )
    except Exception as e:
        raise BrokerError(f"n8n request failed: {e}")

    if r.status_code >= 300:
        raise BrokerError(f"n8n returned {r.status_code}: {r.text[:300]}")

    try:
        payload = r.json()
    except Exception:
        raise BrokerError("n8n returned non-JSON body")

    if "error" in payload:
        raise BrokerError(payload["error"])

    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise BrokerError("n8n response missing 'rows' array")
    return rows


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if N8N_QUERY_SECRET:
        h["X-Aviva-Secret"] = N8N_QUERY_SECRET
    return h
