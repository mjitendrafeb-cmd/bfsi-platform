"""Storage — SQLite for dev/local, interface-compatible with Supabase later.

The pipeline only calls: seen(), insert_item(), record_health().
When you move to Supabase, write a SupabaseStorage class with the same
three methods and change one line in run.py. Nothing else changes.
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_items (
    dedupe_hash      TEXT PRIMARY KEY,
    agency           TEXT NOT NULL,
    company_name_raw TEXT,
    entity_id        INTEGER,          -- NULL = not in your 300 (or unmatched)
    match_confidence REAL,
    title            TEXT,
    doc_type         TEXT,
    pdf_url          TEXT,
    pdf_path         TEXT,
    published_on     TEXT,
    ingested_at      TEXT,
    processed        INTEGER DEFAULT 0 -- delta engine picks up processed=0
);
CREATE INDEX IF NOT EXISTS idx_items_entity ON raw_items(entity_id, published_on);
CREATE TABLE IF NOT EXISTS scraper_health (
    agency TEXT, run_at TEXT, ok INTEGER, note TEXT
);

-- Canonical platform tables from the project brief. Existing pipeline tables
-- (raw_items/deltas/financials) remain for backward compatibility; these
-- tables provide stable names for app/reporting growth.
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY, legal_name TEXT, display_name TEXT, aliases TEXT,
    cin TEXT, sector TEXT, sub_sector TEXT, listed INTEGER, bse_code TEXT,
    nse_symbol TEXT, isins TEXT, priority_tier INTEGER
);
CREATE TABLE IF NOT EXISTS source_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT UNIQUE, source TEXT,
    entity_id INTEGER, title TEXT, doc_type TEXT, source_url TEXT, local_path TEXT,
    published_on TEXT, ingested_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source_item_id INTEGER, entity_id INTEGER,
    doc_type TEXT, local_path TEXT, source_link TEXT, text_hash TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_hash TEXT,
    entity_id INTEGER, agency TEXT, doc_type TEXT,
    snapshot_json TEXT, confidence REAL, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap ON snapshots(entity_id, doc_type, agency, id);
CREATE TABLE IF NOT EXISTS diffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER, snapshot_id INTEGER,
    prior_snapshot_id INTEGER, changes_json TEXT, materiality TEXT, note TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS rating_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER, agency TEXT, action_date TEXT,
    instrument TEXT, rating TEXT, outlook TEXT, action TEXT, source_snapshot_id INTEGER, source_link TEXT
);
CREATE TABLE IF NOT EXISTS financial_metrics (
    metric_key TEXT PRIMARY KEY, label TEXT, unit TEXT, display_order INTEGER
);
CREATE TABLE IF NOT EXISTS financial_cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER, metric_key TEXT, period TEXT,
    basis TEXT, value REAL, source TEXT, source_link TEXT, verified INTEGER DEFAULT 0,
    source_snapshot_id INTEGER, divergence_flag INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER, item_type TEXT, item_id TEXT,
    reason TEXT, payload_json TEXT, status TEXT DEFAULT 'open', created_at TEXT, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS news_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER, headline TEXT, summary TEXT,
    event_date TEXT, source TEXT, source_link TEXT, materiality TEXT, ai_flag INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ai_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, task TEXT, model TEXT,
    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0, created_at TEXT
);
"""

METRICS = [
    ("aum_cr", "AUM", "Rs crore", 10),
    ("disbursements_cr", "Disbursements", "Rs crore", 20),
    ("total_income_cr", "Total Income", "Rs crore", 30),
    ("nii_cr", "Net Interest Income", "Rs crore", 40),
    ("ppop_cr", "Pre-provision Operating Profit", "Rs crore", 50),
    ("provisions_cr", "Provisions", "Rs crore", 60),
    ("pat_cr", "Profit After Tax", "Rs crore", 70),
    ("gnpa_pct", "Gross NPA", "%", 80),
    ("nnpa_pct", "Net NPA", "%", 90),
    ("car_pct", "Capital Adequacy Ratio", "%", 100),
    ("networth_cr", "Net Worth", "Rs crore", 110),
    ("borrowings_cr", "Borrowings", "Rs crore", 120),
    ("cost_of_funds_pct", "Cost of Funds", "%", 130),
    ("collection_efficiency_pct", "Collection Efficiency", "%", 140),
]


def _boolish(value: str | None) -> int:
    return 1 if str(value or "").strip().lower() in {"1", "true", "yes", "y"} else 0


class Storage:
    def __init__(self, db_path: Path, entity_master_csv: Path | None = None):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.seed_financial_metrics()
        master = entity_master_csv or Path("data/entity_master.csv")
        if master.exists():
            self.seed_entities(master)

    def seed_entities(self, entity_master_csv: Path) -> int:
        """Mirror data/entity_master.csv into the canonical entities table."""
        with open(entity_master_csv, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            self.conn.execute(
                """INSERT INTO entities
                   (id, legal_name, display_name, aliases, cin, sector, sub_sector,
                    listed, bse_code, nse_symbol, isins, priority_tier)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     legal_name=excluded.legal_name,
                     display_name=excluded.display_name,
                     aliases=excluded.aliases,
                     cin=excluded.cin,
                     sector=excluded.sector,
                     sub_sector=excluded.sub_sector,
                     listed=excluded.listed,
                     bse_code=excluded.bse_code,
                     nse_symbol=excluded.nse_symbol,
                     isins=excluded.isins,
                     priority_tier=excluded.priority_tier""",
                (
                    int(row["id"]), row["legal_name"], row["display_name"],
                    row.get("aliases", ""), row.get("cin") or row.get("CIN", ""),
                    row.get("sector", ""), row.get("sub_sector", ""),
                    _boolish(row.get("listed")), row.get("bse_code", ""),
                    row.get("nse_symbol", ""), row.get("isins", ""),
                    int(row.get("priority_tier") or row.get("priority") or 0),
                ),
            )
        self.conn.commit()
        return len(rows)

    def seed_financial_metrics(self) -> None:
        self.conn.executemany(
            "INSERT OR IGNORE INTO financial_metrics VALUES (?,?,?,?)",
            METRICS,
        )
        self.conn.commit()

    def seen(self, dedupe_hash: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM raw_items WHERE dedupe_hash=?", (dedupe_hash,))
        return cur.fetchone() is not None

    def insert_item(self, **kw) -> None:
        kw["ingested_at"] = datetime.now(timezone.utc).isoformat()
        cols = ",".join(kw)
        marks = ",".join("?" * len(kw))
        self.conn.execute(
            f"INSERT OR IGNORE INTO raw_items ({cols}) VALUES ({marks})",
            tuple(kw.values()))
        self.conn.commit()

    def record_health(self, agency: str, ok: bool, note: str = "") -> None:
        self.conn.execute(
            "INSERT INTO scraper_health VALUES (?,?,?,?)",
            (agency, datetime.now(timezone.utc).isoformat(), int(ok), note))
        self.conn.commit()

    # -- convenience for eyeballing results ---------------------------------
    def summary(self) -> list[tuple]:
        return self.conn.execute("""
            SELECT agency,
                   COUNT(*)                                   AS total,
                   SUM(CASE WHEN entity_id IS NOT NULL
                            THEN 1 ELSE 0 END)                AS matched,
                   MAX(published_on)                          AS latest
            FROM raw_items GROUP BY agency
        """).fetchall()
