import sqlite3, os, re

DB_PATH = os.environ.get("ERP_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "erp.db"))
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "schema.sql")

def _load_schema_sql():
    """Load the original T-SQL schema.sql as the single source of truth.

    The only translation needed for SQLite is the inline foreign-key
    spelling: T-SQL writes `INT FOREIGN KEY REFERENCES T(C)` in a column
    definition, SQLite writes `INT REFERENCES T(C)`. Everything else in
    schema.sql (types, multi-row INSERTs, comments) is SQLite-compatible.
    """
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        sql = f.read()
    return re.sub(r"\bFOREIGN\s+KEY\s+REFERENCES\b", "REFERENCES", sql)

def init_db():
    need_build = True
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            need_build = conn.execute("SELECT COUNT(*) FROM Units").fetchone()[0] == 0
            conn.close()
        except sqlite3.Error:
            need_build = True
    if not need_build:
        return
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_load_schema_sql())
        conn.commit()
    finally:
        conn.close()

def run_readonly(sql, params=()):
    # Second layer of read-only enforcement: SQLite URI mode=ro + query_only pragma
    init_db()
    conn = sqlite3.connect(f"file:{os.path.abspath(DB_PATH)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return cols, rows
    finally:
        conn.close()

def list_customers():
    _, rows = run_readonly("SELECT DISTINCT CustomerName FROM Sales_Contracts ORDER BY CustomerName")
    return [r["CustomerName"] for r in rows]
