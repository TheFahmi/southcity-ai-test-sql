from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import os
from .db import init_db, run_readonly
from .engine import generate_sql, build_answer, format_rupiah
from .guardrails import validate_sql, Blocked

app = FastAPI(title="SouthCity AI Data Query Assistant", version="1.0.0")

class AskRequest(BaseModel):
    question: str
    user_role: Optional[str] = None

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/health")
def health():
    return {"status": "ok", "service": "southcity-ai-text-to-sql"}

@app.post("/ask")
@app.post("/query")
async def ask(payload: AskRequest, request: Request,
              user_role_header: Optional[str] = Header(default=None, alias="user_role"),
              x_user_role: Optional[str] = Header(default=None, alias="X-User-Role")):
    role = payload.user_role or user_role_header or x_user_role
    if not role:
        return JSONResponse(status_code=400, content={"status":"rejected","category":"RBAC","answer":"Header/body user_role wajib diisi: Sales_Staff atau Management."})
    try:
        sql, params, kind = generate_sql(payload.question)
        sql = validate_sql(sql, role)  # guardrail on generated SQL, whatever its source
        cols, rows = run_readonly(sql, params)
        answer, rows = build_answer(kind, rows, {})
        # Add formatted companions for money columns, keep raw numbers intact
        return {"status":"ok","user_role":role,"question":payload.question,"sql":sql,"answer":answer,"columns":cols,"data":rows,"row_count":len(rows)}
    except Blocked as e:
        status = 403
        return JSONResponse(status_code=status, content={"status":"rejected","category":e.category,"user_role":role,"question":payload.question,"answer":e.message})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status":"error","answer":str(e)})

@app.get("/")
def index():
    p = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    return FileResponse(os.path.abspath(p))
