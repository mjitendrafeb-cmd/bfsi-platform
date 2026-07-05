"""Processor — drains the raw_items queue (processed=0, entity matched).

    python -m pipeline.process            # process everything pending
    python -m pipeline.process --dry-run  # show what would be processed

For each item:  route schema → get text (PDF or title) → extract →
store snapshot → diff vs previous snapshot → grade → store delta →
mark processed. News items skip PDF extraction (title/summary only).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from common.entity_match import EntityMatcher
from pipeline import schemas
from pipeline.extract import (
    doc_to_text, extract, extraction_confidence,
    QUARTERLY_RESULTS_MAX_PAGES, QUARTERLY_RESULTS_MAX_CHARS,
)
from pipeline.delta import diff_snapshots, grade_delta, baseline_note

load_dotenv()

log = logging.getLogger(__name__)
DB = Path("db/tracker.sqlite")
ENTITY_MASTER = Path("data/entity_master.csv")

# Which extracted field names "the entity this document is about", per
# schema — most use entity_name, but sf_rationale describes a pool deal
# rather than a single company, so the closest equivalent is the
# originator that sold the pool.
ENTITY_FIELD_BY_DOC_TYPE = {
    "rating_rationale": "entity_name",
    "exchange_filing": "entity_name",
    "quarterly_results": "entity_name",
    "news": "entity_name",
    "sf_rationale": "originator",
}

# Only these doc types have a meaningful "previous version" to diff against
# (successive rating rationales / quarterly results / SF surveillance notes
# for the same entity). News and exchange filings are one-off events, not
# revisions of a prior document, so they're graded directly from their own
# extracted fields.
DIFFABLE_DOC_TYPES = {"rating_rationale", "quarterly_results", "sf_rationale"}

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
CREATE TABLE IF NOT EXISTS financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    period TEXT,
    basis TEXT,
    aum_cr REAL, disbursements_cr REAL, total_income_cr REAL, nii_cr REAL,
    ppop_cr REAL, provisions_cr REAL, pat_cr REAL, gnpa_pct REAL,
    nnpa_pct REAL, car_pct REAL, networth_cr REAL, borrowings_cr REAL,
    cost_of_funds_pct REAL, collection_efficiency_pct REAL,
    source_snapshot_id INTEGER REFERENCES snapshots(id),
    verified INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_financials_entity ON financials(entity_id, period);
"""

# Same 14 fields as QUARTERLY_RESULTS.fields["metrics"] in schemas.py —
# order here drives both the financials table's columns and the INSERT.
FINANCIAL_METRICS = [
    "aum_cr", "disbursements_cr", "total_income_cr", "nii_cr", "ppop_cr",
    "provisions_cr", "pat_cr", "gnpa_pct", "nnpa_pct", "car_pct",
    "networth_cr", "borrowings_cr", "cost_of_funds_pct",
    "collection_efficiency_pct",
]


def _load_entity_names(path: Path) -> dict[int, str]:
    names = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            names[int(row["id"])] = row["display_name"].strip()
    return names


def _entity_mismatch(matcher: EntityMatcher, entity_names: dict[int, str],
                      schema_key: str, snap: dict, it) -> dict | None:
    """None if the extraction's stated entity corresponds to the entity
    this item is tagged as (or if the schema doesn't state one at all —
    can't check what wasn't extracted). Otherwise a dict describing the
    mismatch, for both the warning message and the review flag.

    Runs for every item regardless of source — a scraper's listing-page
    fuzzy match can misfire same as a human mistyping an entity_id
    during manual ingestion; this is the same re-check either way.
    """
    field = ENTITY_FIELD_BY_DOC_TYPE.get(schema_key)
    doc_name = snap.get(field) if field else None
    if not doc_name or not str(doc_name).strip():
        return None
    match = matcher.match(doc_name)
    matched_id = match.entity_id if match else None
    if matched_id == it["entity_id"]:
        return None
    return {
        "doc_name": doc_name,
        "tagged_name": entity_names.get(it["entity_id"], f"entity_id={it['entity_id']}"),
        "matched_id": matched_id,
    }


def _migrate_financials_basis_column(conn) -> None:
    """The financials table existed before the basis (standalone/
    consolidated) column was added — CREATE TABLE IF NOT EXISTS won't
    retroactively add it to a database that already has the table."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(financials)")}
    if "basis" not in cols:
        conn.execute("ALTER TABLE financials ADD COLUMN basis TEXT")
        conn.commit()


def _store_financials(conn, entity_id: int, statements: list[dict],
                       snapshot_id: int) -> None:
    """One row per financial_statements entry — a filing with both
    standalone and consolidated figures produces two rows, never one
    merged/picked row."""
    cols = ", ".join(FINANCIAL_METRICS)
    placeholders = ", ".join("?" * len(FINANCIAL_METRICS))
    for stmt in statements:
        values = [stmt.get(m) for m in FINANCIAL_METRICS]
        conn.execute(
            f"INSERT INTO financials "
            f"(entity_id, period, basis, {cols}, source_snapshot_id, verified, created_at) "
            f"VALUES (?, ?, ?, {placeholders}, ?, 0, ?)",
            (entity_id, stmt.get("period"), stmt.get("basis"),
             *values, snapshot_id, _now()))


def process_pending(limit: int = 50, dry_run: bool = False,
                     only_hashes: set[str] | None = None) -> None:
    """Drain the raw_items queue (processed=0, entity matched). Shared by
    the `python -m pipeline.process` CLI and `pipeline.ingest`, so manual
    ingestion runs through the exact same extraction/delta logic as
    scraper-sourced items — one code path, not two.

    `only_hashes` restricts processing to specific dedupe_hashes (e.g. a
    targeted backfill), leaving any other pending items untouched rather
    than spending API calls on documents nobody asked to process yet.
    """
    matcher = EntityMatcher(ENTITY_MASTER)
    entity_names = _load_entity_names(ENTITY_MASTER)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    _migrate_financials_basis_column(conn)

    pending = conn.execute("""
        SELECT * FROM raw_items
        WHERE processed = 0 AND entity_id IS NOT NULL
        ORDER BY published_on LIMIT ?""", (limit,)).fetchall()
    if only_hashes is not None:
        pending = [it for it in pending if it["dedupe_hash"] in only_hashes]
    print(f"{len(pending)} items pending")

    for it in pending:
        schema_key = schemas.route(it["agency"], it["doc_type"], it["title"])
        schema = schemas.SCHEMAS[schema_key]
        if dry_run:
            print(f"  would process [{schema_key:>18}] {it['agency']:>8} | "
                  f"{it['published_on']} | {it['title'][:60]}")
            continue

        # ---- text source -------------------------------------------------
        if it["agency"] == "news" or not it["pdf_path"]:
            text = f"Headline: {it['title']}\nCompany: {it['company_name_raw']}"
        elif schema_key == "quarterly_results":
            # BSE/NSE results filings can bundle the actual financial
            # statements dozens of pages into a much larger document
            # (AGM notices, director-appointment annexures, etc.) — see
            # extract.QUARTERLY_RESULTS_MAX_PAGES's docstring for a real
            # case that motivated this.
            text = doc_to_text(it["pdf_path"], max_pages=QUARTERLY_RESULTS_MAX_PAGES)
            if len(text) < 200:
                _mark(conn, it, status=2)   # needs OCR/visual — review queue
                continue
        else:
            text = doc_to_text(it["pdf_path"])
            if len(text) < 200:
                _mark(conn, it, status=2)   # needs OCR/visual — review queue
                continue

        # ---- extract -----------------------------------------------------
        max_chars = QUARTERLY_RESULTS_MAX_CHARS if schema_key == "quarterly_results" else 60000
        try:
            snap = extract(text, schema, max_chars=max_chars)
        except Exception:
            log.exception("extract failed: %s", it["title"][:60])
            _mark(conn, it, status=3)
            continue

        # ---- entity-mismatch guard -----------------------------------------
        mismatch = _entity_mismatch(matcher, entity_names, schema_key, snap, it)
        if mismatch:
            if mismatch["matched_id"] is not None:
                hint = f" (that name actually matches entity_id={mismatch['matched_id']})"
            else:
                hint = " (that name doesn't match any tracked entity)"
            print(f"  ⚠ ENTITY MISMATCH [{it['agency']}] {it['title'][:60]!r}: "
                  f"document says '{mismatch['doc_name']}', "
                  f"you tagged '{mismatch['tagged_name']}'{hint}. "
                  f"Not filed — marked for review.")
            _mark(conn, it, status=4)
            continue

        conf = extraction_confidence(snap)
        cur = conn.execute(
            "INSERT INTO snapshots VALUES (NULL,?,?,?,?,?,?,?)",
            (it["dedupe_hash"], it["entity_id"], it["agency"], schema_key,
             json.dumps(snap, ensure_ascii=False), conf, _now()))
        snap_id = cur.lastrowid

        # ---- financials table --------------------------------------------
        if schema_key == "quarterly_results":
            _store_financials(conn, it["entity_id"],
                               snap.get("financial_statements") or [], snap_id)
        elif schema_key == "rating_rationale":
            # Unlisted entities (e.g. IKF Home Finance) have no BSE/NSE
            # results filings at all — their only financial-metrics
            # source is whatever the CRA cites in its own rationale.
            # basis='CRA rationale' distinguishes this from an actual
            # standalone/consolidated statement — it's whatever the
            # rating agency chose to disclose, not an audited statement.
            key_metrics = snap.get("key_metrics") or {}
            if key_metrics:
                stmt = {"basis": "CRA rationale",
                        "period": key_metrics.get("metrics_asof")}
                stmt.update({m: key_metrics.get(m) for m in FINANCIAL_METRICS})
                _store_financials(conn, it["entity_id"], [stmt], snap_id)

        # ---- diff vs previous (rating_rationale / quarterly_results only) --
        if schema_key in DIFFABLE_DOC_TYPES:
            # Chronological (published_on), NOT insertion order (id) — a
            # historical backfill inserts documents dated well before
            # whatever already exists in the table, and those get a
            # HIGHER id despite an EARLIER date. id-based "previous"
            # lookup would then diff a document against one that's
            # actually chronologically after it. Found via a real bug:
            # a March-2024 backfilled document got compared against an
            # already-present July-2026 one and produced a nonsensical
            # "massive rating upgrade" — the two were just reversed.
            prev = conn.execute("""
                SELECT s.id, s.snapshot_json FROM snapshots s
                JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
                WHERE s.entity_id=? AND s.doc_type=? AND s.agency=?
                  AND r.published_on < ?
                ORDER BY r.published_on DESC, s.id DESC LIMIT 1""",
                (it["entity_id"], schema_key, it["agency"], it["published_on"])).fetchone()

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    process_pending(limit=args.limit, dry_run=args.dry_run)


def _mark(conn, it, status: int) -> None:
    conn.execute("UPDATE raw_items SET processed=? WHERE dedupe_hash=?",
                 (status, it["dedupe_hash"]))
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
