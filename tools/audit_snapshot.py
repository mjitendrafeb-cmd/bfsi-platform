"""QC figure-trace: verify every number and name in an extracted snapshot
actually appears in its source document, with surrounding context shown
so a reviewer can eyeball each hit instead of trusting it blindly.

Long free-text fields (driver bullets, commentary) are intentionally
skipped — those schema fields are documented as paraphrased summaries,
not verbatim quotes, so checking them for exact substring presence would
just produce noisy false "MISS" results. This checks the atomic facts:
numbers and short name/label/identifier strings.

    python tools/audit_snapshot.py <snapshot_id>
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.extract import doc_to_text  # noqa: E402

DB = ROOT / "db" / "tracker.sqlite"
CONTEXT_CHARS = 50
MAX_NAME_WORDS = 12  # longer strings are treated as narrative, not a fact to trace
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_snapshot(snapshot_id: int) -> sqlite3.Row:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT s.snapshot_json, s.dedupe_hash, s.doc_type, "
        "r.pdf_path, r.title, r.company_name_raw "
        "FROM snapshots s JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash "
        "WHERE s.id = ?", (snapshot_id,)).fetchone()
    if row is None:
        raise SystemExit(f"No snapshot with id={snapshot_id}")
    return row


def collect_facts(obj, path: str = "") -> list[tuple[str, str, object]]:
    """Walk the snapshot, yielding (path, kind, value) for numbers and
    short name-like strings. `kind` is 'number', 'date', or 'name'."""
    facts: list[tuple[str, str, object]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            facts += collect_facts(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            facts += collect_facts(v, f"{path}[{i}]")
    elif isinstance(obj, bool) or obj is None:
        pass  # not a traceable fact
    elif isinstance(obj, (int, float)):
        facts.append((path, "number", obj))
    elif isinstance(obj, str):
        s = obj.strip()
        if not s:
            pass
        elif _ISO_DATE.match(s):
            facts.append((path, "date", s))
        elif len(s.split()) <= MAX_NAME_WORDS and not s.rstrip().endswith((".", ";", ":")):
            facts.append((path, "name", s))
        # else: narrative/commentary (long, or reads like a full sentence)
        # — paraphrase expected by the schema, not a verbatim quote, skip
    return facts


def number_variants(value: float, path: str) -> list[str]:
    vals = {value}
    if isinstance(value, float) and value.is_integer():
        vals.add(int(value))
    variants = set()
    for v in vals:
        variants.add(str(v))
        variants.add(f"{v:,}")
        if isinstance(v, float):
            for prec in (0, 1, 2):
                variants.add(f"{v:.{prec}f}")
                variants.add(f"{v:,.{prec}f}")
    if "pct" in path.lower() or "percent" in path.lower():
        variants |= {v + "%" for v in list(variants)}
    return sorted(variants, key=len, reverse=True)


def date_variants(value: str) -> list[str]:
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return [value]
    return [
        value,
        d.strftime("%B %d, %Y"),                       # July 03, 2026
        d.strftime("%B %d, %Y").replace(" 0", " "),     # July 3, 2026
        d.strftime("%d %b %Y"),                         # 03 Jul 2026
        d.strftime("%d-%b-%Y"),                         # 03-Jul-2026
    ]


def find_in_text(text: str, needle: str) -> tuple[int, str] | None:
    # `text` is pre-normalized (whitespace collapsed to single spaces) so
    # PDF line-wraps in the middle of a name/phrase don't cause a false
    # miss; normalize the needle the same way for a fair comparison.
    needle = " ".join(needle.split())
    idx = text.lower().find(needle.lower())
    if idx == -1:
        return None
    start = max(0, idx - CONTEXT_CHARS)
    end = min(len(text), idx + len(needle) + CONTEXT_CHARS)
    return idx, f"...{text[start:end]}..."


def audit(snapshot_id: int) -> None:
    row = load_snapshot(snapshot_id)
    snapshot = json.loads(row["snapshot_json"])
    if not row["pdf_path"]:
        raise SystemExit("No source document on file for this item "
                          "(pdf_path is empty) — can't trace it.")
    text = " ".join(doc_to_text(row["pdf_path"]).split())

    facts = collect_facts(snapshot)
    results = []
    for path, kind, value in facts:
        if kind == "number":
            variants = number_variants(value, path)
        elif kind == "date":
            variants = date_variants(value)
        else:
            variants = [value]

        hit = None
        for variant in variants:
            hit = find_in_text(text, variant)
            if hit:
                break
        results.append((path, kind, value, hit))

    found = sum(1 for *_, hit in results if hit)
    total = len(results)

    print(f"Snapshot {snapshot_id} — {row['company_name_raw']} "
          f"({row['doc_type']})")
    print(f"Source document: {row['pdf_path']}")
    print(f"Source text length: {len(text):,} chars\n")

    for path, kind, value, hit in results:
        mark = "OK  " if hit else "MISS"
        print(f"[{mark}] {kind:6} {path:40} = {value!r}")
        print(f"        {hit[1] if hit else '(not found in source text)'}")

    if total:
        pct = found / total * 100
        print(f"\nScore: {found}/{total} facts traced to source ({pct:.1f}%)")
    else:
        print("\nNo numeric/name facts found to check.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tools/audit_snapshot.py <snapshot_id>")
    audit(int(sys.argv[1]))
