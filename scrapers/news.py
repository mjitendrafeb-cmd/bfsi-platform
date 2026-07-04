"""News harvester — Google News RSS per entity alias. No bot protection, free.

Feed: https://news.google.com/rss/search?q="<alias>"&hl=en-IN&gl=IN&ceid=IN:en
One feed per alias; dedupe (in base class) is by link, so overlapping
aliases don't duplicate. PDFs are never downloaded for news.
"""
from __future__ import annotations

import csv
import time
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

from scrapers.base import BaseScraper, RatingItem

FEED = ("https://news.google.com/rss/search?q=%22{q}%22"
        "&hl=en-IN&gl=IN&ceid=IN:en")


class NewsScraper(BaseScraper):
    agency = "news"

    def __init__(self, *args, entity_master_csv: Path = Path("data/entity_master.csv"), **kw):
        kw["download_pdfs"] = False
        super().__init__(*args, **kw)
        self.queries: list[tuple[str, str]] = []   # (query, display_name)
        with open(entity_master_csv, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = row["display_name"].strip()
                self.queries.append((name, name))
                # Long aliases only — short ones ("MFL") flood with noise.
                for a in (row.get("aliases") or "").split(";"):
                    a = a.strip()
                    if len(a) >= 8:
                        self.queries.append((a, name))

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        items: list[RatingItem] = []
        for query, name in self.queries:
            url = FEED.format(q=quote(query))
            try:
                r = self.session.get(url, timeout=30)
                r.raise_for_status()
                root = ElementTree.fromstring(r.content)
            except Exception:
                continue
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                pub = _parse(it.findtext("pubDate"))
                if not link or pub is None or pub < since:
                    continue
                src = it.find("{https://news.google.com/rss}source")
                items.append(RatingItem(
                    agency=self.agency,
                    company_name_raw=name,
                    title=title,
                    pdf_url=link,               # article URL doubles as dedupe key
                    published_on=pub,
                    doc_type="news",
                    extra={"source": src.text if src is not None else "",
                           "query": query},
                ))
            time.sleep(1.0)
        return items


def _parse(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return parsedate_to_datetime(v).date()
    except (TypeError, ValueError):
        return None
