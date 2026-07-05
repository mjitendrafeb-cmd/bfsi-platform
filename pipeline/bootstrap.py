"""Stage D — knowledge bootstrap.

    python -m pipeline.bootstrap <entity_id> [--years 3]

Pulls an entity's historical rating rationales going back N years, from
every CRA that actually supports date-range or paginated access:
  - CareEdge's /rrcompany takes any date range, with a server-side
    companyName filter (confirmed live) — so this pulls the entity's
    full history directly, not every company's PRs for 3 years.
  - Acuité paginates its general listing, but no company-specific
    search was found on their site — so this is bounded to
    ACUITE_BOOTSTRAP_MAX_PAGES, not the full N years. Reaching a full
    3 years would mean several hundred page requests to page through
    every company's ratings just to find this one's.

Every other CRA scraper in this project (CRISIL, ICRA, India Ratings,
Infomerics, Brickwork) is documented in its own module docstring as
limited to a single recent page/snapshot regardless of the `since`
parameter passed — not attempted here, since re-fetching the same
few days of all companies' filings wouldn't reach further back.

Ingests everything through the normal extraction/delta pipeline
oldest-first (process_pending already orders by published_on
ascending), so the delta engine builds the rating history
chronologically instead of backwards. Finishes with a timeline summary
of every rating_rationale found for this entity — the securitisation
deals a company originates (sf_rationale) are ingested too, just not
included in this particular timeline, which is about the entity's own
corporate credit rating trajectory.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from common.entity_match import EntityMatcher
from common.storage import Storage
from scrapers.careedge import CareEdgeScraper
from scrapers.acuite import AcuiteScraper
from pipeline.process import process_pending, recompute_chronological_deltas

load_dotenv()

DB = Path("db/tracker.sqlite")
ENTITY_MASTER = Path("data/entity_master.csv")
ACUITE_BOOTSTRAP_MAX_PAGES = 80  # bounded — see module docstring


def _load_entity(entity_id: int) -> dict:
    with open(ENTITY_MASTER, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if int(row["id"]) == entity_id:
                return row
    raise SystemExit(f"No entity_id={entity_id} in {ENTITY_MASTER}")


def _matches_entity(company_name_raw: str, entity_id: int, entity: dict,
                     matcher: EntityMatcher, lenient: bool) -> bool:
    m = matcher.match(company_name_raw)
    if m and m.entity_id == entity_id:
        return True
    if not lenient:
        return False
    # CareEdge's companyName search already filtered server-side, but
    # variants like "X-Securitisation" (originator=X) don't survive the
    # matcher's normal fuzzy threshold — a looser check is safe here
    # specifically because the search term already scoped the results.
    key_tokens = [t for t in entity["legal_name"].lower().split() if len(t) > 3][:2]
    raw_lower = company_name_raw.lower()
    return bool(key_tokens) and all(tok in raw_lower for tok in key_tokens)


def _ingest(storage: Storage, scraper, entity_id: int, entity: dict,
            matcher: EntityMatcher, items, lenient: bool) -> set[str]:
    new_hashes: set[str] = set()
    for item in items:
        if not _matches_entity(item.company_name_raw, entity_id, entity, matcher, lenient):
            continue
        if storage.seen(item.dedupe_hash):
            continue

        pdf_path = scraper._download_pdf(item)
        storage.insert_item(
            dedupe_hash=item.dedupe_hash,
            agency=scraper.agency,
            company_name_raw=item.company_name_raw,
            entity_id=entity_id,
            match_confidence=1.0,
            title=item.title,
            doc_type=item.doc_type,
            pdf_url=item.pdf_url,
            pdf_path=str(pdf_path) if pdf_path else None,
            published_on=item.published_on.isoformat(),
        )
        new_hashes.add(item.dedupe_hash)
    return new_hashes


def _rating_summary(instruments: list[dict]) -> str:
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


def print_timeline(entity_id: int, entity_name: str) -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    # Chronological (published_on), not insertion id — a historical
    # backfill inserts older documents after newer ones already exist,
    # so id order and date order can disagree (see pipeline/process.py's
    # prev-lookup fix for the bug this caused).
    rows = conn.execute("""
        SELECT s.agency, s.snapshot_json, s.created_at, r.published_on
        FROM snapshots s
        JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        WHERE s.entity_id = ? AND s.doc_type = 'rating_rationale'
        ORDER BY r.published_on ASC, s.id ASC
    """, (entity_id,)).fetchall()

    print(f"\n=== Rating timeline: {entity_name} ({len(rows)} rationale(s)) ===\n")
    for r in rows:
        snap = json.loads(r["snapshot_json"])
        rating_date = snap.get("rating_date") or r["published_on"] or r["created_at"][:10]
        print(f"  {rating_date}  [{r['agency']:>10}]  {_rating_summary(snap.get('instruments'))}")


def bootstrap(entity_id: int, years: int) -> None:
    entity = _load_entity(entity_id)
    since = date.today() - timedelta(days=365 * years)
    print(f"Bootstrapping {entity['display_name']} (entity_id={entity_id}) "
          f"back to {since.isoformat()} ({years} years)\n")

    storage = Storage(DB)
    matcher = EntityMatcher(ENTITY_MASTER)
    all_new_hashes: set[str] = set()

    print(f"[CareEdge] fetching with companyName='{entity['legal_name']}' filter...")
    careedge = CareEdgeScraper(storage, matcher, download_pdfs=False)
    careedge_items = careedge.fetch_new_items(since, company_name=entity["legal_name"])
    print(f"  {len(careedge_items)} item(s) returned from the server-side filtered search")
    new = _ingest(storage, careedge, entity_id, entity, matcher, careedge_items, lenient=True)
    print(f"  {len(new)} new item(s) registered")
    all_new_hashes |= new

    print(f"\n[Acuité] paginating up to {ACUITE_BOOTSTRAP_MAX_PAGES} pages "
          f"(bounded — no company-specific search available)...")
    acuite = AcuiteScraper(storage, matcher, download_pdfs=False)
    acuite_items = acuite.fetch_new_items(since, max_pages=ACUITE_BOOTSTRAP_MAX_PAGES)
    print(f"  {len(acuite_items)} item(s) seen across all companies in the paginated window")
    new = _ingest(storage, acuite, entity_id, entity, matcher, acuite_items, lenient=False)
    print(f"  {len(new)} new item(s) matched to {entity['display_name']} and registered")
    all_new_hashes |= new

    print(f"\n{len(all_new_hashes)} new document(s) total. Running extraction/delta "
          f"pipeline oldest-first...\n")
    if all_new_hashes:
        process_pending(limit=len(all_new_hashes) + 10, only_hashes=all_new_hashes)

    # Backfilling can insert documents dated earlier than one already in
    # the table (e.g. this entity already had a recent rationale before
    # today) — process_pending() never revisits that pre-existing
    # entry's delta, so it's left comparing against nothing instead of
    # the newly-available earlier history. Rebuild the whole chain
    # chronologically to guarantee correctness regardless.
    for agency in ("careedge", "acuite"):
        for doc_type in ("rating_rationale", "sf_rationale"):
            n = recompute_chronological_deltas(entity_id, doc_type, agency)
            if n:
                print(f"Recomputed {n} {agency}/{doc_type} delta(s) in chronological order.")

    print_timeline(entity_id, entity["display_name"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("entity_id", type=int)
    ap.add_argument("--years", type=int, default=3)
    args = ap.parse_args()
    bootstrap(args.entity_id, args.years)


if __name__ == "__main__":
    main()
