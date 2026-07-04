"""Delta engine — the platform's core.

Step 1 (deterministic, no LLM): field-by-field diff of two snapshots of
the same (entity, doc_type[, agency]). Exact. Cannot hallucinate.

Step 2 (LLM): grade each change's materiality and write the delta note —
"what changed and why it matters" — the only thing the user reads.
"""
from __future__ import annotations

import json
import os


# ---------------------------------------------------------------------------
# Step 1 — deterministic diff
# ---------------------------------------------------------------------------
def diff_snapshots(prev: dict, new: dict, prefix: str = "") -> list[dict]:
    """Returns [{field, old, new, kind}] for every changed leaf."""
    changes: list[dict] = []
    keys = {*prev, *new} - {"_doc_type"}
    for k in sorted(keys):
        path = f"{prefix}{k}"
        a, b = prev.get(k), new.get(k)
        if isinstance(a, dict) and isinstance(b, dict):
            changes += diff_snapshots(a, b, path + ".")
        elif isinstance(a, list) and isinstance(b, list) and not _scalar_list(a, b):
            # lists of bullets/objects: set-style compare on json repr
            sa = {json.dumps(x, sort_keys=True) for x in a}
            sb = {json.dumps(x, sort_keys=True) for x in b}
            for item in sorted(sb - sa):
                changes.append({"field": path, "old": None,
                                "new": json.loads(item), "kind": "added"})
            for item in sorted(sa - sb):
                changes.append({"field": path, "old": json.loads(item),
                                "new": None, "kind": "removed"})
        elif a != b:
            kind = "modified"
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                kind = "increased" if b > a else "decreased"
            changes.append({"field": path, "old": a, "new": b, "kind": kind})
    return changes


def _scalar_list(a: list, b: list) -> bool:
    return all(not isinstance(x, (dict, list)) for x in a + b) and a == b


# ---------------------------------------------------------------------------
# Step 2 — materiality + delta note (LLM)
# ---------------------------------------------------------------------------
DELTA_MODEL = "claude-sonnet-4-6"

DELTA_SYSTEM = """You are a senior credit analyst reviewing what changed \
between two versions of a document about the same company. You receive an \
exact machine-generated list of changes — you must NOT invent changes \
beyond this list. Output ONLY JSON:
{
 "materiality": "high|medium|low",
 "delta_note": "<=6 crisp lines: what changed and why it matters from a \
credit perspective. Lead with the most material change. Use figures. No \
filler, no restating unchanged facts.",
 "changes_graded": [{"field": "...", "materiality": "high|medium|low"}],
 "suggested_watchlist_items": ["only if a change warrants ongoing monitoring"]
}
Credit lens: rating/outlook/watch changes and driver/sensitivity changes \
are high; asset-quality and capital moves usually high/medium; analyst \
name changes and cosmetic rewording are low."""


def grade_delta(entity_name: str, doc_type: str,
                changes: list[dict]) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = (f"Company: {entity_name}\nDocument type: {doc_type}\n"
              f"Exact changes (old → new):\n"
              f"{json.dumps(changes, indent=1)[:20000]}\n\nReturn the JSON.")
    msg = client.messages.create(
        model=DELTA_MODEL, max_tokens=1500, temperature=0,
        system=DELTA_SYSTEM,
        messages=[{"role": "user", "content": prompt}])
    raw = msg.content[0].text.strip().removeprefix("```json").removeprefix(
        "```").removesuffix("```").strip()
    return json.loads(raw)


def baseline_note(snapshot: dict) -> dict:
    """First document of its type for an entity — no diff possible."""
    return {"materiality": "low",
            "delta_note": "Baseline established — first "
                          f"{snapshot.get('_doc_type','document')} on record; "
                          "future documents will be diffed against this.",
            "changes_graded": [], "suggested_watchlist_items": []}
