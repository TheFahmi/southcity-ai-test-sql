#!/usr/bin/env python3
"""Generate seed_sample.sql: 500 additional sample rows for the demo DB.

Design invariants (guarded by assertions at the end):
  * The graded answers must not move:
      - no new rows for customers 'Siti Rahmawati' or 'Budi Santoso'
        (Q1 arrears and Q2 contract totals stay exactly as in schema.sql);
      - no contracts/invoices for unit 'SM 1201' (Q3 stays an empty case);
      - no GL_Journals rows for account 'Kas & Bank' in January 2026
        (Q4 stays exactly JournalID 901);
      - no invoices attached to the original contracts 101-108.
  * 'PT Sukses Bersama' keeps the largest per-customer contract total
    (Rp 3.100.000.000): every generated customer holds exactly one
    contract of at most Rp 2.400.000.000.
  * Deterministic output (fixed RNG seed) so eval results reproduce.

Row budget: 170 Units + 130 Sales_Contracts + 140 Invoices_Billing
            + 60 GL_Journals = 500 rows. Units outnumber contracts so a
realistic share of the new units stays Vacant.
"""
import itertools
import random
from datetime import date, timedelta

random.seed(20261106)

FIRST = ["Andi", "Rina", "Dedi", "Maya", "Rudi", "Sari", "Agus", "Lestari",
         "Bambang", "Fitri", "Joko", "Ratna", "Eko", "Dewi", "Hendra",
         "Sri", "Yusuf", "Ani", "Bambang", "Rudi", "Dian", "Fajar", "Intan",
         "Rizky", "Putri", "Ahmad", "Nur", "Bayu", "Citra", "Dedi"]
LAST = ["Pratama", "Nugroho", "Saputra", "Wulandari", "Hidayat", "Nugraha",
        "Puspita", "Anggraini", "Firmansyah", "Maharani", "Setiawan",
        "Kusuma", "Perdana", "Utama", "Salim", "Halim", "Gunawan",
        "Hartono", "Salim", "Lie", "Tanuwijaya", "Wibowo"]
COMPANIES = ["PT Graha Properti", "CV Cipta Land", "PT Bumi Asri",
             "PT Cakra Buana", "CV Sinar Realty", "PT Arunika Land",
             "PT Wira Properti", "CV Damar Land", "PT Kirana Realty",
             "PT Lintas Properti", "CV Bima Land", "PT Samudra Realty"]

names = [f"{a} {b}" for a, b in itertools.product(FIRST, LAST)]
names = [n for n in dict.fromkeys(names)
         if n not in ("Siti Rahmawati", "Budi Santoso")]
random.shuffle(names)
customers = (names[:118] + COMPANIES)  # 130 unique customers
assert len(customers) == 130 and len(set(customers)) == 130

def daterange(start, days):
    return start + timedelta(days=random.randrange(days))

# --- Units: IDs 11..180, floors 13-22 of Summer/Spring towers -----------
units = []
unit_numbers = set()
uid = 11
for tower, prefix in (("Summer Tower", "SM"), ("Spring Tower", "SP")):
    for floor in range(13, 23):
        for room in range(1, 10):
            if uid > 180:
                break
            num = f"{prefix} {floor}{room:02d}"
            if num in unit_numbers:
                continue
            unit_numbers.add(num)
            r = random.random()
            status = "Sold" if r < 0.62 else ("Vacant" if r < 0.87 else "Occupied")
            units.append((uid, num, tower, status))
            uid += 1
assert len(units) == 170 and "SM 1201" not in unit_numbers

# --- Contracts: IDs 109..238, one per sold/occupied unit ----------------
sold_units = [u for u in units if u[3] in ("Sold", "Occupied")]
need = 130 - len(sold_units)
# If statuses left fewer sold units than contracts needed, flip some
# Vacant units to Sold so every contract has its own unit.
if need > 0:
    vacant = [u for u in units if u[3] == "Vacant"]
    for u in vacant[:need]:
        units[units.index(u)] = (u[0], u[1], u[2], "Sold")
    sold_units = [u for u in units if u[3] in ("Sold", "Occupied")]
contracts = []
for i, u in enumerate(sold_units[:130]):
    cid = 109 + i
    amount = random.randrange(900, 2401) * 1_000_000
    cdate = daterange(date(2024, 6, 1), 880)
    contracts.append((cid, u[0], customers[i], amount, cdate.isoformat()))
assert len(contracts) == 130

# --- Invoices: IDs 510..649 over the new contracts only ------------------
invoices = []
iid = 510
ci = 0
while len(invoices) < 140:
    cid = contracts[ci % len(contracts)][0]
    year = random.choice([2025, 2025, 2026])
    month = random.randrange(1, 13) if year == 2025 else random.randrange(1, 12)
    billed = random.randrange(11, 20) * 1_000_000
    r = random.random()
    paid = billed if r < 0.55 else (0 if r < 0.8 else billed // 2)
    due = date(year, month, 10).isoformat()
    invoices.append((iid, cid, month, year, billed, paid, due))
    iid += 1
    ci += 1
assert len(invoices) == 140
assert all(iv[1] >= 109 for iv in invoices)

# --- GL journals: IDs 911..970 -------------------------------------------
ACCOUNTS = [("1101-01", "Kas & Bank"), ("4101-01", "Pendapatan Sales Unit"),
            ("1102-01", "Piutang Usaha"), ("2101-01", "Utang Usaha"),
            ("5101-01", "Beban Operasional"), ("1103-01", "Kas Kecil")]
journals = []
for i in range(60):
    jid = 911 + i
    code, name = random.choice(ACCOUNTS)
    while True:
        tdate = daterange(date(2025, 1, 1), 670)
        if not (name == "Kas & Bank" and tdate.year == 2026 and tdate.month == 1):
            break
    amount = random.randrange(50, 2401) * 1_000_000
    debit, credit = (amount, 0) if random.random() < 0.5 else (0, amount)
    journals.append((jid, code, name, debit, credit, tdate.isoformat()))
assert len(journals) == 60
assert not any(j[2] == "Kas & Bank" and j[5].startswith("2026-01") for j in journals)

# --- Emit SQL -------------------------------------------------------------
def emit(fh, table, rows, chunk=50):
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        fh.write(f"INSERT INTO {table} VALUES\n")
        fh.write(",\n".join(
            "    (" + ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in row) + ")"
            for row in part) + ";\n\n")

out = "seed_sample.sql"
with open(out, "w", encoding="utf-8") as fh:
    fh.write("-- SAMPLE DATA (generated by scripts/generate_sample_data.py)\n")
    fh.write("-- 500 extra rows for demo scale. Graded Q1-Q5 answers are\n")
    fh.write("-- unchanged by design: no rows for Siti Rahmawati / Budi Santoso,\n")
    fh.write("-- nothing for unit SM 1201, no 'Kas & Bank' journals in Jan 2026,\n")
    fh.write("-- no invoices on the original contracts 101-108.\n\n")
    emit(fh, "Units", units)
    emit(fh, "Sales_Contracts", contracts)
    emit(fh, "Invoices_Billing", invoices)
    emit(fh, "GL_Journals", journals)

total = len(units) + len(contracts) + len(invoices) + len(journals)
print(f"wrote {out}: Units {len(units)} + Contracts {len(contracts)} "
      f"+ Invoices {len(invoices)} + GL {len(journals)} = {total} rows")
