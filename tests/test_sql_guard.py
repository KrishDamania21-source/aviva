"""
Read-only SQL guard tests.  Run:  python tests/test_sql_guard.py
(no pytest needed; also works under pytest if installed)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sql_guard import check_sql, BLOCKED_MESSAGE
import pipeline

BLOCKED = [
    "DROP TABLE sales_data",
    "drop table sales_data;",
    "SELECT 1; DROP TABLE sales_data",
    "SELECT 1;\nDROP TABLE sales_data;",
    "-- harmless\nDROP TABLE sales_data",
    "/* SELECT */ DELETE FROM sales_data",
    "WITH x AS (DELETE FROM sales_data RETURNING *) SELECT * FROM x",
    "SELECT * INTO backup FROM sales_data",
    "UPDATE sales_data SET region = 'X'",
    "INSERT INTO sales_data VALUES (1)",
    "ALTER TABLE sales_data ADD COLUMN x int",
    "TRUNCATE sales_data",
    "CREATE TABLE t (x int)",
    "GRANT ALL ON sales_data TO public",
    "SELECT 1 -- ; DROP TABLE sales_data\n; DROP TABLE sales_data",
    "",
    "   -- only a comment",
]

ALLOWED = [
    "SELECT * FROM sales_data",
    "select region, sum(total_amount) from sales_data group by region;",
    'WITH t AS (SELECT * FROM sales_data) SELECT COUNT(*) FROM t',
    "SELECT * FROM sales_data WHERE customer_name = 'Drop; Delete Inc'",   # keywords inside a string
    'SELECT "created_at_label" FROM sales_data',                          # identifier, not CREATE
    "-- top reps\nSELECT sales_rep FROM sales_data",
]


def test_blocks_dangerous_sql():
    for sql in BLOCKED:
        ok, _, reason = check_sql(sql)
        assert not ok, f"should be blocked: {sql!r}"
        assert reason


def test_allows_read_only_sql():
    for sql in ALLOWED:
        ok, cleaned, reason = check_sql(sql)
        assert ok, f"should be allowed: {sql!r} ({reason})"
        assert "--" not in cleaned and not cleaned.endswith(";")


def test_pipeline_blocks_drop_before_execution():
    """Force the LLM to 'generate' a DROP and prove nothing reaches the database."""
    calls = []
    saved = (pipeline.search_index, pipeline.get_table_schema, pipeline.generate_sql, pipeline.execute_sql)
    try:
        pipeline.search_index = lambda *a, **k: [{"table_name": "sales_data"}]
        pipeline.get_table_schema = lambda *a, **k: "region (text)"
        pipeline.generate_sql = lambda *a, **k: "DROP TABLE sales_data"
        pipeline.execute_sql = lambda sql: calls.append(sql) or []
        result = pipeline.answer_question("delete everything")
    finally:
        (pipeline.search_index, pipeline.get_table_schema, pipeline.generate_sql, pipeline.execute_sql) = saved

    assert calls == [], "execute_sql must not be called for a blocked query"
    assert result["answer"] == BLOCKED_MESSAGE
    assert "DROP" in result["blocked"]


def test_database_rejects_writes_even_if_guard_bypassed():
    """Second layer: execute_sql runs in a READ ONLY transaction.
    Uses a table that doesn't exist, so this is harmless even if the layer failed."""
    if not os.environ.get("DATABASE_URL"):
        print("  (skipped: no DATABASE_URL)")
        return
    try:
        pipeline.execute_sql("DROP TABLE IF EXISTS aviva_guard_canary")
    except Exception as e:
        assert "read-only" in str(e).lower(), e
        return
    raise AssertionError("write succeeded inside read-only transaction")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
