#!/usr/bin/env python3
"""Load seed_sample.sql (+500 rows) into the SQL Server demo database.

Idempotent: if the sample sentinel unit already exists, nothing is
inserted. Connects with the credentials in the environment:
  MSSQL_HOST, MSSQL_PORT, MSSQL_DB, MSSQL_USER, MSSQL_PASSWORD
Use an admin login (the app's own login is SELECT-only by design).
Usage: python3 scripts/load_sample_sqlserver.py [--status]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SENTINEL = "SM 1301"


def main():
    import pymssql
    conn = pymssql.connect(
        server=os.environ.get("MSSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MSSQL_PORT", "1433")),
        user=os.environ["MSSQL_USER"],
        password=os.environ["MSSQL_PASSWORD"],
        database=os.environ.get("MSSQL_DB", "SouthCityERP"),
        timeout=60, login_timeout=15)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM Units WHERE UnitNumber = %s", (SENTINEL,))
    present = cur.fetchone()[0] > 0
    counts = {}
    for t in ("Units", "Sales_Contracts", "Invoices_Billing", "GL_Journals"):
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        counts[t] = cur.fetchone()[0]
    print("counts before:", counts, "| sample present:", present)
    if "--status" in sys.argv or present:
        return
    seed_path = os.path.join(os.path.dirname(__file__), "..", "seed_sample.sql")
    with open(seed_path, encoding="utf-8") as f:
        script = f.read()
    body = "\n".join(l for l in script.splitlines() if not l.startswith("--"))
    for statement in body.split(";\n"):
        statement = statement.strip()
        if "INSERT" in statement:
            cur.execute(statement)
    conn.commit()
    for t in counts:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        counts[t] = cur.fetchone()[0]
    print("counts after:", counts)
    conn.close()


if __name__ == "__main__":
    main()
