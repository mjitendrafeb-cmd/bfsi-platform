"""Storage — SQLite for dev/local, interface-compatible with Supabase later.

The pipeline only calls: seen(), insert_item(), record_health().
When you move to Supabase, write a SupabaseStorage class with the same
three methods and change one line in run.py. Nothing else changes.
"""
from __future__ import annotations

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
"""


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)

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
