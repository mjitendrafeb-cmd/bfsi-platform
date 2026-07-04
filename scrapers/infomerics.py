"""Infomerics scraper — STUB (roadmap week 1-4).

RECON 02-Jul-26: Next.js RSC app; /latest-press-release payload streams client-side. Use tools/probe.py to capture the /_next data or API route, then call directly.

How to implement:
  1. Open the agency's rationale/press-release listing page with browser
     DevTools > Network tab open.
  2. If the list loads via XHR/fetch (like CareEdge's /rrcompany), call that
     JSON endpoint directly — always prefer this over HTML parsing.
  3. If server-rendered HTML: parse with BeautifulSoup.
  4. If JS-rendered with no clean endpoint: Playwright fallback.
Only fetch_new_items() needs writing; the base class does the rest.
"""
from datetime import date

from scrapers.base import BaseScraper, RatingItem


class InfomericsScraper(BaseScraper):
    agency = "infomerics"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        raise NotImplementedError("infomerics scraper not yet implemented")
