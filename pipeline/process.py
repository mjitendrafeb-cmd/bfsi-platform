"""Processor — drains the raw_items queue (processed=0, entity matched).

    python -m pipeline.process            # process everything pending
    python -m pipeline.process --dry-run  # show what would be processed

For each item:  route schema → get text (PDF or title) → extract →
store snapshot → diff vs previous snapshot → grade → store delta →
mark processed. News items skip PDF extraction (title/summary only).
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from pipeline import schemas
from pipeline.extract import pdf_to_text, extract, extraction_confidence
from pipeline.delta import diff_snapshots, grade_delta, baseline_note

load_dotenv()

log = logging.getLogger(__name__)
DB = Path("db/tracker.sqlite")

# Only these doc types have a meaningful "previous version" to diff against
# (successive rating rationales / quarterly results for the same entity).
# News and exchange filings are one-off events, not revisions of a prior
# document, so they're graded directly from their own extracted fields.
DIFFABLE_DOC_TYPES = {"rating_rationale", "quarterly_results"}

DDL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_hash TEXT REFERENCES raw_items(dedupe_hash),
    entity_id INTEGER, agency TEXT, doc_type TEXT,
    snapshot_json TEXT, confidence REAL, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap ON snapshots(entity_id, doc_type, agency, id);
CREATE TABLE IF NOT EXISTS deltas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER, doc_type TEXT, agency TEXT,
    new_snapshot_id INTEGER, prev_snapshot_id INTEGER,
    changes_json TEXT, materiality TEXT, delta_note TEXT,
    watchlist_json TEXT, created_at TEXT
);
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)

    pending = conn.execute("""
        SELECT * FROM raw_items
        WHERE processed = 0 AND entity_id IS NOT NULL
        ORDER BY published_on LIMIT ?""", (args.limit,)).fetchall()
    print(f"{len(pending)} items pending")

    for it in pending:
        schema_key = schemas.route(it["agency"], it["doc_type"])
        schema = schemas.SCHEMAS[schema_key]
        if args.dry_run:
            print(f"  would process [{schema_key:>18}] {it['agency']:>8} | "
                  f"{it['published_on']} | {it['title'][:60]}")
            continue

        # ---- text source -------------------------------------------------
        if it["agency"] == "news" or not it["pdf_path"]:
            text = f"Headline: {it['title']}\nCompany: {it['company_name_raw']}"
        else:
            text = pdf_to_text(it["pdf_path"])
            if len(text) < 200:
                _mark(conn, it, status=2)   # needs OCR/visual — review queue
                continue

        # ---- extract -----------------------------------------------------
        try:
            snap = extract(text, schema)
        except Exception:
            log.exception("extract failed: %s", it["title"][:60])
            _mark(conn, it, status=3)
            continue
        conf = extraction_confidence(snap)
        cur = conn.execute(
            "INSERT INTO snapshots VALUES (NULL,?,?,?,?,?,?,?)",
            (it["dedupe_hash"], it["entity_id"], it["agency"], schema_key,
             json.dumps(snap, ensure_ascii=False), conf, _now()))
        snap_id = cur.lastrowid

        # ---- diff vs previous (rating_rationale / quarterly_results only) --
        if schema_key in DIFFABLE_DOC_TYPES:
            prev = conn.execute("""
                SELECT id, snapshot_json FROM snapshots
                WHERE entity_id=? AND doc_type=? AND agency=? AND id<?
                ORDER BY id DESC LIMIT 1""",
                (it["entity_id"], schema_key, it["agency"], snap_id)).fetchone()

            if prev is None:
                graded, changes, prev_id = baseline_note(snap), [], None
            else:
                changes = diff_snapshots(json.loads(prev["snapshot_json"]), snap)
                prev_id = prev["id"]
                graded = grade_delta(it["company_name_raw"], schema_key, changes) \
                    if changes else {"materiality": "low",
                                     "delta_note": "No substantive changes vs "
                                     "previous document.",
                                     "changes_graded": [],
                                     "suggested_watchlist_items": []}
        else:
            # news / exchange_filing: each item is its own event, not a
            # revision of a previous one — no diff, grade from the
            # extraction itself.
            changes, prev_id = [], None
            if snap.get("schema_mismatch"):
                note = snap.get("actual_content", "Content did not match "
                                                   "the expected document type.")
                materiality = "low"
            else:
                headline = snap.get("headline", "")
                body = snap.get("summary") or snap.get("detail") or ""
                note = f"{headline} {body}".strip()
                materiality = snap.get("credit_relevance", "low")
            graded = {
                "materiality": materiality,
                "delta_note": note,
                "changes_graded": [],
                "suggested_watchlist_items": [],
            }

        conn.execute(
            "INSERT INTO deltas VALUES (NULL,?,?,?,?,?,?,?,?,?,?)",
            (it["entity_id"], schema_key, it["agency"], snap_id, prev_id,
             json.dumps(changes, ensure_ascii=False), graded["materiality"],
             graded["delta_note"],
             json.dumps(graded.get("suggested_watchlist_items", [])), _now()))
        _mark(conn, it, status=1)
        print(f"  ✓ [{graded['materiality']:>6}] {it['company_name_raw']}: "
              f"{graded['delta_note'][:80]}")

    conn.commit()


def _mark(conn, it, status: int) -> None:
    conn.execute("UPDATE raw_items SET processed=? WHERE dedupe_hash=?",
                 (status, it["dedupe_hash"]))
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
