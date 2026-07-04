"""Icra scraper — WORKING (verified live 04-Jul-2026).

RECON 02-Jul-26 said plain requests get a 503 from Imperva/Incapsula bot
protection, requiring Playwright. Re-tested live: plain `requests` GETs
to both the homepage and the listing page returned clean 200s with no
challenge at all — the bot protection either isn't active on this path
right now or was tightened only intermittently. Kept plain `requests`
since it's simpler and it worked; revisit with Playwright + stealth
(see tools/probe.py) if 503s start appearing.

Listing page (server-rendered HTML table, no JSON API found):
    GET https://www.icra.in/Rating/AllRatingRationales

Each row: date ("03 Jul 2026") | sector | a link to
    /Rationale/ShowRationaleReport?Id=NNNNN
whose link text is "<Company Name>: <rating action description>".

PDF (confirmed real application/pdf, ~675KB on a sample fetch):
    https://www.icra.in/Rating/GetRationalReportFilePdf?Id=NNNNN
    (same Id as the rationale report)

KNOWN LIMITATION: the page's date-range search fields (ratingFromDate /
ratingToDate) are wired to client-side JS/AJAX, not plain query-string
GET params — tried both and got byte-identical responses either way.
So, like CRISIL, this only fetches the single default listing page
(most-recent items, currently ~20 rows spanning 3 days) and filters
client-side by `since`; it will not reach further back than that.
"""
from __future__ import annotations

from datetime import date, datetime

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, RatingItem

LIST_ENDPOINT = "https://www.icra.in/Rating/AllRatingRationales"
PDF_BASE = "https://www.icra.in/Rating/GetRationalReportFilePdf?Id="


class IcraScraper(BaseScraper):
    agency = "icra"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        r = self.session.get(LIST_ENDPOINT, timeout=45)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        items: list[RatingItem] = []
        for row in soup.select("table.table tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            link = cells[2].find("a", href=True)
            if not link or "ShowRationaleReport" not in link["href"]:
                continue

            published = _parse_dt(cells[0].get_text(strip=True))
            if published is None or published < since:
                continue

            rid = link["href"].rsplit("Id=", 1)[-1]
            heading = link.get_text(strip=True)
            company_name, _, _ = heading.partition(":")

            items.append(RatingItem(
                agency=self.agency,
                company_name_raw=company_name.strip(),
                title=heading,
                pdf_url=PDF_BASE + rid,
                published_on=published,
                doc_type=cells[1].get_text(strip=True) or "RR",
            ))
        return items


def _parse_dt(value: str | None) -> date | None:
    if not value:
        return None
    try:
        # e.g. "03 Jul 2026"
        return datetime.strptime(value.strip(), "%d %b %Y").date()
    except ValueError:
        return None
