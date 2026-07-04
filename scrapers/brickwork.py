"""Brickwork scraper — WORKING (verified live 04-Jul-2026).

RECON 02-Jul-26 said /ratings-reviews.aspx 404s and flagged Brickwork as
possibly winding down post-SEBI action, worth verifying before
building. Verified: SEBI restrictions were lifted March 2024 and the
site is actively publishing — real, distinct rating actions dated
26-May-2026 through 3-Jul-2026 found directly on their press-release
page, continuous right up through yesterday.

Listing page (classic server-rendered ASP.NET, plain requests work
fine, no bot protection observed):
    GET https://www.brickworkratings.com/PressRelease.aspx
    -> <ul class="press-release-list"><li><a href=... aria-label="BWR
       {rating} : {Company} {Instrument} Rs.{amount}">...

Two different link styles are mixed in this one list:
  1. Admin/PressRelease/{Company}-{D}{Mon}{YYYY}...pdf — a real PDF,
     with its rating date already embedded in the filename (no extra
     request needed).
  2. https://bcrisp.in/BLRHTML/HTMLDocument/ViewRatingRationale...
     ?id=N — an HTML rationale (a shared rationale-hosting platform,
     apparently used across several agencies), with NO date visible on
     the listing page at all; the date only appears inside the
     document itself ("RATING RATIONALE 03Jul2026 ..."), so these
     need one extra fetch per distinct URL to determine `published_on`
     (several list entries share the same URL — one document can cover
     multiple instruments — so this is deduped by URL first).

Company name isn't in its own column — it's embedded in the link text
alongside the rating and instrument ("BWR AAA : Company Long Term Bank
Loan Rs.X Crore"), split out via the "Long Term"/"Short Term" marker
that reliably starts the instrument description in every sample seen.

URL-shape note: bcrisp.in links are query-string based (?id=N, the
same shape that broke ICRA's naive filename derivation) and the PDF
links repeat their exact URL across several list rows for the same
document — already covered by the global fix in
BaseScraper._pdf_filename (always dedupe-hash based), no special
handling needed here.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, RatingItem

LIST_ENDPOINT = "https://www.brickworkratings.com/PressRelease.aspx"
_INSTRUMENT_MARKER = re.compile(r"\b(Long Term|Short Term)\b")
# Month names show up abbreviated in the document text ("03Jul2026") but
# spelled out in full in filenames ("3July2026") — accept either.
_FILENAME_DATE = re.compile(r"-(\d{1,2})([A-Za-z]+?)(\d{4})")
_DOC_DATE = re.compile(r"RATING RATIONALE\s+(\d{1,2})([A-Za-z]+?)(\d{4})")


class BrickworkScraper(BaseScraper):
    agency = "brickwork"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        r = self.session.get(LIST_ENDPOINT, timeout=45)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        ul = soup.find("ul", class_="press-release-list")
        if ul is None:
            return []

        date_cache: dict[str, date | None] = {}
        items: list[RatingItem] = []
        for a in ul.find_all("a", href=True):
            href = a["href"]
            url = href if href.startswith("http") else f"https://www.brickworkratings.com/{href}"

            if url not in date_cache:
                date_cache[url] = self._resolve_date(url)
            published = date_cache[url]
            if published is None or published < since:
                continue

            text = a.get_text(" ", strip=True)
            _, _, rest = text.partition(":")
            rest = rest.strip()
            m = _INSTRUMENT_MARKER.search(rest)
            company = (rest[:m.start()] if m else rest).strip()
            if not company:
                continue

            items.append(RatingItem(
                agency=self.agency,
                company_name_raw=company,
                title=text,
                pdf_url=url,
                published_on=published,
                doc_type="PR",
            ))
        return items

    def _resolve_date(self, url: str) -> date | None:
        m = _FILENAME_DATE.search(url)
        if m:
            return _parse_ordinal(*m.groups())
        try:
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
        except Exception:
            return None
        # "RATING RATIONALE" and the date are in separate tags
        # (<h6>...</h6><span>03Jul2026</span>), not adjacent in the raw
        # HTML — search the rendered text, not the markup.
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        m = _DOC_DATE.search(text)
        return _parse_ordinal(*m.groups()) if m else None


def _parse_ordinal(day: str, mon: str, year: str) -> date | None:
    try:
        # %b wants a 3-letter abbreviation; truncate full names ("July" -> "Jul")
        return datetime.strptime(f"{int(day):02d} {mon[:3]} {year}", "%d %b %Y").date()
    except ValueError:
        return None
