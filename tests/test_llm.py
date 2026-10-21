import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("ERP_DB_PATH", "/tmp/test_erp_southcity.db")
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import llm as llm_mod
from app.llm import extract_sql

c = TestClient(app)
BENIGN = "Tampilkan ringkasannya untuk saya."

def _enable_llm(monkeypatch, fn):
    monkeypatch.setenv("TEXT2SQL_MODE", "llm")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "mock-model")
    monkeypatch.setattr(llm_mod, "propose_sql", lambda q, role="Management": fn(q))

def test_extract_sql_plain_and_fenced():
    assert extract_sql("SELECT 1").startswith("SELECT")
    assert extract_sql("```sql\nSELECT * FROM Units;\n```").startswith("SELECT")
    with pytest.raises(ValueError):
        extract_sql("Maaf, saya tidak tahu.")

def test_llm_good_sql_passes_with_engine_tag(monkeypatch):
    sql = """SELECT sc.CustomerName, ib.PeriodMonth, ib.PeriodYear, SUM(ib.AmountBilled) AS TotalBilled,
             SUM(ib.AmountPaid) AS TotalPaid, SUM(ib.AmountBilled - ib.AmountPaid) AS TotalOutstanding
             FROM Invoices_Billing ib JOIN Sales_Contracts sc ON sc.ContractID = ib.ContractID
             WHERE sc.CustomerName = 'Siti Rahmawati' AND ib.PeriodMonth = 10 AND ib.PeriodYear = 2026
             GROUP BY sc.CustomerName, ib.PeriodMonth, ib.PeriodYear"""
    _enable_llm(monkeypatch, lambda q: sql)
    r = c.post("/ask", json={"question": BENIGN, "user_role": "Sales_Staff"})
    assert r.status_code == 200, r.text
    assert "Rp10.500.000" in r.json()["answer"]
    assert r.json()["engine"] == "llm:mock-model"

def test_llm_delete_proposal_blocked(monkeypatch):
    _enable_llm(monkeypatch, lambda q: "DELETE FROM GL_Journals WHERE JournalID = 901")
    r = c.post("/ask", json={"question": BENIGN, "user_role": "Management"})
    assert r.status_code == 403 and r.json()["category"] == "READ_ONLY"

def test_llm_gl_proposal_blocked_for_sales(monkeypatch):
    _enable_llm(monkeypatch, lambda q: "SELECT * FROM GL_Journals")
    r = c.post("/ask", json={"question": BENIGN, "user_role": "Sales_Staff"})
    assert r.status_code == 403 and r.json()["category"] == "RBAC"

def test_llm_failure_falls_back_to_deterministic(monkeypatch):
    def boom(q): raise RuntimeError("llm down")
    _enable_llm(monkeypatch, boom)
    r = c.post("/ask", json={"question": "Berapa total nilai kontrak sales atas nama Budi Santoso di SouthCity?", "user_role": "Management"})
    assert r.status_code == 200, r.text
    assert "Rp2.700.000.000" in r.json()["answer"]
    assert "fallback" in r.json()["engine"]
