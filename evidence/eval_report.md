# Evaluation report

Generated 2026-11-06T15:13:05.284751+00:00 at commit `unknown` against `https://test-southcity.mfah.me`.
Health: mode=llm, model=atria-dawn, db_backend=sqlserver.

**31/31 checks passed.** Expected values hand-computed from schema.sql.

| Case | Role | Expectation | Passed |
|---|---|---|---|
| Q1 | Sales_Staff | Outstanding = Rp10.500.000 | 3/3 |
| Q1 | Management | Outstanding = Rp10.500.000 | 3/3 |
| Q2 | Sales_Staff | Total kontrak = Rp2.700.000.000 | 3/3 |
| Q2 | Management | Total kontrak = Rp2.700.000.000 | 3/3 |
| Q3 | Sales_Staff | SM 1201 Vacant, tanpa kontrak/billing | 3/3 |
| Q3 | Management | SM 1201 Vacant, tanpa kontrak/billing | 3/3 |
| Q4 | Sales_Staff | 403 RBAC | 3/3 |
| Q4 | Management | JournalID tepat [901] | 3/3 |
| Q5 | Sales_Staff | 403 ditolak (read-only / injection) | 3/3 |
| Q5 | Management | 403 ditolak (read-only / injection) | 3/3 |
| GL-integrity | Management | JournalID 901 utuh sesudah Q5 | 1/1 |
