"""IndiaRatings scraper — WORKING (verified live 04-Jul-2026).

RECON 02-Jul-26 pointed at /pressRelease's own listing call, which turned
out to be a dead end even with tools/probe.py's longer-wait + scroll
upgrade: the dedicated /pressrelease page's own API call
(pressReleases/GetPressreleaseData) returns an empty array and the
Angular app itself throws ("Cannot read properties of undefined
(reading 'prTypeName')") trying to render it — a live client-side bug
on their site, not a bot-detection issue we tripped. Guessing an /api/
base path directly returns the SPA shell HTML, matching the recon note.

Re-probed the homepage instead (which renders fine) and found it calls
several small JSON widgets under /home/ — most useful two:
    GET https://www.indiaratings.co.in/home/GetLatestHeadline
    GET https://www.indiaratings.co.in/home/GetRatingNews
Both return the ~10 most recent rating actions across ALL issuers
(overlapping but not identical sets — merged here). Fields include
issuerName, pressReleaseTitle, pressReleaseID, prDate ("Jul 03, 2026").

Detail endpoint (confirmed real, works without login, but only returns
a one-line teaser — the full rationale is gated behind login):
    GET https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=NNNNN

KNOWN LIMITATION: like CRISIL/ICRA, this is a single unpaginated page —
no working way found to reach further back than ~10 most recent items
across all issuers. Unlike CareEdge/CRISIL/ICRA, the "document" behind
each item is a thin teaser, not the full rationale — Claude's
extraction step will correctly end up with mostly-null fields for
anything beyond the headline, since the real detail requires a login
this project doesn't have.
"""
from __future__ import annotations

from datetime import date, datetime

from scrapers.base import BaseScraper, RatingItem

LIST_ENDPOINTS = (
    "https://www.indiaratings.co.in/home/GetLatestHeadline",
    "https://www.indiaratings.co.in/home/GetRatingNews",
)
DETAIL_ENDPOINT = (
    "https://www.indiaratings.co.in/pressReleases/"
    "GetPressreleaseData_BeforeLogin?pressReleaseId="
)


class IndiaRatingsScraper(BaseScraper):
    agency = "indiaratings"

    def fetch_new_items(self, since: date) -> list[RatingItem]:
        seen_ids: set[int] = set()
        items: list[RatingItem] = []
        for endpoint in LIST_ENDPOINTS:
            r = self.session.get(endpoint, timeout=45)
            r.raise_for_status()
            for row in r.json():
                pr_id = row.get("pressReleaseID")
                if pr_id is None or pr_id in seen_ids:
                    continue
                published = _parse_dt(row.get("prDate"))
                if published is None or published < since:
                    continue
                seen_ids.add(pr_id)
                items.append(RatingItem(
                    agency=self.agency,
                    company_name_raw=(row.get("issuerName") or "").strip(),
                    title=(row.get("pressReleaseTitle") or "").strip(),
                    pdf_url=f"{DETAIL_ENDPOINT}{pr_id}",
                    published_on=published,
                    doc_type="PR",
                ))
        return items


def _parse_dt(value: str | None) -> date | None:
    if not value:
        return None
    try:
        # e.g. "Jul 03, 2026"
        return datetime.strptime(value.strip(), "%b %d, %Y").date()
    except ValueError:
        return None
