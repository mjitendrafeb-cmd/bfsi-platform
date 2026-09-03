"""Merge a newline-delimited BFSI watchlist into ``entity_master.csv``.

The importer is intentionally conservative. It removes only source-location
markers such as ``(BLR)``/``(CQR)`` for deduplication and preserves every
submitted spelling as an alias. Corporate suffixes are not used to merge
different names, which avoids accidentally combining similarly named siblings.

Run from the repository root::

    python scripts/import_entity_watchlist.py
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "data" / "entity_watchlist.txt"
DEFAULT_MASTER = ROOT / "data" / "entity_master.csv"

FIELDS = [
    "id", "legal_name", "display_name", "aliases", "cin", "sector",
    "sub_sector", "listed", "bse_code", "nse_symbol", "isins",
    "priority_tier",
]

_SPACE = re.compile(r"\s+")
_SOURCE_MARKER = re.compile(r"(?:\s*-?\s*\((?:BLR|CQR)\)|\s+-\s+BLR)$", re.I)
_FORMER_NAME = re.compile(
    r"\s*\((?:formerly known as|erstwhile)\s+(.+?)\)\s*$", re.I
)
_TRAILING_SUFFIX = re.compile(r"\s+(?:private\s+limited|limited|ltd)\.?$", re.I)


def clean_name(name: str) -> str:
    return _SPACE.sub(" ", name.strip())


def canonical_name(name: str) -> str:
    """Remove source labels/old-name notes, but retain the legal-name core."""
    value = clean_name(name)
    value = _SOURCE_MARKER.sub("", value).strip()
    value = _FORMER_NAME.sub("", value).strip()
    return value


def dedupe_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", canonical_name(name).lower()).strip()


def display_name(name: str) -> str:
    return _TRAILING_SUFFIX.sub("", canonical_name(name)).strip()


def aliases_from(name: str) -> set[str]:
    raw = clean_name(name)
    canonical = canonical_name(raw)
    aliases = {raw}
    if canonical != raw:
        aliases.add(canonical)
    former = _FORMER_NAME.search(raw)
    if former:
        aliases.add(clean_name(former.group(1)))
    return {alias for alias in aliases if alias}


def classify(name: str) -> tuple[str, str]:
    value = name.lower()
    if any(token in value for token in (
        "mutual fund", "asset management", "investment management",
        "funds management",
    )):
        return "Asset Management", "mutual_fund"
    if "insurance" in value or "reinsurance" in value:
        return "Insurance", "insurance"
    if "small finance bank" in value:
        return "Bank", "small_finance_bank"
    if re.search(r"\bbank\b", value) or "sberbank" in value:
        return "Bank", "bank"
    if any(token in value for token in (
        "housing finance", "home finance", "homefin", "home loan",
        "home first finance", "pnb housing", "india shelter finance",
        "truhome finance",
    )):
        return "HFC", "housing_finance"
    if "microfinance" in value or "microfin" in value or "micro finance" in value:
        return "NBFC", "MFI"
    if "clearing" in value:
        return "Market Infrastructure", "clearing_corporation"
    if any(token in value for token in (
        "securities", "broking", "brokers", "stock brokers", "capital markets",
        "equities", "wealth management", "investment advisors",
    )):
        return "Capital Markets", "securities_broking"
    if "asset reconstruction" in value or value.endswith(" arc"):
        return "ARC", "asset_reconstruction"
    if any(token in value for token in ("infrastructure finance", "financial corporation")):
        return "Financial Institution", "development_finance"
    return "NBFC", "other_finance"


def read_master(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def merge(source: Path, master: Path) -> tuple[int, int, int]:
    rows = read_master(master)
    by_key = {dedupe_key(row["legal_name"]): row for row in rows}
    next_id = max((int(row["id"]) for row in rows), default=0) + 1
    added = merged = ignored = 0

    for submitted in source.read_text(encoding="utf-8").splitlines():
        submitted = clean_name(submitted)
        if not submitted or submitted.startswith("#"):
            continue
        key = dedupe_key(submitted)
        if not key:
            ignored += 1
            continue
        candidate_aliases = aliases_from(submitted)
        if key in by_key:
            row = by_key[key]
            existing = {a.strip() for a in (row.get("aliases") or "").split(";") if a.strip()}
            canonical = {row["legal_name"], row["display_name"]}
            updated = sorted((existing | candidate_aliases) - canonical, key=str.casefold)
            row["aliases"] = ";".join(updated)
            if int(row["id"]) > 3:
                row["sector"], row["sub_sector"] = classify(row["legal_name"])
            merged += 1
            continue

        legal = canonical_name(submitted)
        sector, sub_sector = classify(legal)
        row = {field: "" for field in FIELDS}
        row.update({
            "id": str(next_id),
            "legal_name": legal,
            "display_name": display_name(legal),
            "aliases": ";".join(sorted(candidate_aliases - {legal}, key=str.casefold)),
            "sector": sector,
            "sub_sector": sub_sector,
            "priority_tier": "2",
        })
        rows.append(row)
        by_key[key] = row
        next_id += 1
        added += 1

    master.parent.mkdir(parents=True, exist_ok=True)
    with open(master, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in FIELDS} for row in rows)
    return added, merged, ignored


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    args = parser.parse_args()
    added, merged, ignored = merge(args.source, args.master)
    print(f"entity master updated: added={added}, merged={merged}, ignored={ignored}")


if __name__ == "__main__":
    main()
