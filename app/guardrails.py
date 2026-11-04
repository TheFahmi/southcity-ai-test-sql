import re

FORBIDDEN = {"DROP","DELETE","UPDATE","INSERT","ALTER","TRUNCATE","EXEC","EXECUTE","CREATE","REPLACE","GRANT","REVOKE","MERGE","VACUUM","ATTACH","DETACH"}
ROLE_TABLES = {
    "Sales_Staff": {"UNITS","SALES_CONTRACTS","INVOICES_BILLING"},
    "Management": {"UNITS","SALES_CONTRACTS","INVOICES_BILLING","GL_JOURNALS"},
}
KNOWN_TABLES = {"UNITS","SALES_CONTRACTS","INVOICES_BILLING","GL_JOURNALS"}

class Blocked(Exception):
    def __init__(self, category, message):
        self.category = category
        self.message = message
        super().__init__(message)

def detect_manipulation_intent(question: str):
    """Layer 0: natural-language manipulation / prompt-injection intent.
    Catches Pertanyaan 5 even before any SQL is generated."""
    q = question.lower()
    manip = re.search(r"\b(hapus|delete|drop|update|insert|alter|truncate|rubah|modify|jadikan|ubah\s+(record|status|data|nilai)|ganti\s+(status|data)|perbarui\s+(data|record|status)|edit\s+(record|data|status)|set\s+status|change\s+status|(tambah|tambahkan|buat|input|masukkan)\s+(record|data|unit|kontrak|invoice|jurnal|tagihan))\b", q)
    injection = re.search(r"(abaikan instruksi|ignore (previous|all) instruction|system administrator|jailbreak|bypass)", q)
    if manip:
        raise Blocked("READ_ONLY", "Permintaan ditolak: sistem bersifat read-only. Perintah manipulasi data (DELETE/DROP/UPDATE/INSERT/ALTER) tidak diperbolehkan tanpa terkecuali.")
    if injection:
        raise Blocked("PROMPT_INJECTION", "Permintaan ditolak: klaim otoritas / instruksi untuk mengabaikan aturan sistem tidak mengubah hak akses Anda.")

def validate_sql(sql: str, user_role: str):
    """Layer 1+2: read-only enforcement + RBAC on the *generated* SQL.
    This runs regardless of how the SQL was produced (rule engine or LLM),
    so a jailbroken LLM still cannot get a write or a forbidden table executed."""
    if user_role not in ROLE_TABLES:
        raise Blocked("RBAC", f"Role tidak dikenal: {user_role}. Gunakan Sales_Staff atau Management.")
    cleaned = sql.strip().rstrip(";")
    if ";" in cleaned:
        raise Blocked("READ_ONLY", "Permintaan ditolak: hanya satu statement SELECT yang diperbolehkan.")
    if not re.match(r"(?is)^\s*(SELECT|WITH)\b", cleaned):
        raise Blocked("READ_ONLY", "Permintaan ditolak: hanya query SELECT (read-only) yang diperbolehkan.")
    if not re.search(r"(?i)\bFROM\b", cleaned):
        raise Blocked("INVALID_QUERY", "Permintaan ditolak: query harus membaca data dari tabel skema (SELECT tanpa FROM tidak diperbolehkan).")
    tokens = set(re.findall(r"[A-Za-z_]+", cleaned.upper()))
    bad = tokens & FORBIDDEN
    if bad:
        raise Blocked("READ_ONLY", f"Permintaan ditolak: kata kunci manipulasi data terdeteksi: {', '.join(sorted(bad))}.")
    # Table extraction: FROM / JOIN targets. Unknown tables are NOT
    # silently dropped: a near-match of a real table (e.g. an LLM writing
    # GL_JOURNAL for GL_JOURNALS) is treated as that table for RBAC, and
    # anything else is rejected instead of failing at execution time.
    import difflib
    raw_tables = set(t.upper() for t in re.findall(r"(?i)\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", cleaned))
    cte_names = set(t.upper() for t in re.findall(r"(?i)\b(?:WITH|,)\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", cleaned))
    tables = set()
    for t in raw_tables:
        if t in cte_names:
            continue
        if t in KNOWN_TABLES:
            tables.add(t)
            continue
        near = difflib.get_close_matches(t, KNOWN_TABLES, n=1, cutoff=0.8)
        if near:
            tables.add(near[0])
            continue
        raise Blocked("UNKNOWN_TABLE", f"Permintaan ditolak: tabel '{t}' tidak ada di skema database.")
    forbidden_tables = tables - ROLE_TABLES[user_role]
    if forbidden_tables:
        raise Blocked("RBAC", f"Akses ditolak untuk role {user_role}: tabel {', '.join(sorted(forbidden_tables))} hanya dapat diakses oleh Management.")
    return cleaned
