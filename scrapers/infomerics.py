"""Infomerics scraper — WORKING (verified live 04-Jul-2026).

RECON 02-Jul-26: Next.js RSC app; /latest-press-release payload streams
client-side. That exact page path is stale (404 — site restructured,
same pattern as every other agency this pilot). The real "latest press
releases" feed turned out to be embedded in the *homepage's* own React
Server Component payload, fetched the same way Next.js's client-side
router prefetches it: a plain GET with an `RSC: 1` header.

    GET https://www.infomerics.com/
    Header: RSC: 1

(The `?_rsc=<hash>` query param visible in DevTools is just an opaque
cache-busting token — confirmed live that it's not required at all;
the header alone is what matters.)

The response is Next.js's "Flight" wire format, not plain JSON — it's
a stream with plain JSON objects embedded at various points, not one
valid top-level JSON document. Each recent press release appears as a
`"PressRelease": {...}` object. Extracted with a brace-matching scan
(respecting quoted strings) rather than a naive regex, since nested
braces inside make a simple non-greedy regex unreliable; each matched
object is then parsed individually with json.loads().

Company name is Document.DocumentTitle — NOT PressRelease.Title, which
is null for every recent entry (confirmed by inspecting the raw
payload). PDF is Document.DocumentFile.url, hosted on Azure Blob
Storage; filenames already end in a random hash, so no URL-shape
filename collision risk like the one fixed for ICRA/Acuite.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from scrapers.base import BaseScraper, RatingItem

HOMEPAGE = "https://www.infomerics.com/"
RSC_HEADERS = {"RSC": "1"}


class InfomericsScraper(BaseScraper):
    agency = "infomerics"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        r = self.session.get(HOMEPAGE, headers=RSC_HEADERS, timeout=45)
        r.raise_for_status()
        text = r.text

        items: list[RatingItem] = []
        seen_urls: set[str] = set()
        for match in re.finditer(r'"PressRelease":(\{)', text):
            obj_text = _extract_balanced(text, match.start(1))
            if obj_text is None:
                continue
            try:
                obj = json.loads(obj_text)
            except json.JSONDecodeError:
                continue

            published = _parse_dt(obj.get("Date"))
            if published is None or published < since:
                continue

            doc = obj.get("Document") or {}
            file_info = doc.get("DocumentFile") or {}
            pdf_url = file_info.get("url")
            if not pdf_url or pdf_url in seen_urls:
                continue
            seen_urls.add(pdf_url)

            company = (doc.get("DocumentTitle") or "").strip()
            if not company:
                continue

            items.append(RatingItem(
                agency=self.agency,
                company_name_raw=company,
                title=f"{company} — Infomerics press release {obj.get('Date')}",
                pdf_url=pdf_url,
                published_on=published,
                doc_type="PR",
            ))
        return items


def _extract_balanced(text: str, start: int) -> str | None:
    """Substring of the balanced {...} object starting at text[start]
    ('{'), respecting quoted strings/escapes — the RSC stream isn't
    valid JSON as a whole, so this can't just be json.loads()'d from
    the outer level."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def _parse_dt(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
