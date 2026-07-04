"""Exchange RSS scraper — WORKING (all feeds verified live 03-Jul-2026).

Market-wide RSS feeds (no bot protection — NSE's RSS sidesteps the
blocking its API/website enforces):

  NSE announcements : https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml
  NSE fin. results  : https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml
  BSE announcements : https://www.bseindia.com/data/xml/announcements.xml
  BSE notices       : https://www.bseindia.com/data/xml/notices.xml

Feeds carry ALL listed companies; we filter via the entity matcher.
Complements bse.py (per-scrip API, deeper history): RSS = real-time
market-wide sweep; API = targeted backfill. Dedupe makes overlap free.
"""
from __future__ import annotations

import re
from datetime import date
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from scrapers.base import BaseScraper, RatingItem

FEEDS = [
    ("nse", "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml", "filing"),
    ("nse", "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml", "results"),
    ("bse", "https://www.bseindia.com/data/xml/announcements.xml", "filing"),
    ("bse", "https://www.bseindia.com/data/xml/notices.xml", "notice"),
]

_BSE_SUFFIX = re.compile(r"[-$*]*\s*\(\d{6}\)\s*$")   # "Name-$ (506261)"


class ExchangeRssScraper(BaseScraper):
    agency = "exchange_rss"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        items: list[RatingItem] = []
        for exch, url, default_type in FEEDS:
            try:
                r = self.session.get(url, timeout=45)
                r.raise_for_status()
                root = ElementTree.fromstring(r.content)
            except Exception:
                continue
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip()
                desc = (it.findtext("description") or "").strip()
                link = (it.findtext("link") or "").strip()
                pub = _parse(it.findtext("pubDate"))
                if not title or (pub and pub < since):
                    continue
                company = _BSE_SUFFIX.sub("", title).strip()
                # Cheap pre-filter before full matcher: skip obvious non-hits
                if not self.matcher.match(company):
                    continue
                items.append(RatingItem(
                    agency=self.agency,
                    company_name_raw=company,
                    title=desc[:300] if desc else title,
                    pdf_url=link or f"{exch}://{title[:80]}",
                    published_on=pub or date.today(),
                    doc_type=default_type,
                    extra={"exchange": exch},
                ))
        return items


def _parse(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return parsedate_to_datetime(v).date()
    except (TypeError, ValueError):
        return None
