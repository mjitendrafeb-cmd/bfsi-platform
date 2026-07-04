"""Manual document ingestion — for documents the scrapers can't reach
(paywalled agencies, a PDF someone emailed you, a report grabbed by hand
from a site not yet supported).

    python -m pipeline.ingest <file-or-folder> <entity_id> <agency>

Registers the document(s) in raw_items (skipping ones already ingested)
and immediately runs them through the normal extraction/delta pipeline
(pipeline.process.process_pending — the exact same code path scraped
items go through, not a separate one). PDF vs HTML is detected
automatically by pipeline.extract.doc_to_text, same as everywhere else.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from common.storage import Storage
from pipeline.process import process_pending

load_dotenv()

# Relative to cwd, same convention as pipeline/process.py and the
# scrapers — this project always runs its scripts from the repo root.
ENTITY_MASTER = Path("data/entity_master.csv")
DB = Path("db/tracker.sqlite")
DOC_EXTENSIONS = {".pdf", ".html", ".htm"}


def _load_entities() -> dict[int, dict]:
    entities = {}
    with open(ENTITY_MASTER, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            entities[int(row["id"])] = row
    return entities


def _collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.iterdir()
            if p.is_file() and p.suffix.lower() in DOC_EXTENSIONS)
    raise SystemExit(f"Not a file or folder: {path}")


def _dedupe_hash(agency: str, file_bytes: bytes) -> str:
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    return hashlib.sha256(
        f"{agency}|manual|{content_hash}".encode()).hexdigest()[:32]


def ingest(path: Path, entity_id: int, agency: str) -> int:
    entities = _load_entities()
    if entity_id not in entities:
        available = ", ".join(
            f"{eid}={row['display_name']}" for eid, row in sorted(entities.items()))
        raise SystemExit(
            f"No entity_id={entity_id} in {ENTITY_MASTER}. Available: {available}")
    entity = entities[entity_id]

    files = _collect_files(path)
    if not files:
        print(f"No .pdf/.html/.htm files found at {path}")
        return 0

    storage = Storage(DB)
    dest_dir = Path("db/pdfs") / agency
    dest_dir.mkdir(parents=True, exist_ok=True)

    new_count = 0
    for f in files:
        file_bytes = f.read_bytes()
        dhash = _dedupe_hash(agency, file_bytes)
        if storage.seen(dhash):
            print(f"  skip (already ingested): {f.name}")
            continue

        dest = dest_dir / f"{f.stem}_{dhash[:8]}{f.suffix.lower()}"
        shutil.copy2(f, dest)

        storage.insert_item(
            dedupe_hash=dhash,
            agency=agency,
            company_name_raw=entity["legal_name"],
            entity_id=entity_id,
            match_confidence=1.0,
            title=f.stem.replace("_", " ").replace("-", " "),
            doc_type="manual",
            pdf_url=f"file://{f.resolve()}",
            pdf_path=str(dest),
            published_on=date.today().isoformat(),
        )
        new_count += 1
        print(f"  registered: {f.name} -> entity_id={entity_id} "
              f"({entity['display_name']}), agency={agency}")

    print(f"\n{new_count} new document(s) registered. "
          "Running extraction/delta pipeline...\n")
    process_pending(limit=1000)
    return new_count


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Manually ingest a document (or folder of documents) "
                     "into the pipeline, bypassing the scrapers.")
    ap.add_argument("path", type=Path, help="A file, or a folder of files")
    ap.add_argument("entity_id", type=int, help="id from data/entity_master.csv")
    ap.add_argument("agency", help="e.g. careedge, crisil, icra — or any label")
    args = ap.parse_args()
    ingest(args.path, args.entity_id, args.agency)


if __name__ == "__main__":
    main()
