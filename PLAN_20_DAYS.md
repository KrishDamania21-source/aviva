# Aviva — 20-Day Portfolio Plan

**Goal:** Turn Aviva into a polished, demo-ready portfolio project that proves you can build a real LLM-powered analytics tool.
**Time budget:** 1–2 hours per day.
**Level:** Newer to the stack. Each day explains the *why*, not just the *what*, so you learn the fundamentals as you go.

---

## Where the project actually stands (June 2026)

Your `CLAUDE.md` describes an older version. The real codebase is further along, and the plan below reflects that. Today Aviva is:

- A **Tableau dashboard extension** (`extension/`) that talks to a **FastAPI backend** (`api.py`)
- Backed by **Postgres / Supabase** (`DATABASE_URL`), not just local SQLite
- With **three query modes** in `pipeline.py`: an **n8n credential broker** for live customer databases, a **DuckDB session store** for data pushed from the Tableau extension, and a **Supabase fallback** for demos
- Routing across **four data sources** (sales, marketing, facebook_ads, vendor_central) using **FAISS semantic search**
- Using **Claude Sonnet** for SQL generation, answer formatting, and filter extraction

That's a lot of moving parts. A recruiter or reviewer will be impressed by the architecture but only if they can *understand it quickly and run it*. Most of this plan is about making the project legible and trustworthy, not adding more features.

---

## The four phases

| Days | Phase | What you walk away with |
|------|-------|--------------------------|
| 1–5 | **Understand & document** | You can explain every file; docs match reality |
| 6–11 | **Harden & make it correct** | Errors handled, SQL safe, tests passing |
| 12–16 | **Polish the experience** | Clean UI, charts, a demo that works every time |
| 17–20 | **Present & ship** | Live demo, README, walkthrough, portfolio writeup |

---

# Phase 1 — Understand & Document (Days 1–5)

You can't polish what you don't fully understand. This phase costs you little code but pays off everywhere.

### Day 1 — Map the system and get it running clean
- Run the app end to end (loader → indexer → backend → extension or Streamlit) and write down every command that worked and every one that broke.
- Draw the request flow on paper or in a diagram tool: *question → FAISS routing → schema fetch → Claude SQL → execute → Claude formats answer → filters extracted → UI.*
- **Learn:** what each of the three modes (broker / session / supabase) is for and when each fires. Read `answer_question()` in `pipeline.py` slowly.
- **Deliverable:** a `NOTES.md` with the working run commands and your flow diagram.

### Day 2 — Rewrite CLAUDE.md / README to match reality
- The current README still describes SQLite + Streamlit only. Update it to describe the real stack: FastAPI, Postgres/Supabase, the Tableau extension, the three modes, and FAISS routing.
- Add an honest "Architecture" section and an "Architecture diagram" (export the Day 1 diagram).
- **Learn:** writing docs forces you to confront things you didn't actually understand. Note every spot where you had to go read code to explain it.
- **Deliverable:** an accurate README.

### Day 3 — Understand the data layer
- Open all four CSVs and `sales.db`. Document each source's columns, types, and a couple of sample rows.
- Map how `config.py` `CSV_SOURCES` descriptions drive FAISS routing. Read `indexer.py` and `loader.py`.
- **Learn:** why the *description text* is the most important part of routing — the embedding of that description is what gets matched against questions.
- **Deliverable:** a short `data/SCHEMA.md` documenting all four sources.

### Day 4 — Understand the FAISS routing layer
- Read `indexer.search_index()`. Trace how a question becomes an embedding and gets matched to a source.
- Run 10 test questions and log which source each routes to. Find at least one that routes *wrong*.
- **Learn:** embeddings, cosine similarity, and why semantic routing beats keyword matching. This is the project's headline feature — you must be able to explain it cold.
- **Deliverable:** a routing test log with at least one misroute identified.

### Day 5 — Understand the Tableau extension and n8n broker
- Read `extension/`, `api.py`, `n8n_broker.py`, and `session_store.py`. Sketch how the extension pushes workbook context and data to the backend.
- Note: `KNOWN_CONNECTIONS` and `N8N_QUERY_WEBHOOK` are placeholders. Decide whether the broker is part of your demo story or something you'll document as "designed, not deployed."
- **Learn:** how a frontend extension and a Python backend share state via session IDs.
- **Deliverable:** a one-paragraph "what's real vs. planned" honesty note for the README.

---

# Phase 2 — Harden & Make It Correct (Days 6–11)

This is what separates a demo from a project. A reviewer will *try to break it*.

### Day 6 — Fix the obvious bugs and stale code first
- The Streamlit `app.py` still references `sales_data`/`marketing_data` charts only and lowercase column names, while `pipeline.py` uses quoted PascalCase Postgres columns. Pick **one** primary frontend (extension or Streamlit) and make it consistent.
- Remove or clearly mark dead/placeholder code.
- **Deliverable:** the chosen frontend runs without column-name mismatches.

### Day 7 — Handle SQL errors gracefully
- Right now a bad generated query can throw raw. Wrap `execute_sql` so a SQL error returns a friendly message *and* logs the failing query.
- Add a single retry: if the query fails, send the error back to Claude and ask it to fix the SQL once.
- **Learn:** the "self-healing query" pattern — a classic, impressive LLM-app technique.
- **Deliverable:** a deliberately bad question returns a clean message, not a stack trace.

### Day 8 — Add SQL safety guardrails
- Generated SQL should be read-only. Reject anything that isn't a `SELECT` (block `INSERT/UPDATE/DELETE/DROP/ALTER`).
- **Learn:** why letting an LLM write SQL against your DB is dangerous without guardrails. This is a talking point reviewers love.
- **Deliverable:** a destructive query attempt is blocked and logged.

### Day 9 — Fix the routing misroute from Day 4
- Improve the `config.py` source `description` for whichever source was misrouting. Re-run the indexer. Re-test.
- **Learn:** prompt/description engineering as a real iterative loop.
- **Deliverable:** the previously-misrouted question now routes correctly, with a before/after note.

### Day 10 — Write your first automated tests
- Add `pytest`. Write tests for the safe parts: `_workbook_context_section`, `extract_filters` JSON parsing, the SQL-safety guard, and a mocked `answer_question`.
- **Learn:** how to test code that calls an LLM by *mocking the LLM call* so tests are fast and free.
- **Deliverable:** `tests/` with 5+ passing tests and a `pytest` command in the README.

### Day 11 — Environment, secrets, and reproducibility
- Make sure `.env` is gitignored (verify it's not in git history). Add a `.env.example` with blank placeholders.
- Pin `requirements.txt` versions. Confirm a fresh clone can run from the README alone.
- **Deliverable:** a teammate (or future you) could clone and run in under 15 minutes.

---

# Phase 3 — Polish the Experience (Days 12–16)

Now make it *feel* good.

### Day 12 — Clean up the answer + SQL display
- Ensure the UI always shows: the answer, the SQL (collapsible), the data source, and the row count. Make formatting consistent.
- **Deliverable:** a clean, predictable result layout.

### Day 13 — Make charts reliable
- The current chart logic is hardcoded per-table and brittle. Generalize it: if results have one text column and one numeric column, draw a bar chart automatically.
- **Learn:** writing display logic that adapts to data shape instead of hardcoded table names.
- **Deliverable:** charts appear for any chartable result, not just two specific tables.

### Day 14 — Build a curated demo question set
- Pick 8–10 questions across all four sources that always return good, interesting answers. These are your demo script.
- Add them as clickable example chips/buttons in the UI so a reviewer doesn't have to think.
- **Deliverable:** one-click example questions that always work.

### Day 15 — Loading states, empty states, and error states
- Polish what the user sees while waiting, when there are no results, and when something fails. No raw errors should ever reach the screen.
- **Deliverable:** every state looks intentional.

### Day 16 — Visual polish pass
- Tighten the header, spacing, and labels. Add a short "How it works" line so a first-time viewer understands the FAISS routing in one sentence.
- **Deliverable:** a screenshot worthy of a portfolio thumbnail.

---

# Phase 4 — Present & Ship (Days 17–20)

### Day 17 — Record a demo and write the walkthrough
- Record a 2–3 minute screen capture: ask 3–4 questions, show the SQL, show the chart, show a misroute being handled.
- **Deliverable:** a demo video or GIF embedded in the README.

### Day 18 — Write the portfolio case study
- One page: the problem, your architecture (with the diagram), the hard parts (FAISS routing, self-healing SQL, multi-mode execution), and what you'd do next.
- **Learn:** how to talk about a project so the *engineering judgment* shows, not just the feature list.
- **Deliverable:** `CASE_STUDY.md`.

### Day 19 — Deploy or package for easy review
- Either deploy the backend (Render/Railway) with a hosted demo link, or package a one-command local run (Docker or a `make demo` script). Pick whichever is realistic.
- **Deliverable:** a way for someone to try Aviva without reading code.

### Day 20 — Final review and ship
- Re-run the full README from scratch on a clean checkout. Fix anything that breaks.
- Polish the GitHub repo: description, topics, pinned, clean commit history on at least the recent work.
- **Deliverable:** a repo you'd happily put at the top of your resume.

---

## How to use this plan

- **Each day has one deliverable.** If you only have an hour, do the deliverable and skip the extra reading.
- **Days slip — that's fine.** This is a 20-task plan, not a 20-calendar-day contract. Move at your real pace.
- **Keep `NOTES.md` open daily.** Writing down what you learned is what turns this from "I built an app" into "I can explain every decision in this app" — which is what gets you hired.
- **The teaching is the point.** You said you want fundamentals. The "Learn" lines are where the durable skills live: embeddings, LLM safety, self-healing queries, testing LLM code, adaptive UI.

## Stretch goals (only if you finish early)
- Conversation memory (follow-up questions that remember the last answer)
- Multi-source questions that join across two data sources
- A proper evaluation harness that scores routing accuracy automatically
- Real auth before any public deployment
