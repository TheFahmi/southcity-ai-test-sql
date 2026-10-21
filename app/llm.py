"""Optional LLM Text-to-SQL proposer (OpenAI-compatible endpoint).

The LLM only *proposes* SQL. Every proposal is validated by the same
guardrails (read-only + RBAC) and executed on a read-only connection,
exactly like SQL from the deterministic engine. A jailbroken or
hallucinating LLM therefore cannot write data or cross role boundaries.

Configuration (environment):
  TEXT2SQL_MODE   deterministic (default) | llm
  LLM_BASE_URL    e.g. https://api.openai.com/v1  or any OpenAI-compatible gateway
  LLM_API_KEY     API key for that endpoint
  LLM_MODEL       e.g. gpt-4o-mini
"""
import os, re, json, urllib.request, urllib.error
from . import rag

# The prompt is no longer a static full-schema dump: rag.build_prompt()
# retrieves only the tables, glossary entries, and few-shot examples
# relevant to the question — and never retrieves tables the caller's
# role may not access (see app/rag.py).

def llm_configured():
    return bool(os.environ.get("LLM_API_KEY") and os.environ.get("LLM_MODEL"))

def extract_sql(text: str) -> str:
    t = text.strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", t, re.S | re.I)
    if m: t = m.group(1).strip()
    # Keep from first SELECT/WITH to end of that statement
    m = re.search(r"(?is)\b(SELECT|WITH)\b.*", t)
    if not m: raise ValueError("LLM response contains no SELECT statement")
    return m.group(0).strip().rstrip(";") + ""

def propose_sql(question: str, role: str = "Management", timeout=30) -> str:
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ["LLM_API_KEY"]
    model = os.environ["LLM_MODEL"]
    prompt, _ctx = rag.build_prompt(question, role)
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ],
    }).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    content = d["choices"][0]["message"]["content"]
    return extract_sql(content)
