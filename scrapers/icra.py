"""Icra scraper — STUB (roadmap week 1-4).

RECON 02-Jul-26: https://www.icra.in returns 503 to plain requests (Imperva/Incapsula bot protection). Needs Playwright with stealth args; from GitHub Actions IPs may still be challenged - test early. Listing page: icra.in/Rating/RatingAction; PDFs under icra.in/Rationale/.

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


class IcraScraper(BaseScraper):
    agency = "icra"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        raise NotImplementedError("icra scraper not yet implemented")
