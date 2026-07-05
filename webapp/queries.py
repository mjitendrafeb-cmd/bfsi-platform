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

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "tracker.sqlite"
ENTITY_MASTER = ROOT / "data" / "entity_master.csv"
PDF_ROOT = (ROOT / "db" / "pdfs").resolve()

MATERIALITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def load_entities() -> list[dict]:
    with open(ENTITY_MASTER, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def entity_names() -> dict[int, str]:
    return {int(e["id"]): e["display_name"].strip() for e in load_entities()}


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


def mark_financials_verified(conn: sqlite3.Connection, ids: list[int]) -> int:
    if not ids:
        return 0
    placeholders = ", ".join("?" * len(ids))
    conn.execute(f"UPDATE financials SET verified=1 WHERE id IN ({placeholders})", ids)
    conn.commit()
    return len(ids)
