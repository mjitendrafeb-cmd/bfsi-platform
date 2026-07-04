"""CareEdge Ratings scraper — WORKING (verified live 02-Jul-2026).

CareEdge's website renders its press-release list client-side from a JSON
endpoint, so we hit the endpoint directly (faster and far more stable than
HTML parsing):

    GET https://www.careratings.com/rrcompany
        ?companyName=&YearID=&fdate=YYYY-MM-DD&tdate=YYYY-MM-DD

Response: {"data": [{CompanyName, FileTitle, FileType, FileURL,
                     PublishedDate}, ...]}

PDF location: https://www.careratings.com/upload/CompanyFiles/PR/{FileURL}
"""
from __future__ import annotations

from datetime import date, datetime

from scrapers.base import BaseScraper, RatingItem

LIST_ENDPOINT = "https://www.careratings.com/rrcompany"
PDF_BASE = "https://www.careratings.com/upload/CompanyFiles/PR/"


class CareEdgeScraper(BaseScraper):
    agency = "careedge"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        params = {
            "companyName": "",
            "YearID": "",
            "fdate": since.isoformat(),
            "tdate": date.today().isoformat(),
        }
        r = self.session.get(LIST_ENDPOINT, params=params, timeout=45)
        r.raise_for_status()
        rows = r.json().get("data", [])

        items: list[RatingItem] = []
        for row in rows:
            file_url = (row.get("FileURL") or "").strip()
            if not file_url:
                continue
            published = _parse_dt(row.get("PublishedDate"))
            if published is None or published < since:
                continue
            items.append(RatingItem(
                agency=self.agency,
                company_name_raw=(row.get("CompanyName") or "").strip(),
                title=(row.get("FileTitle") or "").strip(),
                pdf_url=PDF_BASE + file_url,
                published_on=published,
                doc_type=(row.get("FileType") or "PR").strip(),
            ))
        return items


def _parse_dt(value: str | None) -> date | None:
    if not value:
        return None
    try:
        # e.g. "2026-07-02 00:00:00.000"
        return datetime.fromisoformat(value.split(".")[0]).date()
    except ValueError:
        return None
