"""Retrieval layer (RAG) that builds the LLM's Text-to-SQL context.

Instead of dumping the whole schema into every prompt, the retriever
selects only what the current question needs, from three knowledge
stores that all live in this repo (no external service, no API key):

  1. Schema catalog — tables/columns parsed from schema.sql, the same
     single source of truth the database itself is built from.
  2. Business glossary — Indonesian business terms mapped to their SQL
     meaning (e.g. "tunggakan" -> AmountBilled - AmountPaid).
  3. Example bank — curated question -> SQL pairs used as few-shot
     examples, scored by similarity to the incoming question.

Retrieval is RBAC-aware: it reuses guardrails.ROLE_TABLES, so tables a
role may not access (GL_Journals for Sales_Staff) are never retrieved
into that role's context at all — the restriction holds at the prompt
layer too, not only when the generated SQL is validated.

Scoring is dependency-free token overlap. If an embeddings endpoint is
configured later, replace _score() with cosine similarity; the
retrieve() interface and the prompt format stay identical.
"""
import os, re
from .guardrails import ROLE_TABLES

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "schema.sql")

STOPWORDS = {
    "yang", "di", "ke", "dari", "untuk", "pada", "dan", "atau", "adalah",
    "berapa", "tampilkan", "tunjukkan", "daftar", "data", "saya", "tolong",
    "bulan", "tahun", "periode", "atas", "nama", "dengan", "dalam",
}

SYNONYMS = {
    "Units": ["unit", "tower", "vacant", "kosong", "status", "menara"],
    "Sales_Contracts": ["kontrak", "sales", "penjualan", "customer", "pelanggan", "pembeli"],
    "Invoices_Billing": ["billing", "tagihan", "tunggakan", "invoice", "bayar", "lunas", "hutang", "piutang"],
    "GL_Journals": ["gl", "jurnal", "jurnal", "ledger", "kas", "bank", "debit", "kredit", "akun", "akuntansi"],
}

GLOSSARY = [
    (["tunggakan", "arrears", "belum lunas", "belum dibayar", "sisa tagihan"],
     "Sisa tunggakan billing = AmountBilled - AmountPaid pada tabel Invoices_Billing.",
     {"Invoices_Billing"}),
    (["total nilai kontrak", "nilai kontrak", "total kontrak"],
     "Total nilai kontrak sales = SUM(SalesAmount) pada tabel Sales_Contracts, dikelompokkan per CustomerName.",
     {"Sales_Contracts"}),
    (["vacant", "kosong", "belum terjual"],
     "Unit kosong: Units.Status = 'Vacant'. Unit yang ada tetapi Vacant tidak memiliki baris Sales_Contracts/Invoices_Billing.",
     {"Units", "Sales_Contracts", "Invoices_Billing"}),
    (["riwayat", "histori", "history"],
     "Riwayat sebuah unit: Units LEFT JOIN Sales_Contracts ON Sales_Contracts.UnitID = Units.UnitID LEFT JOIN Invoices_Billing ON Invoices_Billing.ContractID = Sales_Contracts.ContractID, filter Units.UnitNumber.",
     {"Units", "Sales_Contracts", "Invoices_Billing"}),
    (["jurnal", "kas & bank", "debit", "kredit", "gl"],
     "Catatan jurnal: tabel GL_Journals, filter AccountName (mis. 'Kas & Bank') dan rentang TransactionDate.",
     {"GL_Journals"}),
]

EXAMPLES = [
    ("Berapa sisa tunggakan billing Siti Rahmawati untuk periode bulan 10 tahun 2026?",
     "SELECT sc.CustomerName, ib.PeriodMonth, ib.PeriodYear, SUM(ib.AmountBilled) AS TotalBilled, SUM(ib.AmountPaid) AS TotalPaid, SUM(ib.AmountBilled - ib.AmountPaid) AS Outstanding FROM Invoices_Billing ib JOIN Sales_Contracts sc ON sc.ContractID = ib.ContractID WHERE sc.CustomerName = 'Siti Rahmawati' AND ib.PeriodMonth = 10 AND ib.PeriodYear = 2026 GROUP BY sc.CustomerName, ib.PeriodMonth, ib.PeriodYear",
     {"Sales_Contracts", "Invoices_Billing"}),
    ("Berapa total nilai kontrak sales atas nama Budi Santoso di SouthCity?",
     "SELECT CustomerName, COUNT(*) AS ContractCount, SUM(SalesAmount) AS TotalSales FROM Sales_Contracts WHERE CustomerName = 'Budi Santoso' GROUP BY CustomerName",
     {"Sales_Contracts"}),
    ("Tampilkan riwayat transaksi sales dan tagihan billing untuk unit SM 1201.",
     "SELECT u.UnitNumber, u.Tower, u.Status, sc.ContractID, sc.CustomerName, sc.SalesAmount, ib.InvoiceID, ib.AmountBilled, ib.AmountPaid FROM Units u LEFT JOIN Sales_Contracts sc ON sc.UnitID = u.UnitID LEFT JOIN Invoices_Billing ib ON ib.ContractID = sc.ContractID WHERE u.UnitNumber = 'SM 1201'",
     {"Units", "Sales_Contracts", "Invoices_Billing"}),
    ("Tampilkan daftar catatan transaksi jurnal akun Kas & Bank pada tabel GL_Journals di bulan Januari 2026.",
     "SELECT JournalID, AccountCode, AccountName, Debit, Credit, TransactionDate FROM GL_Journals WHERE AccountName = 'Kas & Bank' AND TransactionDate >= '2026-01-01' AND TransactionDate < '2026-02-01' ORDER BY TransactionDate, JournalID",
     {"GL_Journals"}),
]

# FK relations from schema.sql: child -> parent. Used for one-hop graph
# expansion in schema linking (a matched table pulls in its join partners).
RELATIONS = [("Invoices_Billing", "Sales_Contracts"), ("Sales_Contracts", "Units")]

def _tokens(text):
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1}

def _score(query_tokens, doc_tokens):
    return len(query_tokens & doc_tokens)

def load_catalog():
    """Parse CREATE TABLE blocks from schema.sql -> {table: [(col, type), ...]}"""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        sql = f.read()
    catalog = {}
    for m in re.finditer(r"CREATE TABLE\s+(\w+)\s*\((.*?)\);", sql, re.S | re.I):
        table, body = m.group(1), m.group(2)
        cols = []
        for line in body.split(","):
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0].upper() not in ("FOREIGN", "PRIMARY", "CONSTRAINT"):
                cols.append((parts[0], parts[1]))
        catalog[table] = cols
    return catalog

def retrieve(question: str, role: str, top_examples: int = 2):
    """Return the RAG context for one question under one role."""
    catalog = load_catalog()
    allowed = ROLE_TABLES.get(role, set())
    visible = {t: c for t, c in catalog.items() if t.upper() in allowed}
    q = _tokens(question)

    # 1) Schema linking: score each visible table, keep matches (or all
    #    visible tables as a safe fallback when nothing matches).
    scored = []
    for table, cols in visible.items():
        doc = set()
        doc |= _tokens(table.replace("_", " "))
        for col, _typ in cols:
            doc |= _tokens(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", col))
        doc |= set(SYNONYMS.get(table, []))
        scored.append((table, _score(q, doc)))
    tables = [t for t, s in sorted(scored, key=lambda x: -x[1]) if s > 0] or list(visible)
    # One-hop FK expansion: a matched table needs its join partners to be
    # usable (e.g. a billing question also needs Sales_Contracts for the
    # customer name), appended after the directly matched tables.
    for child, parent in RELATIONS:
        for a, b in ((child, parent), (parent, child)):
            if a in tables and b in visible and b not in tables:
                tables.append(b)

    # 2) Glossary hits — also role-filtered: an entry that names a
    #    restricted table must not leak into a restricted role's context.
    qtext = question.lower()
    glossary = [hint for terms, hint, tables_g in GLOSSARY
                if {t.upper() for t in tables_g} <= allowed
                and any(term in qtext or _tokens(term) & q for term in terms)]

    # 3) Few-shot examples, restricted to examples whose tables the role
    #    may see; top-N by similarity.
    ex_scored = []
    for qtext_ex, sql_ex, tables_ex in EXAMPLES:
        if not {t.upper() for t in tables_ex} <= allowed:
            continue
        ex_scored.append(({"question": qtext_ex, "sql": sql_ex}, _score(q, _tokens(qtext_ex))))
    examples = [e for e, s in sorted(ex_scored, key=lambda x: -x[1]) if s > 0][:top_examples]

    return {"tables": tables, "glossary": glossary, "examples": examples,
            "catalog": {t: visible[t] for t in tables}}

def build_prompt(question: str, role: str):
    """Assemble the LLM prompt from retrieved context only."""
    ctx = retrieve(question, role)
    lines = [
        "You are a Text-to-SQL generator for a property ERP database.",
        "Reply with ONE SQL SELECT statement only. No explanation, no markdown fences.",
        "",
        "Relevant tables (retrieved for this question):",
    ]
    for table, cols in ctx["catalog"].items():
        colstr = ", ".join(f"{c} {t}" for c, t in cols)
        lines.append(f"{table}({colstr})")
    if ctx["glossary"]:
        lines += ["", "Business terms:"]
        lines += [f"- {g}" for g in ctx["glossary"]]
    if ctx["examples"]:
        lines += ["", "Examples:"]
        for e in ctx["examples"]:
            lines.append(f"Q: {e['question']}")
            lines.append(f"SQL: {e['sql']}")
    lines += [
        "",
        "Rules:",
        "- SELECT only. Never DELETE/UPDATE/INSERT/DROP/ALTER.",
        "- Outstanding billing = AmountBilled - AmountPaid.",
        "- Dates are ISO text 'YYYY-MM-DD'.",
        "",
        "Write the SQL for the user's question.",
    ]
    return "\n".join(lines), ctx
