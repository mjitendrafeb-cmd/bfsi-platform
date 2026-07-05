"""Peer comparison across entities' latest financials.

    python -m pipeline.compare <entity_id> [<entity_id> ...]
    python -m pipeline.compare 1 2 3

For each (entity, basis) pair, picks the single most recent ANNUAL
period row (a bare "FY26"-style label, not a quarter) — balance-sheet
metrics (AUM, net worth, CAR% etc.) are point-in-time as of the annual
close, so the annual row is the authoritative, complete one; a
quarter-only row would be missing most of them. Never blends two
periods' figures into one column — if no annual row exists at all for
a given (entity, basis), falls back to that group's single most recent
row of any period rather than combining rows together. Period is
always labeled exactly as stored, never reformatted. Prints a console
table and writes a labeled .xlsx to db/comparisons/.
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "tracker.sqlite"
ENTITY_MASTER = ROOT / "data" / "entity_master.csv"
OUT_DIR = ROOT / "db" / "comparisons"

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


def _load_entity_names() -> dict[int, str]:
    names = {}
    with open(ENTITY_MASTER, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            names[int(row["id"])] = row["display_name"].strip()
    return names


_ANNUAL_PERIOD = re.compile(r"^FY(\d{2,4})$")  # bare fiscal year only, e.g. "FY26" — not "Q4FY26"


def _annual_year(period: str | None) -> int | None:
    m = _ANNUAL_PERIOD.match(period or "")
    return int(m.group(1)) if m else None


def _latest_rows_for_entity(conn: sqlite3.Connection, entity_id: int) -> list[sqlite3.Row]:
    """One row per (basis) for this entity — the most recent ANNUAL
    period if one exists for that basis, else that basis's single most
    recent row of any period. Never merges two periods together."""
    rows = conn.execute("""
        SELECT f.*, r.agency, r.title, r.published_on
        FROM financials f
        LEFT JOIN snapshots s ON s.id = f.source_snapshot_id
        LEFT JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        WHERE f.entity_id = ?
        ORDER BY f.id DESC
    """, (entity_id,)).fetchall()
    if not rows:
        return []

    by_basis: dict[str | None, list[sqlite3.Row]] = {}
    for r in rows:
        by_basis.setdefault(r["basis"], []).append(r)

    # A basis=NULL group is untagged legacy data from before basis was
    # tracked — superseded once this entity has at least one properly
    # basis-tagged group, so don't surface it as its own column.
    if None in by_basis and any(b is not None for b in by_basis):
        del by_basis[None]

    selected: list[sqlite3.Row] = []
    for basis, group in by_basis.items():
        annual = [r for r in group if _annual_year(r["period"]) is not None]
        if annual:
            annual.sort(key=lambda r: _annual_year(r["period"]), reverse=True)
            selected.append(annual[0])
        else:
            selected.append(group[0])  # group is already id-DESC ordered

    basis_order = {"standalone": 0, "consolidated": 1, "CRA rationale": 2}
    selected.sort(key=lambda r: basis_order.get(r["basis"], 3))
    return selected


def build_columns(entity_ids: list[int]) -> list[dict]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    names = _load_entity_names()

    columns = []
    for eid in entity_ids:
        entity_name = names.get(eid, f"entity_id={eid}")
        rows = _latest_rows_for_entity(conn, eid)
        if not rows:
            print(f"  (no financials data for {entity_name} — skipped)")
            continue
        for r in rows:
            columns.append({
                "entity": entity_name,
                "basis": r["basis"] or "-",
                "period": r["period"] or "-",
                "source": f"{r['agency']} - {r['title']}" if r["agency"] else "-",
                "published_on": r["published_on"] or "-",
                "verified": "Verified" if r["verified"] else "Unverified",
                **{m: r[m] for m, _ in METRIC_LABELS},
            })
    return columns


def print_table(columns: list[dict]) -> None:
    if not columns:
        print("No data to compare.")
        return

    label_w = max(len(lbl) for _, lbl in METRIC_LABELS + [("", "Entity"), ("", "Basis"),
                                                            ("", "Period"), ("", "Source"),
                                                            ("", "Published"), ("", "Status")])
    col_w = max(18, max(len(c["entity"]) + len(c["basis"]) + 3 for c in columns))

    def row(label: str, values: list[str]) -> str:
        cells = "  ".join(v.ljust(col_w)[:col_w] for v in values)
        return f"{label.ljust(label_w)}  {cells}"

    print(row("Entity", [c["entity"] for c in columns]))
    print(row("Basis", [c["basis"] for c in columns]))
    print(row("Period", [c["period"] for c in columns]))
    print(row("Status", [c["verified"] for c in columns]))
    print(row("Source", [c["source"][:col_w] for c in columns]))
    print(row("Published", [c["published_on"] for c in columns]))
    print("-" * (label_w + 2 + len(columns) * (col_w + 2)))
    for m, lbl in METRIC_LABELS:
        values = [("" if c[m] is None else str(c[m])) for c in columns]
        print(row(lbl, values))


def write_excel(columns: list[dict], entity_ids: list[int]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Comparison"

    header_labels = ["Metric"] + [f"{c['entity']} ({c['basis']})" for c in columns]
    ws.append(header_labels)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    meta_rows = [
        ("Period", "period"), ("Status", "verified"),
        ("Source", "source"), ("Published", "published_on"),
    ]
    for label, key in meta_rows:
        ws.append([label] + [c[key] for c in columns])

    ws.append([])
    for m, lbl in METRIC_LABELS:
        ws.append([lbl] + [c[m] for c in columns])

    ws.column_dimensions["A"].width = 26
    for i in range(len(columns)):
        ws.column_dimensions[chr(ord("B") + i)].width = 24

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"compare_{'-'.join(str(e) for e in entity_ids)}_{stamp}.xlsx"
    wb.save(out_path)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("entity_ids", type=int, nargs="+")
    args = ap.parse_args()

    columns = build_columns(args.entity_ids)
    print()
    print_table(columns)
    if columns:
        out_path = write_excel(columns, args.entity_ids)
        print(f"\nExported: {out_path}")


if __name__ == "__main__":
    main()
