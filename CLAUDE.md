# Aviva -- Setup and Architecture

Natural language analytics assistant. Ask a business question; Aviva routes it to the right
data source, generates PostgreSQL SQL, runs it, and returns a plain-English answer.

## Project structure

```
aviva/
├── app.py              # Streamlit frontend
├── pipeline.py         # Core pipeline: routing, SQL gen, guard, execution, retry, answer
├── indexer.py          # LLM-based source routing (search_index) and response_text helper
├── sql_guard.py        # Read-only SQL gate (check_sql)
├── loader.py           # Loads CSV files into Supabase Postgres
├── session_store.py    # DuckDB in-memory sessions (Tableau extension path)
├── n8n_broker.py       # n8n credential broker (placeholder, not deployed)
├── api.py              # FastAPI backend for the Tableau extension
├── config.py           # DATABASE_URL, model names, CSV_SOURCES routing table
├── requirements.txt
├── .env                # Not committed; see .env.example
├── .env.example        # Template for required environment variables
├── data/
│   ├── sales_data.csv
│   ├── marketing_data.csv
│   ├── facebook_ads.csv
│   └── vendor_central.csv
├── docs/
│   ├── routing.png
│   ├── self-correct.png
│   └── misroute.png
├── extension/          # Tableau dashboard extension (HTML/JS, experimental)
└── tests/
    ├── test_sql_guard.py
    └── test_retry.py
```

## Architecture

### Request flow (Streamlit / Supabase mode)

```
question
  > pipeline.answer_question()
  > indexer.search_index()      -- Claude Haiku picks a table from CSV_SOURCES descriptions;
                                    returns {table_name, reason, runner_up}; no vector index
  > get_table_schema()          -- information_schema.columns for the chosen table
  > generate_sql()              -- Claude Sonnet: question + schema -> SQL
  > sql_guard.check_sql()       -- first layer: whitelist SELECT/WITH, block all writes
  > execute_sql()               -- SET TRANSACTION READ ONLY; SQLAlchemy -> Supabase Postgres
      [ on error: fix_sql() -> check_sql() -> execute_sql(); one retry only ]
  > format_answer()             -- Claude Sonnet: rows -> plain-English answer
```

### Execution modes (in priority order)

1. **n8n broker** -- if `connection` is given and `N8N_QUERY_WEBHOOK` is set. Placeholder;
   not deployed.
2. **DuckDB session** -- if `session_id` is given and a session is loaded. Used by the
   Tableau extension, which pushes worksheet snapshots to `POST /load-session`.
3. **Supabase** -- default. Used by the Streamlit app and local development.

### Models (config.py)

- `ROUTING_MODEL_NAME`: `claude-haiku-4-5-20251001` -- routing only
- `MODEL_NAME`: `claude-sonnet-5-5` -- SQL generation, self-correction, answer formatting

### SQL guard (sql_guard.py)

`check_sql()` strips comments, masks string literal and quoted identifier contents, then:
- requires the statement to start with `SELECT` or `WITH`
- rejects multiple statements (semicolons after the first)
- rejects dollar-quoted strings
- rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `GRANT`, `INTO`

A blocked query is a hard stop; it is never retried.

`execute_sql()` also opens a `SET TRANSACTION READ ONLY` connection as a second independent
layer.

## First-time setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY and DATABASE_URL
python loader.py       # loads the four CSVs into Supabase
streamlit run app.py   # http://localhost:8501
```

## Tests

```bash
python tests/test_sql_guard.py   # 4 tests, no API key or DB required
python tests/test_retry.py       # 7 tests, no API key or DB required
```

## Adding a new data source

1. Drop the CSV into `data/`.
2. Add an entry to `CSV_SOURCES` in `config.py`. The `description` is what the routing
   LLM reads; be specific about what the table contains and what it does not contain.
3. Run `python loader.py` to push the new table to Supabase.

## FastAPI backend (Tableau extension)

```bash
uvicorn api:app --reload --port 8000
```

Endpoints: `GET /health`, `POST /query`, `POST /load-session`,
`DELETE /load-session/{session_id}`, `GET /connections`, `POST /refresh`.

The extension is experimental. See `docs/NOTES.md` for known issues.
