from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import os
from .db import init_db, run_readonly
from .engine import generate_sql, build_answer, classify_kind
from .guardrails import validate_sql, Blocked, detect_manipulation_intent, ROLE_TABLES
from . import llm as llm_mod
from . import rag as rag_mod

app = FastAPI(title="SouthCity AI Data Query Assistant", version="1.1.0")

class AskRequest(BaseModel):
    question: str
    user_role: Optional[str] = None

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/health")
def health():
    mode = os.environ.get("TEXT2SQL_MODE", "deterministic")
    return {"status": "ok", "service": "southcity-ai-text-to-sql",
            "text2sql_mode": mode, "llm_configured": llm_mod.llm_configured(),
            "llm_model": os.environ.get("LLM_MODEL") if llm_mod.llm_configured() else None,
            "db_backend": os.environ.get("DB_BACKEND", "sqlite").lower(),
            "rag_backend": rag_mod.active_backend(),
            "sample_data": os.environ.get("SAMPLE_DATA", "1") != "0"}

def _run(sql, params, kind, role, question, engine_tag, rag_ctx=None):
    sql = validate_sql(sql, role)  # guardrail on generated SQL, whatever its source
    cols, rows = run_readonly(sql, params)
    answer, rows = build_answer(kind, rows, {})
    resp = {"status": "ok", "user_role": role, "question": question, "engine": engine_tag,
            "sql": sql, "answer": answer, "columns": cols, "data": rows, "row_count": len(rows)}
    if rag_ctx is not None:
        resp["rag"] = {"tables": rag_ctx["tables"], "glossary_hits": len(rag_ctx["glossary"]),
                       "examples": len(rag_ctx["examples"]),
                       "backend": rag_ctx.get("backend", "token-overlap")}
    return resp

@app.post("/ask")
@app.post("/query")
async def ask(payload: AskRequest, request: Request,
              user_role_header: Optional[str] = Header(default=None, alias="user_role"),
              x_user_role: Optional[str] = Header(default=None, alias="X-User-Role")):
    role = payload.user_role or user_role_header or x_user_role
    if not role:
        return JSONResponse(status_code=400, content={"status":"rejected","category":"RBAC","answer":"Header/body user_role wajib diisi: Sales_Staff atau Management."})
    try:
        # Layer 0 always runs first, in every mode: a manipulation /
        # prompt-injection question never even reaches an LLM or the DB.
        detect_manipulation_intent(payload.question)

        # Question-level RBAC pre-check: if the question is *about* a table
        # this role may not access, refuse before any generation happens.
        # (Otherwise a generator denied that table's context may improvise
        # a table-less SELECT instead of the access refusal the caller is
        # entitled to.) Deliberately runs on intent, not on generated SQL.
        forbidden_intent = rag_mod.intended_tables(payload.question) - ROLE_TABLES.get(role, set())
        if forbidden_intent:
            raise Blocked("RBAC", f"Akses ditolak untuk role {role}: pertanyaan ini menyangkut tabel {', '.join(sorted(forbidden_intent))} yang hanya dapat diakses oleh Management.")

        # RAG retrieval runs in every mode: it feeds the LLM prompt in
        # llm mode, and its summary is reported in the response either
        # way so reviewers can see exactly which context was selected.
        try:
            rag_ctx = rag_mod.retrieve(payload.question, role)
        except Exception:
            rag_ctx = None

        mode = os.environ.get("TEXT2SQL_MODE", "deterministic").lower()
        if mode == "llm" and llm_mod.llm_configured():
            try:
                raw_sql = llm_mod.propose_sql(payload.question, role)
            except Exception:
                raw_sql = None  # LLM unreachable/unparseable -> deterministic fallback below
            if raw_sql is not None:
                # Security verdicts (RBAC / READ_ONLY) from validate_sql are final:
                # they propagate as Blocked and are NOT softened by the fallback.
                # A plain execution failure (e.g. hallucinated column) is not a
                # security verdict: fall through to the deterministic engine.
                kind = classify_kind(raw_sql)
                try:
                    return _run(raw_sql, (), kind, role, payload.question, f"llm:{os.environ.get('LLM_MODEL')}", rag_ctx)
                except Blocked:
                    raise
                except Exception:
                    pass
            sql, params, kind = generate_sql(payload.question)
            return _run(sql, params, kind, role, payload.question, "deterministic (llm fallback)", rag_ctx)

        sql, params, kind = generate_sql(payload.question)
        return _run(sql, params, kind, role, payload.question, "deterministic", rag_ctx)
    except Blocked as e:
        return JSONResponse(status_code=403, content={"status":"rejected","category":e.category,"user_role":role,"question":payload.question,"answer":e.message})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status":"error","answer":str(e)})

@app.get("/")
def index():
    p = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    return FileResponse(os.path.abspath(p))
