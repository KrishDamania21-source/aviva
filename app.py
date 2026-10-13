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

st.set_page_config(page_title="Aviva", layout="centered")

# Fix word wrap in st.code blocks
st.markdown("""
<style>
    code {
        white-space: pre-wrap !important;
        word-wrap: break-word !important;
    }
    .stCodeBlock > div {
        resize: none !important;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar — demo controls
with st.sidebar:
    simulate_bad_sql = st.toggle("Demo: simulate a bad first query", value=False)
    if simulate_bad_sql:
        st.caption("The first generated query gets one column name misspelled, "
                   "so the self-correction path runs live.")

# Header
st.title("Aviva")
st.markdown("*Ask your sales and marketing data anything*")
st.markdown("---")

# Input section
question = st.text_input(
    "Your question:",
    placeholder="e.g., Who is the top performing sales rep?",
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


# Submit button
if st.button("Ask", type="primary", use_container_width=True):
    if question.strip():
        with st.spinner("Analyzing your question..."):
            result = answer_question(question, simulate_bad_sql=simulate_bad_sql,
                                     extract_tableau_filters=False)

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
        answer_md = result["answer"].replace("$", "\\$")  # stop Streamlit treating $ as LaTeX
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
                    st.caption("Demo toggle was on: this first query was deliberately corrupted.")
                st.markdown("**First query (failed)**")
                st.code(result.get("first_sql") or "", language="sql")
                st.markdown("**Postgres error**")
                st.code(result.get("first_error") or "", language="text")
                st.markdown("**Corrected query** is shown under *Generated SQL*.")

    else:
        st.warning("Please enter a question")
