"""Peer comparison across entities' latest financials.

    python -m pipeline.compare <entity_id> [<entity_id> ...]
    python -m pipeline.compare 1 2 3

For each entity, pulls every financials row sharing the same period as
that entity's most-recently-added row (so a standalone+consolidated
pair for the same reporting period both show up as separate columns,
never merged into one). Prints a console table and writes an .xlsx to
db/comparisons/.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB = Path("db/tracker.sqlite")
ENTITY_MASTER = Path("data/entity_master.csv")
OUT_DIR = Path("db/comparisons")

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


def _latest_rows_for_entity(conn: sqlite3.Connection, entity_id: int) -> list[sqlite3.Row]:
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
    latest_period = rows[0]["period"]
    same_period = [r for r in rows if r["period"] == latest_period]
    basis_order = {"standalone": 0, "consolidated": 1, "CRA rationale": 2}
    same_period.sort(key=lambda r: basis_order.get(r["basis"], 3))
    return same_period


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
