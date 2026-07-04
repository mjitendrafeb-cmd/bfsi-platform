"""Dispatcher — run one scraper or all.

Usage:
    python run.py careedge --days 7
    python run.py all --days 2
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from common.entity_match import EntityMatcher
from common.storage import Storage
from scrapers.careedge import CareEdgeScraper
from scrapers.bse import BseScraper
from scrapers.news import NewsScraper
from scrapers.exchange_rss import ExchangeRssScraper
from scrapers.crisil import CrisilScraper

# Stubs land here as they're implemented (week 1-4 of roadmap):
# from scrapers.icra import IcraScraper
# from scrapers.indiaratings import IndiaRatingsScraper
# from scrapers.acuite import AcuiteScraper
# from scrapers.infomerics import InfomericsScraper
# from scrapers.brickwork import BrickworkScraper

SCRAPERS = {
    "careedge": CareEdgeScraper,
    "bse": BseScraper,
    "news": NewsScraper,
    "exchange_rss": ExchangeRssScraper,
    "crisil": CrisilScraper,
}

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("agency", choices=[*SCRAPERS, "all"])
    p.add_argument("--days", type=int, default=3,
                   help="look-back window (dedupe handles overlap)")
    p.add_argument("--no-pdfs", action="store_true",
                   help="skip PDF downloads (listing only)")
    args = p.parse_args()

    storage = Storage(Path("db/tracker.sqlite"))
    matcher = EntityMatcher(Path("data/entity_master.csv"))
    since = date.today() - timedelta(days=args.days)

    targets = SCRAPERS.values() if args.agency == "all" \
        else [SCRAPERS[args.agency]]

    for cls in targets:
        scraper = cls(storage, matcher, download_pdfs=not args.no_pdfs)
        scraper.run(since)

    print("\n=== DB summary (agency | total | matched to your 300 | latest) ===")
    for row in storage.summary():
        print(" | ".join(str(c) for c in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
