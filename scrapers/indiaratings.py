"""IndiaRatings scraper — STUB (roadmap week 1-4).

RECON 02-Jul-26: Angular SPA (runtime/main.js); /pressRelease renders list late, direct /api/ guesses return SPA shell. Use tools/probe.py with longer wait + scroll to capture the XHR, then replicate with requests.

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


class IndiaRatingsScraper(BaseScraper):
    agency = "indiaratings"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        raise NotImplementedError("indiaratings scraper not yet implemented")
