import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic
from sqlalchemy import create_engine, text
from config import DATABASE_URL, MODEL_NAME
from indexer import search_index

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


def get_table_schema(table_name: str) -> str:
    """Get the schema of a table from Postgres information_schema."""
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = :table ORDER BY ordinal_position"
        ), {"table": table_name})
        columns = result.fetchall()

    schema_lines = [f"  {col[0]} ({col[1]})" for col in columns]
    return "\n".join(schema_lines)


def generate_sql(question: str, table_name: str, schema: str) -> str:
    """Ask Claude to generate SQL for the question."""
    prompt = f"""You are a SQL expert. Generate a PostgreSQL query to answer this question.

Table: {table_name}
Schema:
{schema}

Question: {question}

Return ONLY the SQL query, nothing else. No explanation, no markdown, just the raw SQL."""

    response = _get_client().messages.create(
        model=MODEL_NAME,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text.strip()


def execute_sql(sql: str) -> list:
    """Execute SQL against the Postgres database."""
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
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

    return response.content[0].text.strip()


def extract_filters(question: str, table_name: str) -> list:
    """Use Claude to extract any dashboard filter intent from the question.

    Returns a list of filter dicts: [{"field": "Region", "values": ["West"]}]
    Each filter maps directly to a Tableau worksheet applyFilterAsync() call.
    """
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
        raw = response.content[0].text.strip()
        parsed = json.loads(raw)
        return parsed.get("filters", [])
    except Exception as e:
        logger.warning(f"Filter extraction failed: {e}")
        return []


def answer_question(question: str) -> dict:
    """End-to-end pipeline to answer a user question.

    Returns a dict with 'answer', 'sql', 'table_name', 'results', and 'filters' keys.
    'filters' is a list of dicts the Tableau extension uses to apply dashboard filters.
    """
    try:
        # Step 1: Find the right table
        relevant_sources = search_index(question, top_k=1)
        if not relevant_sources:
            return {
                "answer": "I could not find a relevant data source for that question.",
                "sql": None,
                "table_name": None,
                "results": None,
                "filters": [],
            }

        table_name = relevant_sources[0]["table_name"]
        logger.info(f"Routing to table: {table_name}")

        # Step 2: Get table schema
        schema = get_table_schema(table_name)

        # Step 3: Generate SQL
        sql = generate_sql(question, table_name, schema)
        logger.info(f"Generated SQL: {sql}")

        # Step 4: Execute SQL
        results = execute_sql(sql)

        # Step 5: Format answer
        answer = format_answer(question, sql, results)

        # Step 6: Extract Tableau filters from the question
        filters = extract_filters(question, table_name)
        logger.info(f"Extracted filters: {filters}")

        return {
            "answer": answer,
            "sql": sql,
            "table_name": table_name,
            "results": results,
            "filters": filters,
        }

    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        return {
            "answer": f"Pipeline error: {type(e).__name__}: {e}",
            "sql": None,
            "table_name": None,
            "results": None,
            "filters": [],
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
