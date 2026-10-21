import re, os, json
from .guardrails import detect_manipulation_intent, Blocked
from .db import list_customers

MONTHS_ID = {"januari":1,"februari":2,"maret":3,"april":4,"mei":5,"juni":6,"juli":7,"agustus":8,"september":9,"oktober":10,"november":11,"desember":12,
             "january":1,"february":2,"march":3,"may":5,"june":6,"july":7,"august":8,"october":10,"december":12}

def format_rupiah(n):
    if n is None: n = 0
    return "Rp" + f"{int(round(float(n))):,}".replace(",", ".")

def _period(q):
    m = re.search(r"bulan\s+(\d{1,2})\s+tahun\s+(\d{4})", q)
    if m: return int(m.group(1)), int(m.group(2))
    for name, num in MONTHS_ID.items():
        m = re.search(rf"\b{name}\s+(\d{{4}})", q)
        if m: return num, int(m.group(1))
    m = re.search(r"periode\s+(\d{1,2})/(\d{4})", q)
    if m: return int(m.group(1)), int(m.group(2))
    return None, None

def _customer(q):
    try: customers = list_customers()
    except Exception: customers = ["Siti Rahmawati","Budi Santoso","PT Sukses Bersama","CV Megah Karya","Hendrik Wijaya"]
    for c in customers:
        if c.lower() in q: return c
    return None

def generate_sql(question: str):
    """Deterministic Text-to-SQL for the ERP domain (no LLM key required,
    fully reproducible for the assessment). If LLM_API_KEY is set, an LLM
    may propose SQL instead — it still passes through the same guardrails
    in main.py before execution (see README architecture)."""
    detect_manipulation_intent(question)
    q = question.lower()
    customer = _customer(q)
    month, year = _period(q)
    unit_m = re.search(r"\b(sm|sp)\s?(\d{4})\b", q)
    unit_number = f"{unit_m.group(1).upper()} {unit_m.group(2)}" if unit_m else None

    # Q4 — General Ledger (checked before generic billing/sales: it mentions GL explicitly)
    if "gl_journals" in q or "jurnal" in q or "general ledger" in q or "kas & bank" in q:
        sql = "SELECT JournalID, AccountCode, AccountName, Debit, Credit, TransactionDate FROM GL_Journals WHERE AccountName = 'Kas & Bank'"
        params = []
        if month and year:
            sql += " AND TransactionDate >= ? AND TransactionDate < ?"
            start = f"{year}-{month:02d}-01"
            nm, ny = (month+1, year) if month < 12 else (1, year+1)
            params += [start, f"{ny}-{nm:02d}-01"]
        sql += " ORDER BY TransactionDate, JournalID"
        return sql, tuple(params), "gl"

    # Q3 — Unit history
    if unit_number and ("riwayat" in q or "unit" in q or "transaksi" in q):
        sql = """SELECT u.UnitNumber, u.Tower, u.Status, sc.ContractID, sc.CustomerName, sc.SalesAmount, sc.ContractDate,
                        ib.InvoiceID, ib.PeriodMonth, ib.PeriodYear, ib.AmountBilled, ib.AmountPaid,
                        (ib.AmountBilled - ib.AmountPaid) AS AmountOutstanding
                 FROM Units u
                 LEFT JOIN Sales_Contracts sc ON sc.UnitID = u.UnitID
                 LEFT JOIN Invoices_Billing ib ON ib.ContractID = sc.ContractID
                 WHERE u.UnitNumber = ? ORDER BY ib.PeriodYear, ib.PeriodMonth"""
        return sql, (unit_number,), "unit_history"

    # Q1 — Billing arrears
    if ("tunggakan" in q or "billing" in q or "tagihan" in q) and customer:
        sql = """SELECT sc.CustomerName, ib.PeriodMonth, ib.PeriodYear,
                        SUM(ib.AmountBilled) AS TotalBilled, SUM(ib.AmountPaid) AS TotalPaid,
                        SUM(ib.AmountBilled - ib.AmountPaid) AS TotalOutstanding
                 FROM Invoices_Billing ib JOIN Sales_Contracts sc ON sc.ContractID = ib.ContractID
                 WHERE sc.CustomerName = ?"""
        params = [customer]
        if month and year:
            sql += " AND ib.PeriodMonth = ? AND ib.PeriodYear = ?"
            params += [month, year]
        sql += " GROUP BY sc.CustomerName, ib.PeriodMonth, ib.PeriodYear"
        return sql, tuple(params), "arrears"

    # Q2 — Sales aggregation
    if ("kontrak" in q or "sales" in q) and customer:
        sql = """SELECT CustomerName, COUNT(*) AS ContractCount, SUM(SalesAmount) AS TotalSalesAmount
                 FROM Sales_Contracts WHERE CustomerName = ? GROUP BY CustomerName"""
        return sql, (customer,), "sales_total"

    raise Blocked("UNSUPPORTED", "Pertanyaan belum dapat dipahami. Coba sebutkan nama customer, nomor unit, periode, atau akun GL secara eksplisit. Contoh pertanyaan ada di README.")

def classify_kind(sql: str):
    """Infer the answer-builder kind from a (validated) SQL statement.
    Used for LLM-proposed SQL, which arrives without an intent label."""
    s = sql.upper()
    if "GL_JOURNALS" in s: return "gl"
    if "INVOICES_BILLING" in s and "SALES_CONTRACTS" in s and "LEFT JOIN" in s: return "unit_history"
    if "INVOICES_BILLING" in s: return "arrears"
    if "UNITS" in s: return "unit_history"
    if "SALES_CONTRACTS" in s: return "sales_total"
    return "generic"

def _generic_answer(rows):
    if not rows: return "Tidak ditemukan data yang sesuai.", rows
    return f"Ditemukan {len(rows)} baris data yang sesuai dengan pertanyaan Anda.", rows

def build_answer(kind, rows, ctx):
    if kind == "arrears":
        if not rows: return "Tidak ditemukan tagihan pada periode tersebut.", rows
        if "TotalOutstanding" not in rows[0]: return _generic_answer(rows)
        total = sum(float(r["TotalOutstanding"] or 0) for r in rows)
        name = rows[0]["CustomerName"]
        return f"Sisa tunggakan billing {name} untuk periode bulan {rows[0]['PeriodMonth']} tahun {rows[0]['PeriodYear']} adalah {format_rupiah(total)}.", rows
    if kind == "sales_total":
        if not rows: return "Tidak ditemukan kontrak sales atas nama tersebut.", rows
        r = rows[0]
        if "TotalSalesAmount" not in r: return _generic_answer(rows)
        return f"Total nilai kontrak sales atas nama {r['CustomerName']} di SouthCity adalah {format_rupiah(r['TotalSalesAmount'])} dari {r['ContractCount']} kontrak.", rows
    if kind == "unit_history":
        if not rows: return "Unit tidak ditemukan.", rows
        r = rows[0]
        if "UnitNumber" not in r: return _generic_answer(rows)
        if r.get("ContractID") is None:
            return f"Unit {r['UnitNumber']} ({r['Tower']}) berstatus {r['Status']} dan tidak memiliki riwayat transaksi sales maupun tagihan billing.", rows
        return f"Ditemukan {len(rows)} baris riwayat transaksi sales dan billing untuk unit {r['UnitNumber']} ({r['Tower']}, status {r['Status']}).", rows
    if kind == "gl":
        if rows and "Debit" not in rows[0]: return _generic_answer(rows)
        total_debit = sum(float(r["Debit"] or 0) for r in rows)
        return f"Ditemukan {len(rows)} catatan jurnal akun Kas & Bank pada periode tersebut, total Debit {format_rupiah(total_debit)}.", rows
    return _generic_answer(rows)
