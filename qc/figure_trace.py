"""Figure-trace audit helpers.

Every extracted number/name should be traceable to source text before it is
trusted. This module is intentionally deterministic and conservative: values
are normalised for commas/currency symbols, but not inferred or rounded.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def _flatten(snapshot, prefix=""):
    if isinstance(snapshot, dict):
        for key, value in snapshot.items():
            if key.startswith("_"):
                continue
            yield from _flatten(value, f"{prefix}.{key}" if prefix else key)
    elif isinstance(snapshot, list):
        for idx, value in enumerate(snapshot):
            yield from _flatten(value, f"{prefix}[{idx}]")
    else:
        yield prefix, snapshot


def _number_variants(value: int | float | str) -> set[str]:
    raw = str(value).strip()
    variants = {raw, raw.replace(",", "")}
    try:
        num = float(raw.replace(",", ""))
    except ValueError:
        return variants
    if num.is_integer():
        variants.add(str(int(num)))
        variants.add(f"{int(num):,}")
    variants.add(str(num))
    return {v for v in variants if v}


def audit_snapshot(snapshot: dict, source_text: str) -> list[dict]:
    """Return trace failures for numeric leaf fields absent from source_text."""
    compact_text = source_text.replace(",", "")
    failures = []
    for path, value in _flatten(snapshot):
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)) or _NUM_RE.fullmatch(str(value).strip()):
            if not any(v in source_text or v.replace(",", "") in compact_text for v in _number_variants(value)):
                failures.append({"field": path, "value": value, "reason": "number_not_found_in_source"})
    return failures
