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
    /* ── Base ─────────────────────────────────────────────────────────── */
    code { white-space: pre-wrap !important; word-wrap: break-word !important; }
    .stCodeBlock > div { resize: none !important; }

    /* ── Sidebar ──────────────────────────────────────────────────────── */
    section[data-testid="stSidebar"] {
        background-color: #F8FAFC !important;
    }
    .sidebar-source-name {
        color: #0F766E;
        font-weight: 700;
    }
    .sidebar-source-desc {
        color: #374151;
        font-size: 0.85rem;
    }
    .sidebar-source-row {
        margin-bottom: 10px;
        line-height: 1.4;
    }

    /* ── Header band ──────────────────────────────────────────────────── */
    .header-band {
        background: linear-gradient(135deg, #CCFBF1 0%, #F0FDFA 60%, #FFFFFF 100%);
        border-radius: 10px;
        padding: 20px 24px 16px 24px;
        margin-bottom: 4px;
    }
    .header-band h1 {
        font-size: 2.2rem;
        font-weight: 800;
        color: #0F4C45;
        margin: 0 0 4px 0;
        line-height: 1.1;
    }
    .header-band p {
        font-size: 1rem;
        color: #374151;
        margin: 0;
    }

    /* ── Pipeline strip ───────────────────────────────────────────────── */
    .pipeline-strip {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 4px;
        background: #F0FDFA;
        border-radius: 8px;
        padding: 10px 14px;
        margin: 10px 0 18px 0;
    }
    .step-pill {
        background: #CCFBF1;
        color: #0F766E;
        font-size: 0.76rem;
        font-weight: 600;
        border-radius: 20px;
        padding: 3px 10px;
        white-space: nowrap;
    }
    .step-sep {
        color: #0F766E;
        font-size: 0.9rem;
        font-weight: 600;
        padding: 0 1px;
    }
    .pipeline-tagline {
        width: 100%;
        font-style: italic;
        font-size: 0.76rem;
        color: #6B7280;
        margin-top: 6px;
    }

    /* ── Example chip buttons ─────────────────────────────────────────── */
    div[data-testid="stButton"] > button[kind="secondary"] {
        background: #FFFFFF !important;
        border: 1.5px solid #0F766E !important;
        border-radius: 20px !important;
        color: #0F766E !important;
        font-size: 0.82rem !important;
        padding: 4px 14px !important;
        transition: background 0.15s, color 0.15s;
    }
    div[data-testid="stButton"] > button[kind="secondary"]:hover {
        background: #0F766E !important;
        color: #FFFFFF !important;
    }

    /* ── Routing box ──────────────────────────────────────────────────── */
    .routing-box {
        background: #EFF6FF;
        border-left: 4px solid #3B82F6;
        border-radius: 0 6px 6px 0;
        padding: 12px 16px;
        margin-bottom: 16px;
    }
    .routing-label {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: #6B7280;
        margin-bottom: 4px;
    }
    .routing-table {
        font-size: 1rem;
        font-weight: 700;
        color: #1E40AF;
        margin-bottom: 4px;
    }
    .routing-reason {
        font-size: 0.88rem;
        color: #374151;
        font-style: italic;
        margin-bottom: 4px;
    }
    .routing-runner-up {
        font-size: 0.78rem;
        color: #9CA3AF;
    }

    /* ── Answer card ──────────────────────────────────────────────────── */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border: none !important;
        border-left: 4px solid #0F766E !important;
        border-radius: 0 8px 8px 0 !important;
        box-shadow: 0 2px 8px rgba(15, 118, 110, 0.10) !important;
        padding-left: 4px;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] p {
        font-size: 1.02rem;
    }

    /* ── Self-corrected amber pill ────────────────────────────────────── */
    .self-corrected-pill {
        background: #F59E0B;
        color: #FFFFFF;
        font-size: 0.72rem;
        font-weight: 700;
        border-radius: 20px;
        padding: 2px 10px;
        vertical-align: middle;
        margin-left: 8px;
        letter-spacing: 0.03em;
    }

    /* ── Read-only check pill ─────────────────────────────────────────── */
    .readonly-pill {
        background: #D1FAE5;
        color: #065F46;
        font-size: 0.72rem;
        font-weight: 700;
        border-radius: 20px;
        padding: 2px 10px;
        vertical-align: middle;
        letter-spacing: 0.03em;
    }

    /* ── Footer ───────────────────────────────────────────────────────── */
    .footer {
        margin-top: 48px;
        padding-top: 12px;
        border-top: 1px solid #E0E4EC;
        font-size: 0.76rem;
        color: #9CA3AF;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Data sources")
    for key, desc in DATA_SOURCE_DESCRIPTIONS.items():
        label = SOURCE_LABELS[key]
        st.markdown(
            f'<div class="sidebar-source-row">'
            f'<span class="sidebar-source-name">{label}</span>'
            f'<span class="sidebar-source-desc"> — {desc}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("**Demo controls**")
    simulate_bad_sql = st.toggle("Simulate a bad first query", value=False)
    if simulate_bad_sql:
        st.caption(
            "The first generated query gets one column name misspelled "
            "so the self-correction path runs live."
        )

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header-band">
    <h1>Aviva</h1>
    <p>Ask your sales and marketing data anything.</p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="pipeline-strip">
    <span class="step-pill">Question</span>
    <span class="step-sep">&rsaquo;</span>
    <span class="step-pill">Pick data source</span>
    <span class="step-sep">&rsaquo;</span>
    <span class="step-pill">Write SQL</span>
    <span class="step-sep">&rsaquo;</span>
    <span class="step-pill">Read-only check</span>
    <span class="step-sep">&rsaquo;</span>
    <span class="step-pill">Run</span>
    <span class="step-sep">&rsaquo;</span>
    <span class="step-pill">Explain</span>
    <span class="pipeline-tagline">Self-correcting, read-only, and it shows its reasoning.</span>
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
    chart = alt.Chart(df).mark_bar(color="#0F766E").encode(
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
        table_html = source_label(routing["table"]).replace("`", "")
        reason_html = (
            f'<div class="routing-reason">{routing["reason"].replace("$", "&#36;")}</div>'
            if routing.get("reason") else ""
        )
        runner_up_html = (
            f'<div class="routing-runner-up">Runner-up: {source_label(routing["runner_up"]).replace("`", "")}</div>'
            if routing.get("runner_up") else ""
        )
        st.markdown(f"""
<div class="routing-box">
    <div class="routing-label">ROUTED TO</div>
    <div class="routing-table">&rarr; {table_html}</div>
    {reason_html}
    {runner_up_html}
</div>
""", unsafe_allow_html=True)

    # 2. Answer
    if result.get("retried") and not result.get("blocked") and result.get("results") is not None:
        st.markdown(
            '### Answer &nbsp; <span class="self-corrected-pill">Self-corrected</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown("### Answer")
    if result.get("sql") and not result.get("blocked"):
        st.markdown(
            '<span class="readonly-pill">Read-only check passed</span>',
            unsafe_allow_html=True,
        )
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
