import os
import re
import json
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic
from sqlalchemy import create_engine, text
from config import DATABASE_URL, MODEL_NAME
from indexer import search_index, response_text
from sql_guard import check_sql, BLOCKED_MESSAGE
import session_store
import n8n_broker

# Logging — surfaces errors instead of swallowing them silently
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Manually load .env since load_dotenv has issues
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                os.environ[key] = value

def _get_client():
    """Return the Anthropic client, initializing it on first use.
    Deferred so a missing key crashes at query time, not at import time —
    which lets uvicorn bind its port before any error surfaces."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set. Add it to your .env file or Render environment variables.")
    return Anthropic(api_key=api_key)


_ENGINE = None


def _get_engine():
    """One shared engine per process. Creating an engine per query leaked a pooled
    connection each time and hit Supabase's 15-client session-pooler limit after ~7 questions."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(DATABASE_URL, pool_size=3, max_overflow=2, pool_pre_ping=True)
    return _ENGINE


def get_table_schema(table_name: str) -> str:
    """Get the schema of a table from Postgres information_schema."""
    with _get_engine().connect() as conn:
        result = conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = :table ORDER BY ordinal_position"
        ), {"table": table_name})
        columns = result.fetchall()

    schema_lines = [f"  {col[0]} ({col[1]})" for col in columns]
    return "\n".join(schema_lines)


def _workbook_context_section(context: dict) -> str:
    """Format workbook field metadata into a prompt section Claude can use."""
    lines = ["\nDashboard context — use this to understand field names, business terminology, and filter values:"]

    # Dashboard parameters first — they often set the scope of what the user sees
    for p in context.get("parameters", []):
        cur = f" = {p.get('currentValue')}" if p.get("currentValue") is not None else ""
        lines.append(f"Parameter: {p['name']} ({p.get('dataType', '?')}){cur}")

    for sheet in context.get("sheets", []):
        lines.append(f"\nSheet: {sheet['name']}")
        for f in sheet.get("fields", []):
            line = f"  - {f['name']} ({f.get('role', '?')}, {f.get('dataType', '?')})"
            if f.get("isCalc"):
                line += " [calculated field]"
            if f.get("description"):
                line += f" — {f['description']}"
            if f.get("formula"):
                line += f" — formula: {f['formula']}"
            if f.get("samples"):
                line += f" — e.g. {', '.join(str(s) for s in f['samples'][:6])}"
            lines.append(line)
        for filt in sheet.get("currentFilters", []):
            if "values" in filt:
                lines.append(f"  Dashboard currently filtered: {filt['field']} in [{', '.join(filt['values'])}]")
            elif "range" in filt:
                lines.append(f"  Dashboard currently filtered: {filt['field']} between {filt['range'][0]} and {filt['range'][1]}")
    return "\n".join(lines)


def generate_sql(question: str, table_name: str, schema: str, workbook_context: dict | None = None) -> str:
    """Ask Claude to generate SQL for the question."""
    context_section = _workbook_context_section(workbook_context) if workbook_context else ""

    prompt = f"""You are a SQL expert. Generate a PostgreSQL query to answer this question.

Table: {table_name}
Schema:
{schema}
{context_section}
Question: {question}

IMPORTANT: PostgreSQL is case-sensitive. Column names must be wrapped in double quotes and spelled exactly as shown in the schema above (e.g. "product_title", "ordered_revenue"). Never reference a column without double quotes.

Return ONLY the SQL query, nothing else. No explanation, no markdown, just the raw SQL."""

    response = _get_client().messages.create(
        model=MODEL_NAME,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    return _strip_fences(response_text(response))


def fix_sql(question: str, table_name: str, schema: str, failed_sql: str, error: str) -> str:
    """Self-healing: show Claude the failing SQL + database error, ask for a corrected query."""
    prompt = f"""This PostgreSQL query failed. Return a corrected query that answers the question.

Table: {table_name}
Schema:
{schema}

Question: {question}

Failed SQL:
{failed_sql}

Database error:
{error}

Column names must be wrapped in double quotes and spelled exactly as shown in the schema.
The query must be a single read-only SELECT (or WITH ... SELECT) statement.
Return ONLY the corrected SQL, nothing else. No explanation, no markdown."""

    response = _get_client().messages.create(
        model=MODEL_NAME,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return _strip_fences(response_text(response))


def _strip_fences(text_: str) -> str:
    """Remove ```sql ... ``` wrapping if Claude adds it despite instructions."""
    s = text_.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rsplit("```", 1)[0]
    return s.strip()


def _corrupt_sql(sql: str, schema: str) -> str:
    """Demo only: misspell the first real column name in the query (swap its last two
    letters, e.g. "total_amount" -> "total_amoutn") so execution fails and the retry runs."""
    columns = {line.strip().split(" (")[0] for line in schema.splitlines() if line.strip()}
    for ident in re.findall(r'"([^"]+)"', sql):
        if ident in columns and len(ident) > 2:
            bad = ident[:-2] + ident[-1] + ident[-2]
            return sql.replace(f'"{ident}"', f'"{bad}"')
    logger.info("DEMO: no quoted column found to corrupt; SQL unchanged")
    return sql


def _short_error(e: Exception) -> str:
    """Database error text for the retry prompt — the driver message, not the SQLAlchemy wrapper."""
    msg = str(getattr(e, "orig", None) or e)
    return msg.split("\n[SQL:")[0].strip()[:600]


def execute_sql(sql: str) -> list:
    """Execute SQL against the Postgres database."""
    with _get_engine().connect() as conn:
        # Second layer behind sql_guard: Postgres itself refuses any write
        conn.execute(text("SET TRANSACTION READ ONLY"))
        result = conn.execute(text(sql))
        keys = result.keys()
        rows = [dict(zip(keys, row)) for row in result.fetchall()]
    return rows


def format_answer(question: str, sql: str, results: list) -> str:
    """Ask Claude to format the results as a natural language answer."""
    if results:
        results_text = "\n".join([str(row) for row in results])
    else:
        results_text = "No results found"

    prompt = f"""You are a helpful analytics assistant. Format this query result as a clear, natural language answer.

Question: {question}
SQL Query: {sql}
Results: {results_text}

Provide a concise, friendly answer based on the results. Use plain text only - no markdown formatting or special characters."""

    response = _get_client().messages.create(
        model=MODEL_NAME,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    return response_text(response).strip()


def extract_filters(question: str, table_name: str, workbook_context: dict | None = None) -> list:
    """Use Claude to extract any dashboard filter intent from the question.

    Returns a list of filter dicts: [{"field": "Region", "values": ["West"]}]
    Each filter maps directly to a Tableau worksheet applyFilterAsync() call.
    """
    # Build filter field hints — prefer live workbook metadata over hardcoded fallbacks
    if workbook_context:
        dim_parts = []
        for sheet in workbook_context.get("sheets", []):
            for f in sheet.get("fields", []):
                if f.get("role") == "dimension":
                    hint_item = f["name"]
                    samples = f.get("samples", [])
                    if samples:
                        hint_item += f" (e.g. {', '.join(str(s) for s in samples[:4])})"
                    dim_parts.append(hint_item)
        # Deduplicate while preserving order
        seen = set()
        unique_parts = []
        for p in dim_parts:
            key = p.split(" (")[0]
            if key not in seen:
                seen.add(key)
                unique_parts.append(p)
        hint = ", ".join(unique_parts) if unique_parts else "any relevant field"
    else:
        field_hints = {
            "sales_data": (
                "Region (e.g. West, East, North, South), "
                "Category (e.g. Widgets, Gadgets), "
                "Sales_Rep (e.g. Sarah Chen), "
                "Customer_Name"
            ),
            "marketing_data": (
                "Channel (e.g. Google Ads, Facebook, Instagram, LinkedIn, Email), "
                "Campaign_Name, "
                "Month (e.g. January, February)"
            ),
            "facebook_ads": (
                "Campaign_Name (e.g. Spring Sale 2024, Brand Awareness Q1, Retargeting - Cart Abandoners), "
                "Ad_Set_Name (e.g. US - 25-44, UK - 25-44, CA - All Ages), "
                "Placement (e.g. Feed, Stories, Reels, Audience Network), "
                "Objective (e.g. Conversions, Reach, Video Views)"
            ),
            "vendor_central": (
                "ASIN (e.g. B08N5WRWNW), "
                "Product_Title (e.g. PowerBlend Pro Protein Powder), "
                "Category (e.g. Nutrition, Supplements, Hydration, Fitness Equipment, Recovery), "
                "Replenishment_Status (e.g. In Stock, Low Stock, Out of Stock)"
            ),
        }
        hint = field_hints.get(table_name, "any relevant field")

    prompt = f"""You are analyzing a natural language question to identify filters that should be applied to a data dashboard.

Question: "{question}"
Data source: {table_name}
Available filter fields: {hint}

Extract any specific filters that are explicitly mentioned or strongly implied.
Return a JSON object in this exact format:
{{
  "filters": [
    {{"field": "Region", "values": ["West"]}},
    {{"field": "Category", "values": ["Widgets"]}}
  ]
}}

Rules:
- Only include filters clearly stated or implied in the question.
- "values" must be a non-empty list of strings.
- If no filters apply, return: {{"filters": []}}
- Return ONLY the JSON, no explanation."""

    try:
        response = _get_client().messages.create(
            model=MODEL_NAME,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response_text(response).strip()
        parsed = json.loads(raw)
        return parsed.get("filters", [])
    except Exception as e:
        logger.warning(f"Filter extraction failed: {e}")
        return []


def answer_question(
    question: str,
    workbook_context: dict | None = None,
    connection: str | None = None,
    session_id: str | None = None,
    simulate_bad_sql: bool = False,
    extract_tableau_filters: bool = True,
) -> dict:
    """End-to-end pipeline to answer a user question.

    Three execution modes, in priority order:
      1. n8n broker — if `connection` is given AND the broker is configured.
         Runs SQL against the user's live database via stored n8n credentials.
      2. DuckDB session — if `session_id` is given AND a session is loaded.
         Runs SQL against in-memory data pushed from the Tableau extension.
      3. Supabase fallback — original behavior. Used when neither of the above
         applies (e.g. local dev, demo dashboards).
    """
    try:
        mode = "supabase"
        table_name = None
        schema = ""
        routing = None

        # ── Mode selection ──────────────────────────────────────────────────
        if connection and n8n_broker.is_configured():
            mode = "broker"
            table_name = connection  # for display purposes
            # Schema fetch is best-effort; workbook_context covers the gap.
            try:
                schema = asyncio.run(n8n_broker.fetch_schema(connection)) or ""
            except RuntimeError:
                # already in event loop (e.g. inside FastAPI) — skip the async hop
                schema = ""
            if not schema:
                schema = "(schema not provided — rely on dashboard context for field names)"

        elif session_id and session_store.get_session(session_id):
            mode = "session"
            schema = session_store.get_schema(session_id)
            # Pick the first table as a "name" for display + filter prompt
            sess = session_store.get_session(session_id)
            table_name = sess["tables"][0] if sess and sess["tables"] else "session"

        else:
            # Original Supabase routing
            relevant_sources = search_index(question, top_k=1, workbook_context=workbook_context)
            if not relevant_sources:
                return _empty_response("I could not find a relevant data source for that question.")
            table_name = relevant_sources[0]["table_name"]
            routing = {
                "table": table_name,
                "reason": relevant_sources[0].get("reason", ""),
                "runner_up": relevant_sources[0].get("runner_up"),
            }
            schema = get_table_schema(table_name)

        logger.info(f"Mode={mode}  table/connection={table_name}")

        # ── Generate SQL ────────────────────────────────────────────────────
        sql = generate_sql(question, table_name, schema, workbook_context=workbook_context)
        logger.info(f"Generated SQL: {sql}")

        if simulate_bad_sql:
            sql = _corrupt_sql(sql, schema)
            logger.info(f"DEMO: corrupted first SQL: {sql}")

        def blocked(bad_sql: str, reason: str) -> dict:
            # A blocked query is a hard stop — never retried
            logger.warning(f"BLOCKED SQL ({reason}): {bad_sql!r}  question={question!r}")
            resp = _empty_response(BLOCKED_MESSAGE)
            resp.update({"sql": bad_sql, "table_name": table_name, "mode": mode,
                         "blocked": reason, "routing": routing})
            return resp

        def run(q: str) -> list:
            if mode == "broker":
                try:
                    return asyncio.run(n8n_broker.execute(connection, q))
                except RuntimeError:
                    # In async context — fall back to creating a new loop
                    loop = asyncio.new_event_loop()
                    try:
                        return loop.run_until_complete(n8n_broker.execute(connection, q))
                    finally:
                        loop.close()
            if mode == "session":
                return session_store.execute(session_id, q)
            return execute_sql(q)

        # ── Read-only guard — nothing executes unless it passes ─────────────
        allowed, sql, reason = check_sql(sql)
        if not allowed:
            return blocked(sql, reason)

        # ── Execute, with one self-healing retry on execution errors ────────
        retried, first_sql, first_error = False, None, None
        try:
            results = run(sql)
        except Exception as e:
            first_sql, first_error, retried = sql, _short_error(e), True
            logger.warning(f"SQL failed, asking Claude to fix: {first_error}  sql={sql!r}")

            sql = fix_sql(question, table_name, schema, first_sql, first_error)
            logger.info(f"Corrected SQL: {sql}")

            # Retried SQL goes through the same guard
            allowed, sql, reason = check_sql(sql)
            if not allowed:
                return blocked(sql, reason)

            try:
                results = run(sql)
            except Exception as e2:
                logger.error(f"Retry also failed: {_short_error(e2)}  sql={sql!r}")
                resp = _empty_response(RETRY_FAILED_MESSAGE)
                resp.update({"sql": sql, "table_name": table_name, "mode": mode, "routing": routing,
                             "retried": True, "first_sql": first_sql, "first_error": first_error})
                return resp

        # ── Format + filter extraction ──────────────────────────────────────
        answer = format_answer(question, sql, results)
        filters = []
        if extract_tableau_filters:  # only the Tableau extension uses these
            filters = extract_filters(question, table_name, workbook_context=workbook_context)
            logger.info(f"Extracted filters: {filters}")

        return {
            "answer": answer,
            "sql": sql,
            "table_name": table_name,
            "results": results,
            "filters": filters,
            "mode": mode,
            "retried": retried,
            "first_sql": first_sql,
            "first_error": first_error,
            "routing": routing,
            "simulated": simulate_bad_sql,
        }

    except Exception as e:
        # Full trace goes to the log; the user never sees it
        logger.error(f"Pipeline error: {e}", exc_info=True)
        return _empty_response(GENERIC_ERROR_MESSAGE)


RETRY_FAILED_MESSAGE = (
    "I couldn't build a working query for that question, even after correcting it once. "
    "Try rephrasing, or ask about a specific metric and data source."
)
GENERIC_ERROR_MESSAGE = (
    "Something went wrong while answering that question. Please try again."
)


def _empty_response(message: str) -> dict:
    return {
        "answer": message,
        "sql": None,
        "table_name": None,
        "results": None,
        "filters": [],
        "mode": None,
    }


if __name__ == "__main__":
    test_questions = [
        "Who is the top performing sales rep?",
        "What were total sales in the West region?",
        "Which product category had the highest revenue?",
        "How did Facebook perform compared to Google Ads?",
    ]

    for question in test_questions:
        print(f"\nQ: {question}")
        print("-" * 60)
        result = answer_question(question)
        print(f"Answer : {result['answer']}")
        print(f"Filters: {result['filters']}")
