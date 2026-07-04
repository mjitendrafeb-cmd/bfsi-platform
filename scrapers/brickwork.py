"""Brickwork scraper — STUB (roadmap week 1-4).

RECON 02-Jul-26: /ratings-reviews.aspx returns 404. Brickwork has been winding down post SEBI action - VERIFY whether it still publishes new ratings at all before spending effort; may be droppable from the 7.

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


class BrickworkScraper(BaseScraper):
    agency = "brickwork"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        raise NotImplementedError("brickwork scraper not yet implemented")
