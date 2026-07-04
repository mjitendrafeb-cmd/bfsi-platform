"""Verification queue for the financials table.

    python -m pipeline.verify              # list all unverified rows
    python -m pipeline.verify --id 5 8      # mark specific row(s) verified
    python -m pipeline.verify --all         # mark every unverified row verified

Verification is permanent (an UPDATE ... SET verified=1, committed to
db/tracker.sqlite) — there's no in-memory/session-only state here.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB = Path("db/tracker.sqlite")
ENTITY_MASTER = Path("data/entity_master.csv")


def _load_entity_names() -> dict[int, str]:
    names = {}
    with open(ENTITY_MASTER, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            names[int(row["id"])] = row["display_name"].strip()
    return names


def _fetch_rows(conn: sqlite3.Connection, only_unverified: bool = True):
    where = "WHERE f.verified = 0" if only_unverified else ""
    return conn.execute(f"""
        SELECT f.id, f.entity_id, f.period, f.basis, f.verified,
               r.agency, r.title, r.pdf_path, r.published_on
        FROM financials f
        LEFT JOIN snapshots s ON s.id = f.source_snapshot_id
        LEFT JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        {where}
        ORDER BY f.entity_id, f.id
    """).fetchall()


def list_unverified() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    names = _load_entity_names()
    rows = _fetch_rows(conn)

    if not rows:
        print("Nothing unverified — all financial rows are marked verified.")
        return

    print(f"{len(rows)} unverified financial row(s):\n")
    for r in rows:
        entity = names.get(r["entity_id"], f"entity_id={r['entity_id']}")
        source = f"{r['agency']} — {r['title']}" if r["agency"] else "(source document not found)"
        print(f"  id={r['id']:<4} {entity:<20} period={r['period'] or '?':<18} "
              f"basis={r['basis'] or '?':<14} published={r['published_on'] or '?'}")
        print(f"          source: {source}")
        if r["pdf_path"]:
            print(f"          file:   {r['pdf_path']}")
        print()
    print(f"To verify: python -m pipeline.verify --id {' '.join(str(r['id']) for r in rows[:3])} ...")
    print("Or all at once: python -m pipeline.verify --all")


def mark_verified(ids: list[int]) -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    placeholders = ", ".join("?" * len(ids))
    existing = {row["id"] for row in conn.execute(
        f"SELECT id FROM financials WHERE id IN ({placeholders})", ids)}
    missing = set(ids) - existing
    if missing:
        print(f"No such financials row id(s): {sorted(missing)} — skipping those")
    valid_ids = [i for i in ids if i in existing]
    if not valid_ids:
        print("Nothing to verify.")
        return
    placeholders = ", ".join("?" * len(valid_ids))
    conn.execute(f"UPDATE financials SET verified = 1 WHERE id IN ({placeholders})", valid_ids)
    conn.commit()
    print(f"Marked verified: {valid_ids}")


def mark_all_verified() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = _fetch_rows(conn)
    if not rows:
        print("Nothing unverified — all financial rows are marked verified.")
        return
    ids = [r["id"] for r in rows]
    placeholders = ", ".join("?" * len(ids))
    conn.execute(f"UPDATE financials SET verified = 1 WHERE id IN ({placeholders})", ids)
    conn.commit()
    print(f"Marked verified: {ids} ({len(ids)} row(s))")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--id", type=int, nargs="+", metavar="ID",
                     help="mark specific financials.id row(s) verified")
    ap.add_argument("--all", action="store_true",
                     help="mark every currently-unverified row verified")
    args = ap.parse_args()

    if args.all:
        mark_all_verified()
    elif args.id:
        mark_verified(args.id)
    else:
        list_unverified()


if __name__ == "__main__":
    main()
