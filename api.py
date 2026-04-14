"""
api.py — Aviva FastAPI backend

Wraps the query pipeline and exposes it over HTTP so the Tableau extension
can POST questions and receive answers + filter instructions.

Run with:
    uvicorn api:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pipeline import answer_question

app = FastAPI(
    title="Aviva API",
    description="Natural language query API for Aviva. Powers the Tableau extension.",
    version="1.0.0",
)

# CORS — required so the Tableau extension (served on a different port) can call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock this down to your Tableau server URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str


class FilterSpec(BaseModel):
    field: str
    values: list[str]


class QueryResponse(BaseModel):
    answer: str
    sql: str | None
    table_name: str | None
    filters: list[FilterSpec]


@app.get("/health")
def health():
    """Quick liveness check — useful for verifying the server is up before a demo."""
    return {"status": "ok", "service": "Aviva API"}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    """
    Main endpoint. Accepts a natural language question, runs the full Aviva
    pipeline, and returns the answer plus any Tableau filter instructions.

    The Tableau extension calls this on every user submission.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    result = answer_question(request.question)

    return QueryResponse(
        answer=result["answer"],
        sql=result.get("sql"),
        table_name=result.get("table_name"),
        filters=[FilterSpec(**f) for f in result.get("filters", [])],
    )
