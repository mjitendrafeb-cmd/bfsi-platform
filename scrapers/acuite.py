"""Acuite scraper — STUB (roadmap week 1-4).

RECON 02-Jul-26: 403 to plain requests on /latest-ratings.htm (bot protection). Try Playwright; ratings listing also mirrored in monthly disclosure Excel on SEBI-mandated pages - a clean fallback worth checking.

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


class AcuiteScraper(BaseScraper):
    agency = "acuite"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        raise NotImplementedError("acuite scraper not yet implemented")
