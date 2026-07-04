"""Extractor — document text → structured snapshot via Claude.

Requires ANTHROPIC_API_KEY in env. Model choice per blueprint:
Sonnet for extraction accuracy. Temperature 0. JSON-only output.
"""
from __future__ import annotations

import json
import os
import re

EXTRACT_MODEL = "claude-sonnet-4-6"

SYSTEM = """You are a credit analyst's extraction engine for Indian BFSI \
documents (rating rationales, exchange filings, results, news). You output \
ONLY a single JSON object matching the schema given — no markdown, no \
preamble. Rules:
- Extract ONLY what the document states. Never infer, never fill gaps. \
Missing → null (or empty list).
- Percentages as plain numbers (2.7 not "2.7%"). Amounts in Rs crore \
(convert lakh/million/billion if needed; state as number).
- Rating drivers/sensitivities: one concise bullet each, preserving the \
document's substance and any figures it cites.
- If the document is not the type described by the schema, return \
{"schema_mismatch": true, "actual_content": "<one line>"}."""


def pdf_to_text(pdf_path: str, max_pages: int = 15) -> str:
    import pdfplumber
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def extract(text: str, schema: dict) -> dict:
    """One Claude call → snapshot dict. Raises on missing key or bad JSON."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = (
        f"Schema (field: description):\n{json.dumps(schema['fields'], indent=1)}\n\n"
        f"Document text:\n<<<\n{text[:60000]}\n>>>\n\n"
        "Return the JSON object now."
    )
    msg = client.messages.create(
        model=EXTRACT_MODEL, max_tokens=4000, temperature=0,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.M).strip()
    snapshot = json.loads(raw)
    snapshot["_doc_type"] = schema["doc_type"]
    return snapshot


def extraction_confidence(snapshot: dict) -> float:
    """Crude confidence: share of non-null leaf fields. Low → review queue."""
    leaves, filled = 0, 0

    def walk(v):
        nonlocal leaves, filled
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            leaves += 1
            filled += bool(v)
        else:
            leaves += 1
            filled += v is not None and v != ""

    walk({k: v for k, v in snapshot.items() if not k.startswith("_")})
    return round(filled / leaves, 2) if leaves else 0.0
