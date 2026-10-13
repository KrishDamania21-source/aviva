"""
Self-healing retry tests.  Run:  python tests/test_retry.py
All Claude/DB calls are stubbed — no network.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pipeline
from sql_guard import BLOCKED_MESSAGE

STUBBED = ("search_index", "get_table_schema", "generate_sql", "fix_sql",
           "execute_sql", "format_answer", "extract_filters")


class Harness:
    """Stubs the pipeline's external calls and records what was called."""

    def __init__(self, generated, fixed=None, failures=0):
        self.generated, self.fixed, self.failures = generated, fixed, failures
        self.executed, self.fix_calls = [], []

    def __enter__(self):
        self.saved = {n: getattr(pipeline, n) for n in STUBBED}
        pipeline.search_index = lambda *a, **k: [{"table_name": "sales_data"}]
        pipeline.get_table_schema = lambda *a, **k: "region (text)"
        pipeline.generate_sql = lambda *a, **k: self.generated
        pipeline.fix_sql = self._fix
        pipeline.execute_sql = self._execute
        pipeline.format_answer = lambda q, sql, rows: f"answer from {sql}"
        pipeline.extract_filters = lambda *a, **k: []
        return self

    def __exit__(self, *exc):
        for n, f in self.saved.items():
            setattr(pipeline, n, f)

    def _fix(self, question, table, schema, failed_sql, error):
        self.fix_calls.append((failed_sql, error))
        return self.fixed

    def _execute(self, sql):
        self.executed.append(sql)
        if len(self.executed) <= self.failures:
            raise RuntimeError('column "regoin" does not exist')
        return [{"region": "West"}]


def test_success_first_try_no_retry():
    with Harness("SELECT region FROM sales_data") as h:
        r = pipeline.answer_question("q")
    assert h.fix_calls == [] and len(h.executed) == 1
    assert r["retried"] is False


def test_execution_error_retries_once_and_recovers():
    with Harness('SELECT "regoin" FROM sales_data',
                 fixed='SELECT "region" FROM sales_data', failures=1) as h:
        r = pipeline.answer_question("q")
    assert len(h.fix_calls) == 1
    assert h.fix_calls[0][0] == 'SELECT "regoin" FROM sales_data'
    assert "does not exist" in h.fix_calls[0][1]          # error text reaches Claude
    assert h.executed == ['SELECT "regoin" FROM sales_data', 'SELECT "region" FROM sales_data']
    assert r["retried"] is True and r["answer"] == 'answer from SELECT "region" FROM sales_data'


def test_blocked_first_query_does_not_retry():
    with Harness("DROP TABLE sales_data", fixed="SELECT 1") as h:
        r = pipeline.answer_question("q")
    assert h.fix_calls == [] and h.executed == []
    assert r["answer"] == BLOCKED_MESSAGE


def test_retried_sql_goes_through_guard():
    with Harness('SELECT "regoin" FROM sales_data',
                 fixed="DROP TABLE sales_data", failures=1) as h:
        r = pipeline.answer_question("q")
    assert len(h.fix_calls) == 1
    assert h.executed == ['SELECT "regoin" FROM sales_data']   # the DROP never executed
    assert r["answer"] == BLOCKED_MESSAGE and "DROP" in r["blocked"]


def test_retry_fails_friendly_message_no_trace():
    with Harness('SELECT "regoin" FROM sales_data',
                 fixed='SELECT "regionn" FROM sales_data', failures=2) as h:
        r = pipeline.answer_question("q")
    assert len(h.fix_calls) == 1 and len(h.executed) == 2    # exactly one retry
    assert r["answer"] == pipeline.RETRY_FAILED_MESSAGE
    for leak in ("Traceback", "RuntimeError", "does not exist"):
        assert leak not in r["answer"]


def test_unexpected_error_is_friendly():
    with Harness("SELECT region FROM sales_data"):
        pipeline.format_answer = lambda *a: (_ for _ in ()).throw(ValueError("boom internals"))
        r = pipeline.answer_question("q")
    assert r["answer"] == pipeline.GENERIC_ERROR_MESSAGE


def test_strip_fences():
    assert pipeline._strip_fences("```sql\nSELECT 1\n```") == "SELECT 1"
    assert pipeline._strip_fences("SELECT 1") == "SELECT 1"


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
