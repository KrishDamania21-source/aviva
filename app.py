import streamlit as st
import pandas as pd
import altair as alt
from pipeline import answer_question

SOURCE_LABELS = {
    "sales_data": "Sales",
    "marketing_data": "Marketing",
    "facebook_ads": "Facebook Ads",
    "vendor_central": "Amazon Vendor Central",
}

DATA_SOURCE_DESCRIPTIONS = {
    "sales_data":     "Sales transactions by region and rep — orders, revenue, product categories.",
    "marketing_data": "Campaign performance across channels — spend, conversions, ROI.",
    "facebook_ads":   "Meta paid ads at campaign/ad-set level — ROAS, CPC, placement breakdowns.",
    "vendor_central": "Amazon Vendor Central — ASINs, ordered/shipped units, glance views.",
}

EXAMPLE_QUESTIONS = [
    "Which marketing channel had the best ROI?",
    "What were total sales by sales rep?",
    "How much revenue did our Instagram ads generate?",
]

st.set_page_config(page_title="Aviva", layout="centered")

st.markdown("""
<style>
    code { white-space: pre-wrap !important; word-wrap: break-word !important; }
    .stCodeBlock > div { resize: none !important; }

    /* Pipeline strip */
    .pipeline-strip {
        background: #F4F6F9;
        border-radius: 6px;
        padding: 10px 16px;
        margin: 12px 0 20px 0;
        font-size: 0.82rem;
        color: #555;
        letter-spacing: 0.01em;
    }
    .pipeline-strip .steps {
        font-weight: 500;
        color: #1B3A6B;
    }
    .pipeline-strip .tagline {
        font-style: italic;
        font-size: 0.77rem;
        margin-top: 4px;
        color: #777;
    }

    /* Example chips */
    .chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
    .chip {
        background: #EEF1F7;
        border: 1px solid #C8D0E0;
        border-radius: 20px;
        padding: 5px 14px;
        font-size: 0.82rem;
        color: #1B3A6B;
        cursor: pointer;
        white-space: nowrap;
    }
    .chip:hover { background: #D8E0F0; }

    /* Footer */
    .footer {
        margin-top: 48px;
        padding-top: 12px;
        border-top: 1px solid #E0E4EC;
        font-size: 0.76rem;
        color: #999;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Data sources")
    for key, desc in DATA_SOURCE_DESCRIPTIONS.items():
        label = SOURCE_LABELS[key]
        st.markdown(f"**{label}** — {desc}")

    st.divider()
    st.markdown("**Demo controls**")
    simulate_bad_sql = st.toggle("Simulate a bad first query", value=False)
    if simulate_bad_sql:
        st.caption(
            "The first generated query gets one column name misspelled "
            "so the self-correction path runs live."
        )

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("# Aviva")
st.markdown("Ask your sales and marketing data anything.")

st.markdown("""
<div class="pipeline-strip">
    <div class="steps">Question &rsaquo; Pick data source &rsaquo; Write SQL &rsaquo; Read-only check &rsaquo; Run &rsaquo; Explain</div>
    <div class="tagline">Self-correcting, read-only, and it shows its reasoning.</div>
</div>
""", unsafe_allow_html=True)

# ── Example chips (rendered as buttons) ───────────────────────────────────────
cols = st.columns(len(EXAMPLE_QUESTIONS))
chip_question = None
for i, q in enumerate(EXAMPLE_QUESTIONS):
    with cols[i]:
        if st.button(q, key=f"chip_{i}", use_container_width=True):
            chip_question = q

# ── Input ─────────────────────────────────────────────────────────────────────
question = st.text_input(
    "Your question:",
    value=chip_question or "",
    placeholder="Type a question or pick an example above.",
    label_visibility="collapsed",
)

run_question = st.button("Ask", type="primary", use_container_width=True)

# ── Empty state ───────────────────────────────────────────────────────────────
if not question.strip() and not run_question:
    st.markdown(
        "<p style='color:#999; font-size:0.9rem; margin-top:8px;'>"
        "Pick an example above or type your own question."
        "</p>",
        unsafe_allow_html=True,
    )


def source_label(table: str | None) -> str:
    return f"{SOURCE_LABELS.get(table, table)} · `{table}`" if table else "—"


def render_chart(rows: list[dict]):
    """Bar chart for multi-row results: first text column vs first numeric column."""
    if not rows or len(rows) < 2 or len(rows) > 50:
        return
    df = pd.DataFrame([dict(r) for r in rows])
    numeric, text = [], []
    for col in df.columns:
        converted = pd.to_numeric(df[col], errors="coerce")
        if converted.notna().all():
            df[col] = converted
            numeric.append(col)
        else:
            text.append(col)
    if not text or not numeric:
        return
    x, y = text[0], numeric[0]
    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X(f"{x}:N", sort="-y", title=x),
        y=alt.Y(f"{y}:Q", title=y),
        tooltip=[x, y],
    ).properties(height=300)
    st.altair_chart(chart, use_container_width=True)


# ── Run query ─────────────────────────────────────────────────────────────────
active_question = chip_question or question
if (run_question or chip_question) and active_question.strip():
    with st.spinner("Analyzing your question..."):
        result = answer_question(
            active_question,
            simulate_bad_sql=simulate_bad_sql,
            extract_tableau_filters=False,
        )

    # 1. Routing decision
    routing = result.get("routing")
    if routing:
        with st.container(border=True):
            st.caption("ROUTING DECISION")
            st.markdown(f"**→ {source_label(routing['table'])}**")
            if routing.get("reason"):
                st.markdown(f"*{routing['reason'].replace('$', chr(92) + '$')}*")
            if routing.get("runner_up"):
                st.caption(f"Runner-up: {source_label(routing['runner_up'])}")

    # 2. Answer
    header = "### Answer"
    if result.get("retried") and not result.get("blocked") and result.get("results") is not None:
        header += " &nbsp; :orange-badge[:material/healing: Self-corrected]"
    st.markdown(header)
    answer_md = result["answer"].replace("$", "\\$")
    if result.get("blocked") or result.get("results") is None:
        st.warning(answer_md)
    else:
        with st.container(border=True):
            st.markdown(answer_md)

    # 3. Chart
    rows = result.get("results")
    render_chart(rows)

    # 4. Row count + collapsibles
    if rows is not None:
        st.caption(f"{len(rows)} row{'s' if len(rows) != 1 else ''} returned")

    if result.get("sql"):
        with st.expander("Generated SQL"):
            st.code(result["sql"], language="sql")

    if result.get("retried"):
        with st.expander("Self-correction details"):
            if result.get("simulated"):
                st.caption("Demo toggle was on: the first query was deliberately corrupted.")
            st.markdown("**First query (failed)**")
            st.code(result.get("first_sql") or "", language="sql")
            st.markdown("**Postgres error**")
            st.code(result.get("first_error") or "", language="text")
            st.markdown("**Corrected query** is shown under *Generated SQL*.")

elif run_question and not active_question.strip():
    st.warning("Please enter a question.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(
    "<div class='footer'>Personal project. Sample data only.</div>",
    unsafe_allow_html=True,
)
