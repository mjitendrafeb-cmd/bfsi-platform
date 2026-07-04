"""BSE corporate announcements scraper — WORKING (verified live 02-Jul-2026).

BSE exposes a JSON API used by its own announcements page:

    GET https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w
        ?pageno=1&strCat=-1&strPrevDate=YYYYMMDD&strToDate=YYYYMMDD
        &strScrip=<scrip>&strSearch=P&strType=C&subcategory=-1

Requires Referer: https://www.bseindia.com/ header.
Attachment PDFs: https://www.bseindia.com/xml-data/corpfiling/AttachLive/<ATTACHMENTNAME>

Covers listed pilot entities only (unlisted ones have no exchange filings —
their signal comes from CRA scrapers + news).
"""
from __future__ import annotations

import csv
import time
from datetime import date, datetime
from pathlib import Path

from scrapers.base import BaseScraper, RatingItem

API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"


class BseScraper(BaseScraper):
    agency = "bse"

    def __init__(self, *args, entity_master_csv: Path = Path("data/entity_master.csv"), **kw):
        super().__init__(*args, **kw)
        self.session.headers["Referer"] = "https://www.bseindia.com/"
        self.scrips: list[tuple[str, str]] = []   # (scrip_code, display_name)
        with open(entity_master_csv, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("listed", "").upper() == "TRUE" and row.get("bse_code"):
                    self.scrips.append((row["bse_code"].strip(),
                                        row["display_name"].strip()))

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        items: list[RatingItem] = []
        for scrip, name in self.scrips:
            params = {
                "pageno": 1, "strCat": "-1", "subcategory": "-1",
                "strPrevDate": since.strftime("%Y%m%d"),
                "strToDate": date.today().strftime("%Y%m%d"),
                "strScrip": scrip, "strSearch": "P", "strType": "C",
            }
            r = self.session.get(API, params=params, timeout=30)
            r.raise_for_status()
            for row in r.json().get("Table", []):
                dt = _parse(row.get("NEWS_DT"))
                if dt is None or dt < since:
                    continue
                attach = (row.get("ATTACHMENTNAME") or "").strip()
                items.append(RatingItem(
                    agency=self.agency,
                    company_name_raw=name,          # exact master name → 1.0 match
                    title=(row.get("NEWSSUB") or row.get("HEADLINE") or "").strip(),
                    pdf_url=ATTACH + attach if attach else
                            f"bse://{row.get('NEWSID','')}",
                    published_on=dt,
                    doc_type=(row.get("CATEGORYNAME") or "filing").strip() or "filing",
                    extra={"scrip": scrip,
                           "critical": row.get("CRITICALNEWS")},
                ))
            time.sleep(1.5)   # be polite: one entity per 1.5s
        return items


def _parse(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v[:19]).date()
    except ValueError:
        return None
