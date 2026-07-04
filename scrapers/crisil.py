"""Crisil scraper — WORKING (verified live 04-Jul-2026).

RECON 02-Jul-26 pointed at .../ratings/rating-actions.html, which no longer
exists (site restructured). Re-probed with tools/probe.py against the
current listing page and found its internal JSON API:

    GET https://www.crisilratings.com/content/crisilratings/en/home/
        our-business/ratings/rating-rationale/_jcr_content/wrapper_100_par/
        ratingresultlisting.results.json
        ?cmd=RR&start=0&limit=200&filters={}

Response: {"docs": [{companyName, heading, transDate ("Jul 03, 2026"),
                     ratingFileName, ...}], "numFound": <total in DB>}

Rationale document (HTML, not PDF):
    https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/
    RatingDocs/{ratingFileName}   (ratingFileName may contain spaces —
    URL-encode it)

KNOWN LIMITATION: pagination via `start` is broken server-side — any
nonzero `start` returns either an empty doc list or a 500 wrapped in a
200 response. Only `start=0` is reliable, so this scraper fetches a
single page (most-recent-first) and filters client-side by `since`.
A single page of ~200-500 docs already spans several days across ALL
companies CRISIL rates, which is enough for the --days windows this
project uses, but a `since` far in the past will silently under-fetch.

Also: the site sits behind an Indusface AppTrana WAF that returns 406
"Request was blocked due to suspicious behavior" if hit too rapidly —
keep to one request per run.
"""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

from scrapers.base import BaseScraper, RatingItem

LIST_ENDPOINT = (
    "https://www.crisilratings.com/content/crisilratings/en/home/"
    "our-business/ratings/rating-rationale/_jcr_content/wrapper_100_par/"
    "ratingresultlisting.results.json"
)
DOC_BASE = "https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/RatingDocs/"


class CrisilScraper(BaseScraper):
    agency = "crisil"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        params = {"cmd": "RR", "start": 0, "limit": 200, "filters": "{}"}
        r = self.session.get(LIST_ENDPOINT, params=params, timeout=45)
        r.raise_for_status()
        docs = r.json().get("docs", [])

        items: list[RatingItem] = []
        for row in docs:
            file_name = (row.get("ratingFileName") or "").strip()
            if not file_name:
                continue
            published = _parse_dt(row.get("transDate"))
            if published is None or published < since:
                continue
            items.append(RatingItem(
                agency=self.agency,
                company_name_raw=(row.get("companyName") or "").strip(),
                title=(row.get("heading") or "").strip(),
                pdf_url=DOC_BASE + quote(file_name),
                published_on=published,
                doc_type="RR",
            ))
        return items


def _parse_dt(value: str | None) -> date | None:
    if not value:
        return None
    try:
        # e.g. "Jul 03, 2026"
        return datetime.strptime(value.strip(), "%b %d, %Y").date()
    except ValueError:
        return None
