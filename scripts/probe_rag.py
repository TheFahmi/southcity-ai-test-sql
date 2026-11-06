#!/usr/bin/env python3
"""Probe both RAG backends on the graded questions + free-form probes.

Usage: python3 scripts/probe_rag.py
Prints, per question and role, the tables/glossary/example counts each
backend selects, so threshold changes are checked against behaviour.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("TEXT2SQL_MODE", "deterministic")

from app import rag, rag_langchain  # noqa: E402

CASES = [
    ("Berapa sisa tunggakan billing Siti Rahmawati untuk periode bulan 10 tahun 2026?", "Management"),
    ("Berapa hutang Siti Rahmawati di bulan Oktober 2026?", "Management"),
    ("Piutang belum lunas atas nama Siti Rahmawati periode 10/2026?", "Sales_Staff"),
    ("Berapa total nilai kontrak sales atas nama Budi Santoso di SouthCity?", "Management"),
    ("Tampilkan riwayat transaksi sales dan tagihan billing untuk unit SM 1201.", "Sales_Staff"),
    ("Tampilkan daftar catatan transaksi jurnal akun Kas & Bank pada tabel GL_Journals di bulan Januari 2026.", "Management"),
    ("Tampilkan daftar catatan transaksi jurnal akun Kas & Bank pada tabel GL_Journals di bulan Januari 2026.", "Sales_Staff"),
    ("Siapa customer dengan total kontrak terbesar?", "Management"),
    ("Berapa unit yang masih kosong?", "Sales_Staff"),
    ("Siapa presiden Indonesia?", "Management"),
]

for question, role in CASES:
    lc = rag_langchain.retrieve(question, role)
    ov = rag._retrieve_overlap(question, role)
    same = lc["tables"] == ov["tables"]
    print(f"[{role}] {question[:60]}...")
    print(f"  langchain: tables={lc['tables']} glossary={len(lc['glossary'])} examples={len(lc['examples'])}")
    print(f"  overlap  : tables={ov['tables']} glossary={len(ov['glossary'])} examples={len(ov['examples'])}  (tables sama: {same})")
