"""
api.py — Aviva FastAPI backend

Wraps the query pipeline and exposes it over HTTP so the Tableau extension
can POST questions and receive answers + filter instructions.

Run with:
    uvicorn api:app --reload --port 8000
"""

import os
import httpx
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pipeline import answer_question

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Aviva API",
    description="Natural language query API for Aviva. Powers the Tableau extension.",
    version="1.0.0",
)

# CORS — required so the Tableau extension (served on a different port) can call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── n8n webhook URLs — set these in Render environment variables ──────────────
N8N_WEBHOOKS = {
    "sales_data":      os.environ.get("N8N_WEBHOOK_SALES", ""),
    "marketing_data":  os.environ.get("N8N_WEBHOOK_MARKETING", ""),
    "facebook_ads":    os.environ.get("N8N_WEBHOOK_FACEBOOK", ""),
    "vendor_central":  os.environ.get("N8N_WEBHOOK_VENDOR", ""),
}


# ── Models ────────────────────────────────────────────────────────────────────
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


class RefreshRequest(BaseModel):
    source: str | None = None  # specific source name, or None to refresh all


class RefreshResponse(BaseModel):
    results: dict[str, str]


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Quick liveness check — useful for verifying the server is up before a demo."""
    return {"status": "ok", "service": "Aviva API"}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    """
    Main endpoint. Accepts a natural language question, runs the full Aviva
    pipeline, and returns the answer plus any Tableau filter instructions.
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


@app.post("/refresh", response_model=RefreshResponse)
async def refresh(request: RefreshRequest = RefreshRequest()):
    """
    Trigger n8n to regenerate and reload data for one or all sources.

    Pass {"source": "sales_data"} to refresh a single source, or send an
    empty body to refresh everything. n8n webhook URLs are read from the
    N8N_WEBHOOK_* environment variables set in Render.
    """
    if request.source:
        if request.source not in N8N_WEBHOOKS:
            raise HTTPException(status_code=400, detail=f"Unknown source: {request.source}")
        targets = {request.source: N8N_WEBHOOKS[request.source]}
    else:
        targets = N8N_WEBHOOKS

    results = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for name, url in targets.items():
            if not url:
                results[name] = "not configured"
                continue
            try:
                r = await client.post(url)
                results[name] = "ok" if r.status_code < 300 else f"error {r.status_code}"
            except Exception as e:
                logger.warning(f"n8n webhook failed for {name}: {e}")
                results[name] = f"error: {str(e)}"

    return RefreshResponse(results=results)
