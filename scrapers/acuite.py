"""Acuite scraper — WORKING (verified live 04-Jul-2026).

RECON 02-Jul-26 found 403s on www.acuite.in/latest-ratings.htm (bot
protection) and suggested Playwright or the SEBI-disclosure Excel as a
fallback. Neither was needed: Acuite's actual live-ratings listing
lives on a separate subdomain, linked from the homepage as "Live
Ratings" —

    GET https://connect.acuite.in/liveratings?page=N

— which has NO bot protection at all: plain `requests` returns a clean
200. Pagination is real and works (unlike CRISIL/ICRA's), so this can
properly honour `since` instead of being stuck on a single page.

The listing itself only renders one placeholder row through plain
requests (the rest is filled in by JS from data embedded in the same
HTML response) — walking the raw tags by class (td-date / td-company)
instead of via <tr> avoids relying on the (malformed) table structure
BeautifulSoup's parser loses rows on.

Each entry links to a company detail page with the FULL rating
rationale as plain HTML (no PDF, no login wall):
    https://connect.acuite.in/fcompany-details/{company}/{date}
Handled automatically by pipeline.extract.doc_to_text (HTML branch).
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, RatingItem

LIST_ENDPOINT = "https://connect.acuite.in/liveratings"
MAX_PAGES = 20          # safety cap, not expected to be hit for --days <= 30
PAGE_DELAY_SECS = 1.5   # gentle pacing between page requests


class AcuiteScraper(BaseScraper):
    agency = "acuite"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        items: list[RatingItem] = []
        for page in range(1, MAX_PAGES + 1):
            r = self.session.get(LIST_ENDPOINT, params={"page": page}, timeout=45)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            dates = soup.find_all(class_="td-date")
            companies = soup.find_all(class_="td-company")
            if not dates:
                break

            page_had_recent_item = False
            for date_cell, company_cell in zip(dates, companies):
                published = _parse_dt(date_cell.get_text(strip=True))
                if published is None:
                    continue
                if published < since:
                    continue
                page_had_recent_item = True

                link = company_cell.find("a", href=True)
                if not link:
                    continue
                items.append(RatingItem(
                    agency=self.agency,
                    company_name_raw=link.get_text(strip=True),
                    title=f"{link.get_text(strip=True)} — rating action "
                          f"{date_cell.get_text(strip=True)}",
                    pdf_url=link["href"],
                    published_on=published,
                    doc_type="PR",
                ))

            if not page_had_recent_item:
                break  # this page was entirely older than `since` — done
            time.sleep(PAGE_DELAY_SECS)
        return items


_ORDINAL = re.compile(r"(\d+)(st|nd|rd|th)\b", re.I)


def _parse_dt(value: str | None) -> date | None:
    if not value:
        return None
    try:
        # e.g. "3rd Jul 26" -> "3 Jul 26"
        cleaned = _ORDINAL.sub(r"\1", value.strip())
        return datetime.strptime(cleaned, "%d %b %y").date()
    except ValueError:
        return None
