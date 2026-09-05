"""Read-only data access for the Stage E web app, plus the one write path
(marking a financials row verified) — every query here mirrors logic
already established by pipeline.compare / pipeline.verify / pipeline.bootstrap,
just reshaped into plain dicts for Jinja templates instead of console output.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from common.storage import SCHEMA as STORAGE_SCHEMA
from pipeline.process import DDL as PROCESS_DDL

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "tracker.sqlite"
ENTITY_MASTER = ROOT / "data" / "entity_master.csv"
PDF_ROOT = (ROOT / "db" / "pdfs").resolve()

MATERIALITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    # The app may be opened before a processor run has created every table.
    # Idempotent DDL keeps directory/review/demo screens usable on first run.
    conn.executescript(STORAGE_SCHEMA)
    conn.executescript(PROCESS_DDL)
    return conn


def load_entities() -> list[dict]:
    with open(ENTITY_MASTER, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def filter_entities(query: str = "", sector: str = "",
                    sub_sector: str = "") -> list[dict]:
    """Filter the entity master for the scalable directory screen."""
    query = query.strip().casefold()
    sector = sector.strip().casefold()
    sub_sector = sub_sector.strip().casefold()
    rows = load_entities()
    if query:
        rows = [
            row for row in rows
            if query in " ".join((
                row.get("legal_name", ""), row.get("display_name", ""),
                row.get("aliases", ""), row.get("bse_code", ""),
                row.get("nse_symbol", ""),
            )).casefold()
        ]
    if sector:
        rows = [row for row in rows if row.get("sector", "").casefold() == sector]
    if sub_sector:
        rows = [
            row for row in rows
            if row.get("sub_sector", "").casefold() == sub_sector
        ]
    return sorted(rows, key=lambda row: row.get("display_name", "").casefold())


def entity_names() -> dict[int, str]:
    return {int(e["id"]): e["display_name"].strip() for e in load_entities()}


def dashboard_stats(conn: sqlite3.Connection) -> dict:
    """Compact operating statistics for the surveillance dashboard."""
    entities = load_entities()

    def scalar(sql: str, default=0):
        try:
            row = conn.execute(sql).fetchone()
            return row[0] if row and row[0] is not None else default
        except sqlite3.OperationalError:
            return default

    return {
        "entities": len(entities),
        "priority_entities": sum(
            1 for entity in entities if entity.get("priority_tier") == "1"
        ),
        "documents": scalar("SELECT COUNT(*) FROM raw_items"),
        "high_changes": scalar(
            "SELECT COUNT(*) FROM deltas WHERE materiality='high'"
        ),
        "open_reviews": scalar(
            "SELECT COUNT(*) FROM review_queue WHERE status='open'"
        ),
        "latest_update": scalar(
            "SELECT MAX(published_on) FROM raw_items", "—"
        ),
    }


def source_url(pdf_path: str | None) -> str | None:
    """Map a raw_items.pdf_path (stored relative to the project root, e.g.
    'db\\pdfs\\careedge\\xxx.pdf') to a /source/... URL the browser can
    fetch, without exposing the rest of the project as static files."""
    if not pdf_path:
        return None
    try:
        abs_path = (ROOT / pdf_path).resolve()
        rel = abs_path.relative_to(PDF_ROOT)
    except ValueError:
        return None
    return "/source/" + str(rel).replace("\\", "/")


# ---------------------------------------------------------------------------
# Delta ribbons — "old → new" summaries derived from a delta's changes_json
# ---------------------------------------------------------------------------
def _instrument_key(d: dict) -> str:
    return d.get("instrument") or d.get("tranche") or ""


def _instrument_label(d: dict) -> str:
    s = d.get("rating") or "?"
    if d.get("outlook"):
        s += f"/{d['outlook']}"
    return s


def extract_ribbons(changes: list[dict], limit: int = 6) -> list[str]:
    """Turn a deterministic changes_json list into short 'X → Y' strings
    for the dashboard/timeline ribbons. Handles the two shapes changes
    come in: instrument/tranche list additions+removals (a rating change
    shows as a matched remove+add pair, since diff_snapshots set-compares
    lists of dicts), and plain scalar field changes (financial metrics,
    outlook, liquidity assessment, etc.)."""
    if not changes:
        return []
    ribbons: list[str] = []

    instr_changes = [c for c in changes if c["field"] in ("instruments", "instrument_tranches")]
    added = [c["new"] for c in instr_changes if c["kind"] == "added"]
    removed = [c["old"] for c in instr_changes if c["kind"] == "removed"]
    removed_by_key = {_instrument_key(d): d for d in removed}
    matched = set()

    for a in added:
        k = _instrument_key(a)
        old = removed_by_key.get(k)
        new_label = _instrument_label(a)
        if old:
            matched.add(k)
            old_label = _instrument_label(old)
            if old_label != new_label:
                ribbons.append(f"{k or 'Instrument'}: {old_label} → {new_label}")
        else:
            action = a.get("action") or "New"
            ribbons.append(f"{k or 'Instrument'}: {action} {new_label}")
    for k, old in removed_by_key.items():
        if k not in matched:
            ribbons.append(f"{k or 'Instrument'}: {_instrument_label(old)} → Withdrawn")

    for c in changes:
        if c["field"] in ("instruments", "instrument_tranches"):
            continue
        if c["kind"] in ("increased", "decreased", "modified"):
            old, new = c["old"], c["new"]
            if isinstance(old, (dict, list)) or isinstance(new, (dict, list)):
                continue
            label = c["field"].rsplit(".", 1)[-1]
            ribbons.append(f"{label}: {old} → {new}")

    return ribbons[:limit]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def recent_deltas(conn: sqlite3.Connection, limit: int = 60) -> list[dict]:
    rows = conn.execute("""
        SELECT d.entity_id, d.doc_type, d.agency, d.materiality, d.delta_note,
               d.changes_json, r.published_on, r.title, r.pdf_path
        FROM deltas d
        JOIN snapshots s ON s.id = d.new_snapshot_id
        JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        ORDER BY r.published_on DESC, d.id DESC
        LIMIT ?
    """, (limit,)).fetchall()
    names = entity_names()
    out = []
    for r in rows:
        changes = json.loads(r["changes_json"]) if r["changes_json"] else []
        out.append({
            "entity_id": r["entity_id"],
            "entity": names.get(r["entity_id"], f"entity_id={r['entity_id']}"),
            "date": r["published_on"],
            "agency": r["agency"],
            "doc_type": r["doc_type"],
            "materiality": r["materiality"],
            "note": r["delta_note"],
            "ribbons": extract_ribbons(changes),
            "title": r["title"],
            "pdf_url": source_url(r["pdf_path"]),
        })
    return out


# ---------------------------------------------------------------------------
# Entity page
# ---------------------------------------------------------------------------
def _rating_summary(instruments: list[dict] | None) -> str:
    seen, parts = [], []
    for i in instruments or []:
        key = (i.get("rating"), i.get("outlook"), i.get("action"))
        if key in seen:
            continue
        seen.append(key)
        rating, outlook, action = key
        s = rating or "?"
        if outlook:
            s += f"/{outlook}"
        if action:
            s += f" ({action})"
        parts.append(s)
    return "; ".join(parts) if parts else "(no instruments extracted)"


def current_ratings(conn: sqlite3.Connection, entity_id: int) -> list[dict]:
    """Latest rating_rationale/sf_rationale snapshot per agency — one row
    per rated instrument, i.e. the ratings actually in force today."""
    rows = conn.execute("""
        SELECT s.agency, s.doc_type, s.snapshot_json, r.published_on
        FROM snapshots s
        JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        WHERE s.entity_id=? AND s.doc_type IN ('rating_rationale','sf_rationale')
        ORDER BY r.published_on DESC, s.id DESC
    """, (entity_id,)).fetchall()
    latest_by_agency: dict[str, sqlite3.Row] = {}
    for r in rows:
        latest_by_agency.setdefault(r["agency"], r)

    out = []
    for agency, r in latest_by_agency.items():
        snap = json.loads(r["snapshot_json"])
        instruments = snap.get("instruments") or snap.get("instrument_tranches") or []
        as_of = snap.get("rating_date") or r["published_on"]
        for instr in instruments:
            out.append({
                "agency": agency,
                "instrument": instr.get("instrument") or instr.get("tranche") or "-",
                "amount_cr": instr.get("amount_cr"),
                "rating": instr.get("rating"),
                "outlook": instr.get("outlook"),
                "as_of": as_of,
            })
    out.sort(key=lambda x: (x["agency"], x["instrument"] or ""))
    return out


def rating_timeline(conn: sqlite3.Connection, entity_id: int) -> list[dict]:
    """Rating actions + credit updates, chronological, across every agency
    (bootstrap.print_timeline's console version is CareEdge/Acuité-only;
    this generalises it for any agency the entity is rated by)."""
    rows = conn.execute("""
        SELECT s.agency, s.doc_type, s.snapshot_json, r.published_on, r.pdf_path
        FROM snapshots s
        JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        WHERE s.entity_id=? AND s.doc_type IN ('rating_rationale','credit_update')
        ORDER BY r.published_on ASC, s.id ASC
    """, (entity_id,)).fetchall()
    out = []
    for r in rows:
        snap = json.loads(r["snapshot_json"])
        if r["doc_type"] == "credit_update":
            out.append({
                "date": snap.get("date") or r["published_on"],
                "agency": r["agency"],
                "kind": "credit_update",
                "label": snap.get("subject", ""),
                "pdf_url": source_url(r["pdf_path"]),
            })
        else:
            out.append({
                "date": snap.get("rating_date") or r["published_on"],
                "agency": r["agency"],
                "kind": "rating_rationale",
                "label": _rating_summary(snap.get("instruments")),
                "pdf_url": source_url(r["pdf_path"]),
            })
    out.reverse()  # newest first for display
    return out


METRIC_LABELS = [
    ("aum_cr", "AUM (Rs cr)"),
    ("disbursements_cr", "Disbursements (Rs cr)"),
    ("total_income_cr", "Total Income (Rs cr)"),
    ("nii_cr", "NII (Rs cr)"),
    ("ppop_cr", "PPOP (Rs cr)"),
    ("provisions_cr", "Provisions (Rs cr)"),
    ("pat_cr", "PAT (Rs cr)"),
    ("gnpa_pct", "GNPA %"),
    ("nnpa_pct", "NNPA %"),
    ("car_pct", "CAR %"),
    ("networth_cr", "Net Worth (Rs cr)"),
    ("borrowings_cr", "Borrowings (Rs cr)"),
    ("cost_of_funds_pct", "Cost of Funds %"),
    ("collection_efficiency_pct", "Collection Efficiency %"),
]


def verified_financials(conn: sqlite3.Connection, entity_id: int) -> list[dict]:
    rows = conn.execute("""
        SELECT f.*, r.agency, r.title, r.pdf_path, r.published_on
        FROM financials f
        LEFT JOIN snapshots s ON s.id = f.source_snapshot_id
        LEFT JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        WHERE f.entity_id=? AND f.verified=1
        ORDER BY f.period DESC, f.id DESC
    """, (entity_id,)).fetchall()
    out = []
    for r in rows:
        out.append({
            "period": r["period"] or "-",
            "basis": r["basis"] or "-",
            "metrics": [(lbl, r[m]) for m, lbl in METRIC_LABELS],
            "source": f"{r['agency']} — {r['title']}" if r["agency"] else "-",
            "pdf_url": source_url(r["pdf_path"]),
        })
    return out


def entity_deltas(conn: sqlite3.Connection, entity_id: int) -> list[dict]:
    rows = conn.execute("""
        SELECT d.doc_type, d.agency, d.materiality, d.delta_note, d.changes_json,
               r.published_on, r.title, r.pdf_path
        FROM deltas d
        JOIN snapshots s ON s.id = d.new_snapshot_id
        JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        WHERE d.entity_id=?
        ORDER BY r.published_on DESC, d.id DESC
    """, (entity_id,)).fetchall()
    out = []
    for r in rows:
        changes = json.loads(r["changes_json"]) if r["changes_json"] else []
        out.append({
            "date": r["published_on"],
            "agency": r["agency"],
            "doc_type": r["doc_type"],
            "materiality": r["materiality"],
            "note": r["delta_note"],
            "ribbons": extract_ribbons(changes),
            "title": r["title"],
            "pdf_url": source_url(r["pdf_path"]),
        })
    return out


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------
def unverified_financials(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT f.id, f.entity_id, f.period, f.basis, r.agency, r.title,
               r.pdf_path, r.published_on
        FROM financials f
        LEFT JOIN snapshots s ON s.id = f.source_snapshot_id
        LEFT JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        WHERE f.verified = 0
        ORDER BY f.entity_id, f.id
    """).fetchall()
    names = entity_names()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "entity": names.get(r["entity_id"], f"entity_id={r['entity_id']}"),
            "period": r["period"] or "-",
            "basis": r["basis"] or "-",
            "source": f"{r['agency']} — {r['title']}" if r["agency"] else "(source not found)",
            "published_on": r["published_on"] or "-",
            "pdf_url": source_url(r["pdf_path"]),
        })
    return out


def flagged_raw_items(conn: sqlite3.Connection, status: int) -> list[dict]:
    rows = conn.execute("""
        SELECT dedupe_hash, agency, company_name_raw, entity_id, title,
               doc_type, pdf_path, published_on
        FROM raw_items WHERE processed=? ORDER BY published_on DESC
    """, (status,)).fetchall()
    names = entity_names()
    out = []
    for r in rows:
        out.append({
            "hash": r["dedupe_hash"][:12],
            "agency": r["agency"],
            "company_name_raw": r["company_name_raw"],
            "tagged_entity": names.get(r["entity_id"], f"entity_id={r['entity_id']}") if r["entity_id"] else "-",
            "title": r["title"],
            "doc_type": r["doc_type"],
            "published_on": r["published_on"] or "-",
            "pdf_url": source_url(r["pdf_path"]),
        })
    return out


def review_queue_items(conn: sqlite3.Connection, reason: str | None = None) -> list[dict]:
    """Open canonical review_queue rows with parsed payloads for the UI."""
    params: list[str] = []
    where = "WHERE status='open'"
    if reason:
        where += " AND reason=?"
        params.append(reason)
    rows = conn.execute(f"""
        SELECT id, entity_id, item_type, item_id, reason, payload_json, created_at
        FROM review_queue
        {where}
        ORDER BY created_at DESC, id DESC
    """, params).fetchall()
    names = entity_names()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {"raw": r["payload_json"]}
        out.append({
            "id": r["id"],
            "entity": names.get(r["entity_id"], f"entity_id={r['entity_id']}") if r["entity_id"] else "-",
            "item_type": r["item_type"],
            "item_id": r["item_id"],
            "reason": r["reason"],
            "payload": payload,
            "created_at": r["created_at"],
        })
    return out


def resolve_review_item(conn: sqlite3.Connection, review_id: int) -> None:
    conn.execute(
        "UPDATE review_queue SET status='resolved', resolved_at=datetime('now') WHERE id=?",
        (review_id,),
    )
    conn.commit()


def entity_documents(conn: sqlite3.Connection, entity_id: int) -> list[dict]:
    """Source documents grouped by processed status for the entity Documents tab."""
    rows = conn.execute("""
        SELECT dedupe_hash, agency, title, doc_type, pdf_path, published_on, processed
        FROM raw_items
        WHERE entity_id=?
        ORDER BY published_on DESC, ingested_at DESC
    """, (entity_id,)).fetchall()
    status = {0: "Pending", 1: "Processed", 2: "Needs OCR", 3: "Extract failed", 4: "Entity mismatch"}
    return [{
        "hash": r["dedupe_hash"][:12],
        "agency": r["agency"],
        "title": r["title"],
        "doc_type": r["doc_type"] or "-",
        "published_on": r["published_on"] or "-",
        "status": status.get(r["processed"], f"Status {r['processed']}"),
        "pdf_url": source_url(r["pdf_path"]),
    } for r in rows]


def entity_review_items(conn: sqlite3.Connection, entity_id: int) -> list[dict]:
    return [r for r in review_queue_items(conn) if r["entity"] == entity_names().get(entity_id, f"entity_id={entity_id}")]


def entity_news_events(conn: sqlite3.Connection, entity_id: int) -> list[dict]:
    """News-like events for the entity News tab.

    Prefer canonical news_events when present; fall back to extracted news deltas
    so the UI works with the current pipeline tables.
    """
    if _table_exists(conn, "news_events"):
        rows = conn.execute("""
            SELECT headline, summary, event_date, source, source_link, materiality, ai_flag
            FROM news_events WHERE entity_id=? ORDER BY event_date DESC, id DESC
        """, (entity_id,)).fetchall()
        if rows:
            return [dict(r) for r in rows]
    rows = conn.execute("""
        SELECT d.delta_note AS summary, d.materiality, d.agency AS source,
               r.published_on AS event_date, r.title AS headline, r.pdf_url AS source_link
        FROM deltas d
        JOIN snapshots s ON s.id=d.new_snapshot_id
        JOIN raw_items r ON r.dedupe_hash=s.dedupe_hash
        WHERE d.entity_id=? AND d.doc_type='news'
        ORDER BY r.published_on DESC, d.id DESC
    """, (entity_id,)).fetchall()
    return [dict(r) | {"ai_flag": 1} for r in rows]


def peer_rating_matrix(conn: sqlite3.Connection, entity_ids: list[int]) -> list[dict]:
    """Latest rating rows for selected peers."""
    out = []
    names = entity_names()
    for eid in entity_ids:
        ratings = current_ratings(conn, eid)
        if not ratings:
            out.append({"entity_id": eid, "entity": names.get(eid, f"entity_id={eid}"),
                        "agency": "-", "instrument": "-", "rating": "—", "outlook": "—", "as_of": "—"})
            continue
        for r in ratings:
            out.append({"entity_id": eid, "entity": names.get(eid, f"entity_id={eid}"), **r})
    return out


def _rating_score(rating: str | None) -> int | None:
    if not rating:
        return None
    text = rating.upper().replace("[ICRA]", "").replace("CARE", "").replace("CRISIL", "").strip()
    order = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-"]
    for idx, token in enumerate(order, start=1):
        if token in text:
            return idx
    return None


def peer_risk_flags(conn: sqlite3.Connection, columns: list[dict]) -> list[dict]:
    """Simple deterministic flags for peer comparison demo/feedback."""
    flags = []
    for c in columns:
        issues = []
        positives = []
        if c.get("verified") != "Verified":
            issues.append("Unverified financials")
        if c.get("gnpa_pct") is not None and c["gnpa_pct"] >= 5:
            issues.append("GNPA ≥ 5%")
        elif c.get("gnpa_pct") is not None and c["gnpa_pct"] <= 2:
            positives.append("Low GNPA")
        if c.get("car_pct") is not None and c["car_pct"] < 18:
            issues.append("CAR < 18%")
        elif c.get("car_pct") is not None and c["car_pct"] >= 22:
            positives.append("Strong CAR")
        if c.get("pat_cr") is not None and c["pat_cr"] < 0:
            issues.append("Loss-making")
        material = conn.execute(
            "SELECT COUNT(*) FROM deltas WHERE entity_id=? AND materiality='high'",
            (c.get("entity_id"),),
        ).fetchone()[0] if _table_exists(conn, "deltas") and c.get("entity_id") is not None else 0
        if material:
            issues.append(f"{material} high-materiality change(s)")
        flags.append({"entity": c["entity"], "basis": c["basis"],
                      "status": "Watch" if issues else "OK",
                      "issues": issues, "positives": positives})
    return flags


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def mark_financials_verified(conn: sqlite3.Connection, ids: list[int]) -> int:
    if not ids:
        return 0
    placeholders = ", ".join("?" * len(ids))
    conn.execute(f"UPDATE financials SET verified=1 WHERE id IN ({placeholders})", ids)
    conn.commit()
    return len(ids)
