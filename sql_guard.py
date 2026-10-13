"""
sql_guard.py — read-only gate for LLM-generated SQL.

Every generated query passes through check_sql() before it touches a database.
Only a single SELECT or WITH statement is allowed.
"""

import re

FORBIDDEN = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT",
             "INTO")  # INTO: Postgres `SELECT ... INTO t` creates a table
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.IGNORECASE)

BLOCKED_MESSAGE = (
    "I can only run read-only queries, and the query generated for that question "
    "wasn't one. Try rephrasing it as a question about your data."
)


def _scan(sql: str) -> tuple[str, str]:
    """Single pass over the SQL.

    Returns (cleaned, masked):
      cleaned — comments removed, everything else intact (this is what executes)
      masked  — also blanks the contents of string literals and quoted identifiers,
                so keyword/semicolon checks can't be fooled by text inside quotes
    """
    cleaned, masked = [], []
    i, n = 0, len(sql)
    while i < n:
        c, nxt = sql[i], sql[i + 1] if i + 1 < n else ""
        if c == "-" and nxt == "-":                      # line comment
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":                      # block comment
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            cleaned.append(" "); masked.append(" ")
            continue
        if c in ("'", '"'):                              # string literal / quoted identifier
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:    # doubled quote = escaped
                        j += 2
                        continue
                    break
                j += 1
            chunk = sql[i:j + 1]
            cleaned.append(chunk)
            masked.append(c + " " * max(len(chunk) - 2, 0) + c)
            i = j + 1
            continue
        cleaned.append(c); masked.append(c)
        i += 1
    return "".join(cleaned), "".join(masked)


def check_sql(sql: str) -> tuple[bool, str, str]:
    """Return (allowed, cleaned_sql, reason). reason is '' when allowed."""
    if not sql or not sql.strip():
        return False, "", "empty query"

    cleaned, masked = _scan(sql)
    cleaned = cleaned.strip().rstrip(";").strip()
    masked = masked.strip().rstrip(";").strip()

    if not masked:
        return False, "", "empty query after removing comments"
    if ";" in masked:
        return False, cleaned, "multiple statements"
    if "$$" in masked:
        return False, cleaned, "dollar-quoted strings not allowed"

    first = masked.split(None, 1)[0].upper()
    if first not in ("SELECT", "WITH"):
        return False, cleaned, f"statement starts with {first}, not SELECT/WITH"

    hit = _FORBIDDEN_RE.search(masked)
    if hit:
        return False, cleaned, f"forbidden keyword {hit.group(1).upper()}"

    return True, cleaned, ""
