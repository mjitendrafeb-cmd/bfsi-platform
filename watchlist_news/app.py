from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import os
import re
import smtplib
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
SEPARATORS = re.compile(r"\s+(?:[-–—|])\s+")
JUNK = re.compile(
    r"trading window|book closure|record date|investor meet|analyst meet|"
    r"esop.*allot|agm|egm|annual general meeting|extraordinary general meeting|"
    r"shareholder intimation",
    re.I,
)
KEEP = re.compile(
    r"auditor|chief financial officer|\bcfo\b|managing director|\bmd\b|"
    r"rating|downgrade|default|\bncd\b|debenture|borrowing|restructur|"
    r"insolvency|pledge",
    re.I,
)
log = logging.getLogger("watchlist_news")


@dataclass(frozen=True)
class PortfolioRow:
    company: str
    analyst_name: str
    analyst_email: str


@dataclass
class NewsItem:
    company: str
    title: str
    link: str
    source: str
    published: datetime
    summary: str = ""


def load_portfolios(path: Path) -> list[PortfolioRow]:
    rows: list[PortfolioRow] = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"company", "analyst_name", "analyst_email"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                log.warning("Malformed portfolios.csv header; expected %s", sorted(required))
                return rows
            for number, raw in enumerate(reader, 2):
                values = {key: (raw.get(key) or "").strip() for key in required}
                if not all(values.values()) or "@" not in values["analyst_email"]:
                    log.warning("Skipping malformed portfolios.csv row %d: %r", number, raw)
                    continue
                rows.append(PortfolioRow(**values))
    except (OSError, csv.Error) as exc:
        log.warning("Could not read portfolios.csv: %s", exc)
    return rows


def dedup_key(source: str, title: str) -> str:
    """The sole key function used by both the check and save paths."""
    headline = SEPARATORS.split(title.strip(), maxsplit=1)[0]
    normalized = re.sub(r"\s+", " ", f"{source}: {headline}".lower()).strip()[:120]
    return hashlib.sha256(normalized.encode()).hexdigest()


def parse_date(entry: Any) -> datetime | None:
    value = entry.get("published") or entry.get("updated")
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
        return result.replace(tzinfo=result.tzinfo or UTC).astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def first_two(company: str) -> str:
    return " ".join(company.lower().split()[:2])


def clean_summary(value: str) -> str:
    text = BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return (text[:397] + "...") if len(text) > 400 else text


class Fetcher:
    def __init__(self, config: dict[str, Any], companies: list[str], now: datetime):
        self.config, self.companies, self.now = config, companies, now
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def _request_feed(self, url: str) -> list[Any]:
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            return parse_feed(response.content)
        except (requests.RequestException, ElementTree.ParseError, ValueError) as exc:
            log.warning("Feed request failed for %s: %s", url, exc)
            return []

    def google(self) -> list[NewsItem]:
        found: list[NewsItem] = []
        consecutive_empty = 0
        for company in self.companies:
            query = f"{' '.join(company.split()[:2])} India finance when:2d"
            url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-IN&gl=IN&ceid=IN:en"
            entries = self._request_feed(url)
            consecutive_empty = consecutive_empty + 1 if not entries else 0
            for entry in entries:
                published = parse_date(entry)
                if not published or published < self.now - timedelta(hours=48) or published > self.now + timedelta(hours=1):
                    continue
                source = (entry.get("source") or {}).get("title") or "Google News"
                found.append(NewsItem(company, entry.get("title", "").strip(), entry.get("link", ""), source, published, clean_summary(entry.get("summary", ""))))
            if consecutive_empty >= 2:
                log.warning("Google returned %d consecutive empty feeds; backing off", consecutive_empty)
                time.sleep(float(self.config.get("google_empty_backoff_seconds", 8)))
            time.sleep(float(self.config.get("google_request_delay_seconds", 1)))
        return found

    def shared_feed(self, name: str, exchange: bool = False) -> list[NewsItem]:
        entries: list[Any] = []
        for url in self.config.get("source_urls", {}).get(name, []):
            entries = self._request_feed(url)
            if entries:
                break
            log.warning("Source URL returned zero items: %s (%s)", name, url)
        found: list[NewsItem] = []
        for entry in entries:
            published = parse_date(entry)
            if not published or published < self.now - timedelta(hours=48):
                continue
            title = entry.get("title", "").strip()
            summary = clean_summary(entry.get("summary", ""))
            haystack = f"{title} {summary}".lower()
            if exchange and JUNK.search(haystack) and not KEEP.search(haystack):
                continue
            for company in self.companies:
                if first_two(company) in haystack:
                    found.append(NewsItem(company, title, entry.get("link", ""), name.replace("_", " ").title(), published, summary))
        return found

    def all(self) -> list[NewsItem]:
        items: list[NewsItem] = []
        enabled = self.config.get("sources", {})
        for name in ("google_news", "rbi_press_releases", "rbi_notifications", "sebi", "nse_announcements", "bse_announcements"):
            if not enabled.get(name, False):
                continue
            batch = self.google() if name == "google_news" else self.shared_feed(name, name in {"nse_announcements", "bse_announcements"})
            log.info("SOURCE_COUNT source=%s items=%d", name, len(batch))
            if not batch:
                log.warning("ZERO_SOURCE_ITEMS source=%s", name)
            items.extend(batch)
        return items


def parse_feed(content: bytes) -> list[dict[str, Any]]:
    """Parse RSS/Atom bytes already fetched with our browser user agent."""
    root = ElementTree.fromstring(content)
    parsed: list[dict[str, Any]] = []
    nodes = list(root.iter("item"))
    if not nodes:
        nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "entry"]
    for node in nodes:
        values: dict[str, Any] = {}
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "link":
                values["link"] = child.attrib.get("href") or (child.text or "").strip()
            elif tag == "source":
                values["source"] = {"title": (child.text or "").strip()}
            elif tag in {"title", "description", "summary", "published", "updated", "pubDate"}:
                mapped = {"description": "summary", "pubDate": "published"}.get(tag, tag)
                values[mapped] = "".join(child.itertext()).strip()
        parsed.append(values)
    return parsed


def load_seen(path: Path, now: datetime) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        raw = {}
    cutoff = now - timedelta(days=30)
    return {key: value for key, value in raw.items() if _iso(value) and _iso(value) >= cutoff}


def _iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError):
        return None


def plain_html(name: str, grouped: dict[str, list[NewsItem]], edit_url: str, fallback: bool = False) -> str:
    blocks = [f"<h1>Portfolio News — {html.escape(name)}</h1>"]
    if fallback:
        blocks.append("<p><em>Claude formatting was unavailable; this is the plain-mode report.</em></p>")
    if not grouped:
        blocks.append("<p>No new developments for your portfolio today.</p>")
    for company, items in grouped.items():
        blocks.append(f"<h2>{html.escape(company)}</h2><ul>")
        for item in items:
            summary = f"<br>{html.escape(item.summary)}" if item.summary else ""
            blocks.append(f'<li><a href="{html.escape(item.link, quote=True)}"><strong>{html.escape(item.title)}</strong></a>{summary}<br><small>{html.escape(item.source)} · {item.published:%d %b %Y, %H:%M UTC}</small></li>')
        blocks.append("</ul>")
    blocks.append(f'<hr><small>Manage this watchlist by <a href="{html.escape(edit_url, quote=True)}">editing portfolios.csv on GitHub</a>.</small>')
    return "<!doctype html><html><body>" + "".join(blocks) + "</body></html>"


def claude_html(name: str, grouped: dict[str, list[NewsItem]], config: dict[str, Any]) -> str:
    import anthropic
    payload = [{"company": company, "items": [vars(item) | {"published": item.published.isoformat()} for item in items]} for company, items in grouped.items()]
    prompt = """Create a concise HTML portfolio-news report with top takeaways, grouped by company. For each item include headline/link, 1-2 line summary, source/date, and one-line credit implication. Judge the underlying event date from the supplied content, not the article publication date. Exclude an item if its underlying event is older than 48 hours. Never include an undated item using a 'recent' hedge. Return HTML body content only. Data:\n""" + json.dumps(payload)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    text_blocks: list[str] = []
    with client.messages.stream(model=config["claude_model"], max_tokens=4000, messages=[{"role": "user", "content": prompt}]) as stream:
        message = stream.get_final_message()
    for block in message.content:
        if getattr(block, "type", None) == "text":
            text_blocks.append(block.text)
    if not text_blocks:
        raise RuntimeError("Claude returned no text blocks")
    return "".join(text_blocks)


def send_email(to: str, cc: list[str], subject: str, body: str) -> None:
    user, password = os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"]
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = user, to, subject
    if cc:
        message["Cc"] = ", ".join(cc)
    message.set_content("This report requires an HTML-capable email client.")
    message.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(message)


def run(root: Path = ROOT, dry_run: bool = False, force: bool = False) -> int:
    config = json.loads((root / "config.json").read_text())
    rows = load_portfolios(root / "portfolios.csv")
    if not rows:
        log.error("No valid portfolio rows; refusing to send")
        return 1
    now = datetime.now(UTC)
    today_ist = (now + timedelta(hours=5, minutes=30)).date().isoformat()
    marker_path = root / "data/last_sent.json"
    try:
        marker = json.loads(marker_path.read_text())
    except (OSError, json.JSONDecodeError):
        marker = {}
    if marker.get("date_ist") == today_ist and not force:
        log.info("Already sent for IST date %s; exiting", today_ist)
        return 0
    companies = list(dict.fromkeys(row.company for row in rows))
    fetched = Fetcher(config, companies, now).all()
    seen_path = root / "data/seen_headlines.json"
    seen = load_seen(seen_path, now)
    fresh: list[NewsItem] = []
    run_keys: set[str] = set()
    for item in fetched:
        key = dedup_key(item.source, item.title)
        if key not in seen and key not in run_keys and item.title and item.link:
            fresh.append(item)
            run_keys.add(key)
    by_company: dict[str, list[NewsItem]] = defaultdict(list)
    for item in fresh:
        by_company[item.company].append(item)
    analysts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        analysts[(row.analyst_name, row.analyst_email)].add(row.company)
    for (name, email), owned in analysts.items():
        grouped = {company: by_company[company] for company in owned if by_company[company]}
        count = sum(map(len, grouped.values()))
        log.info("ANALYST_COUNT analyst=%s email=%s items=%d", name, email, count)
        if not grouped and not config.get("send_empty_portfolio_email", True):
            continue
        fallback = False
        if config.get("claude_mode") and grouped:
            try:
                body = claude_html(name, grouped, config)
                body += f'<hr><small><a href="{html.escape(config["repository_edit_url"], quote=True)}">Edit portfolios.csv on GitHub</a></small>'
            except Exception as exc:
                # Includes Anthropic's insufficient-credit HTTP 400; delivery must continue.
                log.warning("Claude formatting failed (%s); using plain mode", exc)
                fallback = True
                body = plain_html(name, grouped, config["repository_edit_url"], fallback)
        else:
            body = plain_html(name, grouped, config["repository_edit_url"], fallback)
        if dry_run:
            log.info("DRY_RUN would send to=%s cc=%s", email, config.get("cc_all", []))
        else:
            send_email(email, config.get("cc_all", []), f"Portfolio News — {name} — {today_ist}", body)
    if not dry_run:
        for item in fresh:
            seen[dedup_key(item.source, item.title)] = now.isoformat()
        seen_path.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
        marker_path.write_text(json.dumps({"date_ist": today_ist, "sent_at_utc": now.isoformat()}, indent=2) + "\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="fetch and render without SMTP or state changes")
    parser.add_argument("--force", action="store_true", help="ignore today's sent marker")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
