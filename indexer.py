import os
import json
import logging
from anthropic import Anthropic
from config import CSV_SOURCES, MODEL_NAME

logger = logging.getLogger(__name__)


def _get_client():
    """Return the Anthropic client, initializing it on first use."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set.")
    return Anthropic(api_key=api_key)


def search_index(query: str, top_k: int = 1) -> list[dict]:
    """Route a natural language query to the most relevant data source.

    Uses Claude to pick the best table from CSV_SOURCES based on the query.
    Returns the same interface as the old FAISS version:
    a list of dicts with 'table_name', 'description', and 'distance'.
    """
    sources_text = "\n\n".join([
        f"Table: {name}\nDescription: {source['description']}"
        for name, source in CSV_SOURCES.items()
    ])

    table_names = list(CSV_SOURCES.keys())

    prompt = f"""You are a data routing assistant. Given a user question, choose the single most relevant table to query.

Available tables:
{sources_text}

User question: "{query}"

Return ONLY a JSON object with no explanation, no markdown, no extra text:
{{"table_name": "the_table_name"}}

The table_name must be one of: {", ".join(table_names)}"""

    try:
        response = _get_client().messages.create(
            model=MODEL_NAME,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        parsed = json.loads(raw)
        table_name = parsed.get("table_name", "")

        if table_name not in CSV_SOURCES:
            logger.warning(f"Claude returned unknown table '{table_name}', defaulting to first source")
            table_name = table_names[0]

        return [{
            "table_name": table_name,
            "description": CSV_SOURCES[table_name]["description"],
            "distance": 0.0,
        }]

    except Exception as e:
        logger.warning(f"Claude routing failed: {e}. Defaulting to first source.")
        fallback = table_names[0]
        return [{
            "table_name": fallback,
            "description": CSV_SOURCES[fallback]["description"],
            "distance": 0.0,
        }]


if __name__ == "__main__":
    print("--- Claude Routing Test ---")
    test_queries = [
        "Who is the top performing sales rep?",
        "What were total sales in the West region?",
        "Which Facebook campaign had the best ROAS?",
        "What's our best selling ASIN on Amazon?",
        "Which channel had the best ROI?",
    ]
    for q in test_queries:
        results = search_index(q)
        print(f"Q: {q}")
        print(f"  -> {results[0]['table_name']}")
