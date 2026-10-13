import os
import json
import logging
from anthropic import Anthropic
from config import CSV_SOURCES, ROUTING_MODEL_NAME

logger = logging.getLogger(__name__)


def _get_client():
    """Return the Anthropic client, initializing it on first use."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set.")
    return Anthropic(api_key=api_key)


def response_text(response) -> str:
    """Concatenate the text blocks of a Claude response. Don't assume content[0] is text —
    newer models can return a thinking block first."""
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")


def search_index(query: str, top_k: int = 1, workbook_context: dict | None = None) -> list[dict]:
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

    # Include Tableau sheet context to help route questions that use dashboard vocabulary
    context_hint = ""
    if workbook_context:
        sheet_names = [s["name"] for s in workbook_context.get("sheets", [])]
        if sheet_names:
            context_hint = f"\nThe question comes from a Tableau dashboard with these sheets: {', '.join(sheet_names)}."

    prompt = f"""You are a data routing assistant. Given a user question, choose the single most relevant table to query.

Available tables:
{sources_text}
{context_hint}
User question: "{query}"

Return ONLY a JSON object with no explanation, no markdown, no extra text:
{{"table_name": "the_table_name", "reason": "one sentence on why this table fits the question", "runner_up": "the second-best table_name"}}

table_name and runner_up must each be one of: {", ".join(table_names)}, and must be different."""

    try:
        response = _get_client().messages.create(
            model=ROUTING_MODEL_NAME,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response_text(response).strip()
        # Strip markdown code fences if Claude wraps the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
        table_name = parsed.get("table_name", "")

        if table_name not in CSV_SOURCES:
            # No silent fallback — a wrong table gives a confident wrong answer
            logger.warning(f"Claude returned unknown table '{table_name}'; not routing")
            return []

        runner_up = parsed.get("runner_up")
        if runner_up not in CSV_SOURCES or runner_up == table_name:
            runner_up = None

        return [{
            "table_name": table_name,
            "description": CSV_SOURCES[table_name]["description"],
            "distance": 0.0,
            "reason": (parsed.get("reason") or "").strip(),
            "runner_up": runner_up,
        }]

    except Exception as e:
        logger.error(f"Claude routing failed: {e}; not routing")
        return []


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
