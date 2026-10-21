import sqlite3, os
DB_PATH = os.environ.get("ERP_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "erp.db"))

DDL = """
CREATE TABLE IF NOT EXISTS Units (UnitID INTEGER PRIMARY KEY, UnitNumber TEXT, Tower TEXT, Status TEXT);
CREATE TABLE IF NOT EXISTS Sales_Contracts (ContractID INTEGER PRIMARY KEY, UnitID INTEGER REFERENCES Units(UnitID), CustomerName TEXT, SalesAmount REAL, ContractDate TEXT);
CREATE TABLE IF NOT EXISTS Invoices_Billing (InvoiceID INTEGER PRIMARY KEY, ContractID INTEGER REFERENCES Sales_Contracts(ContractID), PeriodMonth INTEGER, PeriodYear INTEGER, AmountBilled REAL, AmountPaid REAL, DueDate TEXT);
CREATE TABLE IF NOT EXISTS GL_Journals (JournalID INTEGER PRIMARY KEY, AccountCode TEXT, AccountName TEXT, Debit REAL, Credit REAL, TransactionDate TEXT);
"""

SEED = [
 ("INSERT INTO Units VALUES (1,'SM 1111','Summer Tower','Sold'),(2,'SM 1112','Summer Tower','Sold'),(3,'SM 1115','Summer Tower','Sold'),(4,'SM 1201','Summer Tower','Vacant'),(5,'SM 1202','Summer Tower','Sold'),(6,'SP 1112','Spring Tower','Sold'),(7,'SP 1113','Spring Tower','Sold'),(8,'SP 1114','Spring Tower','Sold'),(9,'SP 1201','Spring Tower','Vacant'),(10,'SP 1202','Spring Tower','Sold')",),
 ("INSERT INTO Sales_Contracts VALUES (101,1,'PT Sukses Bersama',1500000000,'2026-01-15'),(102,2,'Budi Santoso',1250000000,'2026-02-10'),(103,3,'Siti Rahmawati',1300000000,'2026-02-20'),(104,5,'CV Megah Karya',1800000000,'2026-03-05'),(105,6,'PT Sukses Bersama',1600000000,'2026-03-12'),(106,7,'Hendrik Wijaya',1400000000,'2026-04-01'),(107,8,'Budi Santoso',1450000000,'2026-04-18'),(108,10,'Siti Rahmawati',1550000000,'2026-05-02')",),
 ("INSERT INTO Invoices_Billing VALUES (501,101,10,2026,15000000,0,'2026-10-10'),(502,105,10,2026,16000000,16000000,'2026-10-10'),(503,102,9,2026,12500000,12500000,'2026-09-10'),(504,102,10,2026,12500000,0,'2026-10-10'),(505,107,10,2026,14500000,0,'2026-10-10'),(506,103,10,2026,13000000,13000000,'2026-10-10'),(507,108,10,2026,15500000,5000000,'2026-10-10'),(508,104,10,2026,18000000,0,'2026-10-10'),(509,106,10,2026,14000000,14000000,'2026-10-10')",),
 ("INSERT INTO GL_Journals VALUES (901,'1101-01','Kas & Bank',1500000000,0,'2026-01-15'),(902,'4101-01','Pendapatan Sales Unit',0,1500000000,'2026-01-15'),(903,'1101-01','Kas & Bank',1250000000,0,'2026-02-10'),(904,'4101-01','Pendapatan Sales Unit',0,1250000000,'2026-02-10'),(905,'1101-01','Kas & Bank',1300000000,0,'2026-02-20'),(906,'4101-01','Pendapatan Sales Unit',0,1300000000,'2026-02-20'),(907,'1101-01','Kas & Bank',1800000000,0,'2026-03-05'),(908,'4101-01','Pendapatan Sales Unit',0,1800000000,'2026-03-05'),(909,'1101-01','Kas & Bank',1600000000,0,'2026-03-12'),(910,'4101-01','Pendapatan Sales Unit',0,1600000000,'2026-03-12')",),
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM Units")
    if cur.fetchone()[0] == 0:
        for (sql,) in SEED:
            conn.execute(sql)
        conn.commit()
    conn.close()

def run_readonly(sql, params=()):
    # Second layer of read-only enforcement: SQLite URI mode=ro + query_only pragma
    init_db()
    conn = sqlite3.connect(f"file:{os.path.abspath(DB_PATH)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return cols, rows
    finally:
        conn.close()

def list_customers():
    _, rows = run_readonly("SELECT DISTINCT CustomerName FROM Sales_Contracts ORDER BY CustomerName")
    return [r["CustomerName"] for r in rows]
