"""Base scraper — every CRA scraper inherits this.

Each concrete scraper only implements fetch_new_items().
The base class handles: entity matching, dedupe, storage, PDF download,
and health reporting. Keep it that way — pipeline logic lives here once.
"""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import requests

from common.entity_match import EntityMatcher
from common.storage import Storage

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}


@dataclass
class RatingItem:
    """One press release / rating rationale as listed on a CRA site."""

    agency: str
    company_name_raw: str          # name exactly as the CRA publishes it
    title: str
    pdf_url: str
    published_on: date
    doc_type: str = "PR"           # PR / rationale / other
    extra: dict = field(default_factory=dict)

    @property
    def dedupe_hash(self) -> str:
        key = f"{self.agency}|{self.pdf_url}"
        return hashlib.sha256(key.encode()).hexdigest()[:32]


class BaseScraper(ABC):
    agency: str = "OVERRIDE_ME"

    def __init__(self, storage: Storage, matcher: EntityMatcher,
                 pdf_dir: Path | None = None, download_pdfs: bool = True):
        self.storage = storage
        self.matcher = matcher
        self.download_pdfs = download_pdfs
        self.pdf_dir = pdf_dir or Path("db/pdfs") / self.agency
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ------------------------------------------------------------------
    # The ONLY method a concrete scraper must implement.
    # ------------------------------------------------------------------
    @abstractmethod
    def fetch_new_items(self, since: date) -> list[RatingItem]:
        """Return all PR/rationale items published on/after `since`."""

    # ------------------------------------------------------------------
    # Shared pipeline
    # ------------------------------------------------------------------
    def run(self, since: date) -> dict:
        """Fetch → dedupe → entity-match → store. Returns run stats."""
        stats = {"agency": self.agency, "fetched": 0, "new": 0,
                 "matched": 0, "errors": 0}
        try:
            items = self.fetch_new_items(since)
        except Exception:
            log.exception("[%s] fetch failed", self.agency)
            stats["errors"] += 1
            self.storage.record_health(self.agency, ok=False,
                                       note="fetch_new_items raised")
            return stats

        stats["fetched"] = len(items)
        for item in items:
            if self.storage.seen(item.dedupe_hash):
                continue
            stats["new"] += 1

            match = self.matcher.match(item.company_name_raw)
            if match:
                stats["matched"] += 1

            pdf_path = None
            if self.download_pdfs and match:
                # Only spend bandwidth on tracked entities.
                pdf_path = self._download_pdf(item)

            self.storage.insert_item(
                dedupe_hash=item.dedupe_hash,
                agency=self.agency,
                company_name_raw=item.company_name_raw,
                entity_id=match.entity_id if match else None,
                match_confidence=match.confidence if match else None,
                title=item.title,
                doc_type=item.doc_type,
                pdf_url=item.pdf_url,
                pdf_path=str(pdf_path) if pdf_path else None,
                published_on=item.published_on.isoformat(),
            )

        # Health fingerprint: zero fetched items for several runs in a row
        # usually means the site changed, not that ratings stopped.
        self.storage.record_health(self.agency, ok=stats["fetched"] > 0,
                                   note=f"fetched={stats['fetched']}")
        log.info("[%s] %s", self.agency, stats)
        return stats

    def _download_pdf(self, item: RatingItem) -> Path | None:
        try:
            self.pdf_dir.mkdir(parents=True, exist_ok=True)
            fname = self._pdf_filename(item)
            out = self.pdf_dir / fname
            if out.exists():
                return out
            r = self.session.get(item.pdf_url, timeout=60)
            r.raise_for_status()
            out.write_bytes(r.content)
            return out
        except Exception:
            log.exception("[%s] pdf download failed: %s",
                          self.agency, item.pdf_url)
            return None

    @staticmethod
    def _pdf_filename(item: RatingItem) -> str:
        """Path segment when the URL has one (CareEdge/Crisil: readable,
        stable per file). For query-string-driven endpoints (e.g. ICRA's
        .../GetRationalReportFilePdf?Id=NNNNN) the path alone repeats for
        every document and isn't filesystem-safe, so fall back to the
        (unique, safe) dedupe hash instead.
        """
        parsed = urlsplit(item.pdf_url)
        path_name = parsed.path.rstrip("/").split("/")[-1]
        if path_name and not parsed.query:
            return path_name
        ext = path_name.rsplit(".", 1)[-1] if "." in path_name else "pdf"
        return f"{item.dedupe_hash}.{ext}"
