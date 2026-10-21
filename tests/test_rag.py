from app import rag

Q1 = "Berapa sisa tunggakan billing Siti Rahmawati untuk periode bulan 10 tahun 2026?"
Q2 = "Berapa total nilai kontrak sales atas nama Budi Santoso di SouthCity?"
Q4 = "Tampilkan daftar catatan transaksi jurnal akun Kas & Bank pada tabel GL_Journals di bulan Januari 2026."

def test_catalog_parsed_from_schema_sql():
    cat = rag.load_catalog()
    assert set(cat) == {"Units", "Sales_Contracts", "Invoices_Billing", "GL_Journals"}
    assert [c for c, _ in cat["GL_Journals"]] == ["JournalID", "AccountCode", "AccountName", "Debit", "Credit", "TransactionDate"]

def test_retrieve_q1_billing_context():
    ctx = rag.retrieve(Q1, "Sales_Staff")
    assert "Invoices_Billing" in ctx["tables"]
    assert "Sales_Contracts" in ctx["tables"]
    assert "GL_Journals" not in ctx["tables"]
    assert ctx["glossary"], "tunggakan glossary entry should hit"
    assert ctx["examples"], "a few-shot example should be retrieved"

def test_retrieve_q2_sales_top():
    ctx = rag.retrieve(Q2, "Sales_Staff")
    assert ctx["tables"][0] == "Sales_Contracts"

def test_retrieve_gl_blocked_for_sales_staff():
    ctx = rag.retrieve(Q4, "Sales_Staff")
    assert "GL_Journals" not in ctx["tables"]
    assert all("GL_Journals" not in e["sql"] for e in ctx["examples"])
    prompt, _ = rag.build_prompt(Q4, "Sales_Staff")
    assert "GL_Journals" not in prompt

def test_retrieve_gl_allowed_for_management():
    ctx = rag.retrieve(Q4, "Management")
    assert "GL_Journals" in ctx["tables"]
    assert any("GL_Journals" in e["sql"] for e in ctx["examples"])
    prompt, _ = rag.build_prompt(Q4, "Management")
    assert "GL_Journals" in prompt
