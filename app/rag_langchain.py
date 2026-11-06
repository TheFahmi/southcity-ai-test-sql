"""LangChain-backed retrieval: embeddings + FAISS over the same three
knowledge stores as app/rag.py (schema catalog, business glossary,
few-shot examples).

Embeddings run locally (fastembed, multilingual MiniLM) — no external
API, no key. The vector index is built once per process from the same
in-repo stores, so the schema's single source of truth is unchanged.

RBAC holds exactly as in the token-overlap retriever: documents carry
the tables they depend on as metadata and are filtered to the role's
allowed tables before anything reaches the prompt; FK one-hop expansion
and the all-visible-tables fallback mirror app/rag.py semantics.
"""
import os

from . import rag as _base
from .guardrails import ROLE_TABLES

EMBED_MODEL = os.environ.get(
    "RAG_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
# The index is built with normalize_L2=True, so FAISS distances are
# cosine-like in [0, 2]; lower is closer. Calibrated on the graded
# questions + free-form probes (scripts/probe_rag.py): relevant docs
# cluster at <= ~1.35, unrelated questions start at ~1.45. Table docs
# carry long column lists (diluted similarity), so tables also pass
# when they are within TABLE_MARGIN of the best table's distance.
TABLE_MAX_DIST = 1.30
TABLE_MARGIN = 0.12
GLOSSARY_MAX_DIST = 1.30
EXAMPLE_MAX_DIST = 1.30

_store = None


def _build_store():
    from langchain_community.embeddings import FastEmbedEmbeddings
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document

    docs = []
    catalog = _base.load_catalog()
    for table, cols in catalog.items():
        text = table.replace("_", " ") + ": " + ", ".join(
            f"{c} {t}" for c, t in cols)
        synonyms = ", ".join(_base.SYNONYMS.get(table, []))
        if synonyms:
            text += f". Istilah terkait: {synonyms}"
        docs.append(Document(page_content=text,
                             metadata={"kind": "table", "tables": table}))
    for terms, hint, tables_g in _base.GLOSSARY:
        docs.append(Document(
            page_content=", ".join(terms) + " — " + hint,
            metadata={"kind": "glossary",
                      "tables": ",".join(sorted(tables_g)), "hint": hint}))
    for qtext, sql, tables_ex in _base.EXAMPLES:
        docs.append(Document(
            page_content=qtext,
            metadata={"kind": "example",
                      "tables": ",".join(sorted(tables_ex)), "sql": sql}))
    cache_dir = os.environ.get("FASTEMBED_CACHE_PATH")
    embeddings = FastEmbedEmbeddings(
        model_name=EMBED_MODEL, cache_dir=cache_dir) if cache_dir else \
        FastEmbedEmbeddings(model_name=EMBED_MODEL)
    return FAISS.from_documents(docs, embeddings, normalize_L2=True)


def _get_store():
    global _store
    if _store is None:
        _store = _build_store()
    return _store


def _permitted(doc, allowed):
    tables = {t.strip().upper() for t in doc.metadata["tables"].split(",")}
    return tables <= allowed


def retrieve(question: str, role: str, top_examples: int = 2):
    catalog = _base.load_catalog()
    allowed = ROLE_TABLES.get(role, set())
    visible = {t: c for t, c in catalog.items() if t.upper() in allowed}
    store = _get_store()
    hits = store.similarity_search_with_score(question, k=64)
    hits = [(doc, dist) for doc, dist in hits if _permitted(doc, allowed)]

    table_hits = [(doc.metadata["tables"], dist) for doc, dist in hits
                  if doc.metadata["kind"] == "table"]
    tables = []
    if table_hits:
        best = min(dist for _, dist in table_hits)
        # A very strong best match (a near-exact topic hit) narrows the
        # set to its neighbourhood; otherwise the absolute cap applies.
        cap = best + TABLE_MARGIN if best <= 0.7 else max(TABLE_MAX_DIST, best + TABLE_MARGIN)
        tables = [name for name, dist in table_hits if dist <= cap]
    tables = list(dict.fromkeys(tables)) or list(visible)
    for child, parent in _base.RELATIONS:
        for a, b in ((child, parent), (parent, child)):
            if a in tables and b in visible and b not in tables:
                tables.append(b)

    glossary = [doc.metadata["hint"] for doc, dist in hits
                if doc.metadata["kind"] == "glossary" and dist <= GLOSSARY_MAX_DIST]
    # Glossary terms are a curated list: exact substring/token hits from
    # the token-overlap retriever are unioned in (they are precise for
    # known terms like "piutang"/"belum lunas" that embeddings rank
    # just above the cut-off).
    for hint in _base._retrieve_overlap(question, role)["glossary"]:
        if hint not in glossary:
            glossary.append(hint)
    examples = [{"question": doc.page_content, "sql": doc.metadata["sql"]}
                for doc, dist in hits
                if doc.metadata["kind"] == "example" and dist <= EXAMPLE_MAX_DIST]
    examples = examples[:top_examples]

    return {"tables": tables, "glossary": glossary, "examples": examples,
            "catalog": {t: visible[t] for t in tables},
            "backend": "langchain"}
