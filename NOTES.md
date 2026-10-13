# Aviva demo notes

## Status: Step 1 done. Pipeline runs end to end in Supabase mode.

## Commands that worked

```bash
cd /Users/krishdamania/aviva
source venv/bin/activate              # Python 3.14.2
pip install -r requirements.txt       # venv was missing psycopg2-binary

# One-time: load the 4 CSVs into Supabase (20 / 20 / 80 / 80 rows)
python -c "from dotenv import load_dotenv; load_dotenv(); from loader import load_all_sources; load_all_sources()"

# End-to-end pipeline check
python -c "from pipeline import answer_question; print(answer_question('Who is the top performing sales rep?')['answer'])"
```

## What broke

| # | Problem | Fix |
|---|---------|-----|
| 1 | `psycopg2` not installed in venv | `pip install -r requirements.txt` |
| 2 | `claude-sonnet-4-20250514` retired, every Claude call 404s. Routing silently fell back to `sales_data`. | `config.py`: `MODEL_NAME = "claude-sonnet-5-5"` |
| 3 | Old Supabase project (`nqsravnlpquiejpycyeb`) is gone | New project `aukkeaowknnzthivyxmf`, `DATABASE_URL` in `.env` now uses the session pooler (`aws-0-us-east-1.pooler.supabase.com:5432`), with the `@` in the password encoded as `%40` |
| 4 | New project was empty | Ran `loader.py` (above) |
| 5 | `loader.py` printed the first 30 chars of `DATABASE_URL` (could leak the password) | Removed that print |

## Smoke test results (one question per source)

| Question | Routed to | Answer |
|---|---|---|
| Who is the top performing sales rep? | sales_data | Sarah Chen, $12,320.30 |
| Which channel had the best ROI? | marketing_data | Email |
| Which Facebook campaign had the best ROAS? | facebook_ads | Retargeting - Cart Abandoners, 13.10 |
| Best selling product on Amazon by ordered revenue? | vendor_central | PowerBlend Pro Protein Powder 5lb |

All columns are lowercase in Postgres (`loader.py` lowercases them). Claude used the lowercase
names correctly, even though the SQL prompt gives a PascalCase example.

## Request flow (Supabase mode, as the code actually works)

```
question (Streamlit app.py, or Tableau extension -> FastAPI POST /query)
  > pipeline.answer_question()        no connection/session_id, so Supabase mode
  > indexer.search_index()            ROUTING: one Claude call picks a table from
                                       the CSV_SOURCES descriptions in config.py
                                       (FAISS is no longer used; there are no similarity scores)
  > get_table_schema()                Postgres information_schema.columns
  > generate_sql()                    Claude: question + schema -> SQL
  > execute_sql()                     SQLAlchemy against Supabase Postgres
  > format_answer()                   Claude: rows -> plain-English answer
  > extract_filters()                 Claude: Tableau filter specs (extension only)
  > UI
```

## Step 2: frontend = Streamlit

```bash
source venv/bin/activate
streamlit run app.py          # http://localhost:8501
```

Why not the Tableau extension:
- No Tableau workbook exists on disk; a dashboard would have to be built from scratch.
- The extension loads from Netlify and calls the Render API, whose `DATABASE_URL` points at the deleted project.
- Filter field names are hardcoded (`Region`, `Sales_Rep`), but Tableau renames CSV fields on import
  (`sales_rep` becomes `Sales Rep`), so filters would likely fail without any error.
- The local `/query` API itself works (tested), so the extension is recoverable after the demo.

Fixes made for Streamlit:
- `.claude/launch.json`: run `venv/bin/streamlit` headless (the bare `streamlit` command isn't on PATH)
- `pipeline.py` SQL prompt: quoting example changed from PascalCase to the real lowercase column names

## Silent routing fallback: removed

`indexer.py` used to route to `sales_data` whenever Claude named a table that doesn't exist
or the routing call failed, which produces confident wrong answers. It now returns no route,
and the user sees "I could not find a relevant data source for that question."

## Step 3: read-only SQL guard

- `sql_guard.py`: `check_sql()` strips comments, then allows only a single `SELECT`/`WITH`.
  It rejects multiple statements and any INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE,
  CREATE, GRANT. It also rejects `INTO` (Postgres `SELECT ... INTO t` creates a table) and `$$`.
  Text inside string literals and quoted identifiers is masked first, so
  `WHERE name = 'Drop; Delete Inc'` is allowed.
- `pipeline.answer_question()` checks before every execution path. Blocked queries are
  logged (`BLOCKED SQL (reason): ...`) and the user sees a friendly message.
- Second layer: `execute_sql()` runs inside `SET TRANSACTION READ ONLY`.
- Tests: `python tests/test_sql_guard.py` (4 pass), including a forced DROP that never
  reaches the executor and a live check that Postgres rejects writes.

## Step 4: self-healing retry

```
generated SQL > guard ── blocked ──> friendly "read-only" message (no retry)
                  │ ok
               execute ── ok ──> answer
                  │ execution error
               fix_sql(question, schema, failed SQL, DB error)   one Claude call
                  │
                guard ── blocked ──> friendly "read-only" message
                  │ ok
               execute ── ok ──> answer (retried=True)
                  │ error
               friendly "couldn't build a working query" message (no second retry)
```

- `pipeline.fix_sql()` sends the question, schema, failing SQL and the Postgres error message (driver text only).
- Any other unexpected error now shows a generic friendly message instead of
  `Pipeline error: <ExceptionType>: ...`. The full trace still goes to the log.
- `_strip_fences()` removes ```` ```sql ```` wrapping from Claude's SQL. Otherwise a fenced
  reply would be blocked by the guard, and blocked queries never retry.
- The result dict now includes `retried`, `first_sql`, `first_error`.
- Tests: `python tests/test_retry.py` (7 pass).
- Live check: a forced `"salesrep"`/`"total"` query failed, Claude corrected it to
  `"sales_rep"`/`"total_amount"`, and the answer was Sarah Chen, $12,320.30.

## Step 5: routing and self-correction visible in the UI

- `indexer.py`: the routing call returns JSON `{table_name, reason, runner_up}`. No scores.
  A `runner_up` that is invalid or the same as the chosen table is dropped.
- `pipeline.py`: the result includes `routing`. New `simulate_bad_sql` flag misspells the
  first real column in the generated SQL (swaps its last two letters) *before* the guard,
  so the corrupted query is guarded like any other.
- `app.py` layout: routing decision box (source, reason, runner-up), Answer (+ "Self-corrected"
  badge when retried), bar chart (generic: first text column vs first numeric column,
  2 to 50 rows), row count, "Generated SQL" expander, "Self-correction details" expander
  (first SQL, Postgres error, and a note when the demo toggle caused it).
- Sidebar: "Demo: simulate a bad first query" toggle, off by default.
- Answers escape `$`, because Streamlit renders `$...$` as LaTeX.

**For recording:** Streamlit keeps the toggle state while a browser tab stays connected.
Reload the page to reset it to off.

## Step 6: speed changes and two reliability bugs found in benchmarking

- Routing uses Haiku (`ROUTING_MODEL_NAME`). Streamlit passes `extract_tableau_filters=False`.
  Median time per question went from 8.1s to 4.0s (details in DEMO_SCRIPT.md).
- **Connection leak (would have broken the recording):** `get_table_schema`/`execute_sql`
  created a new SQLAlchemy engine per call, and each one kept a pooled connection open. Supabase's
  session pooler allows 15 clients, so queries failed after about 7 questions in one process.
  Fixed with one shared engine (`_get_engine()`, pool_size 3, pre-ping). Verified with 120
  consecutive queries.
- **Thinking-block crash:** Sonnet 5.5 sometimes returns a thinking block before the text,
  and `response.content[0].text` raised AttributeError, which showed as "Something went wrong".
  It was intermittent. All five call sites now use `response_text()`, which joins the text blocks.

## Open items
- Step 5 (decided): no scores. The routing call returns JSON with the chosen table, a
  one-sentence reason and the runner-up table, and the UI shows all three.
- Rotate the Supabase DB password after the recording. It was shared in chat.
