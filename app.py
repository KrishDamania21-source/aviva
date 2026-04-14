import streamlit as st
import pandas as pd
import altair as alt
from pipeline import answer_question

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

# Header
st.title("Aviva")
st.markdown("*Ask your sales data anything*")
st.markdown("---")

# Input section
question = st.text_input(
    "Your question:",
    placeholder="e.g., Who is the top performing sales rep?",
)

# Submit button
if st.button("Ask", type="primary", use_container_width=True):
    if question.strip():
        # Show spinner while processing
        with st.spinner("Analyzing your question..."):
            result = answer_question(question)

        # Show answer with copy button
        st.markdown("### Answer")
        st.text_area(
            label="Answer",
            value=result["answer"],
            disabled=True,
            label_visibility="collapsed",
            height=150
        )

        # Show data source in expander
        table_name = result.get("table_name")
        if table_name:
            with st.expander("View Data Source"):
                st.markdown(f"**Table:** `{table_name}`")

        # Show SQL in expander
        if result["sql"]:
            with st.expander("View SQL Query"):
                st.code(result["sql"], language="sql")

        # Show chart if applicable
        if result.get("results") and len(result["results"]) >= 2:
            table_name = result.get("table_name")
            results = result["results"]

            with st.expander("View Chart"):
                # Convert results to DataFrame
                df = pd.DataFrame([dict(row) for row in results])

                if table_name == "sales_data" and "region" in df.columns:
                    # Find revenue column (could be total_amount, total_sales, etc.)
                    revenue_col = next(
                        (col for col in df.columns if "total" in col.lower() or "amount" in col.lower()),
                        None
                    )
                    if revenue_col:
                        chart_data = df.groupby("region")[revenue_col].sum().reset_index()
                        chart_data.columns = ["Region", "Revenue"]
                        chart = alt.Chart(chart_data).mark_bar().encode(
                            x=alt.X("Region", sort="-y"),
                            y="Revenue"
                        ).properties(width=600, height=300)
                        st.altair_chart(chart, use_container_width=True)

                elif table_name == "marketing_data" and "channel" in df.columns:
                    # Find revenue column (could be revenue, total_revenue, etc.)
                    revenue_col = next(
                        (col for col in df.columns if "revenue" in col.lower()),
                        None
                    )
                    if revenue_col:
                        chart_data = df.groupby("channel")[revenue_col].sum().reset_index()
                        chart_data.columns = ["Channel", "Revenue"]
                        chart = alt.Chart(chart_data).mark_bar().encode(
                            x=alt.X("Channel", sort="-y"),
                            y="Revenue"
                        ).properties(width=600, height=300)
                        st.altair_chart(chart, use_container_width=True)

    else:
        st.warning("Please enter a question")
