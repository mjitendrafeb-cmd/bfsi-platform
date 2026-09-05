"""Export a read-only static demo site for GitHub Pages or file sharing.

This is deliberately dependency-free: it reads the local SQLite database and
CSV entity master directly, copies the existing CSS, and writes static HTML to
`docs/`. Static exports are for demo/feedback only; review approvals,
ingestion, AI processing, and SQLite writes still require the FastAPI app.

Usage:
    python scripts/export_static_site.py
    python scripts/export_static_site.py --out docs-demo
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.entity_profiles import entity_profile

DB = ROOT / "db" / "tracker.sqlite"
ENTITY_MASTER = ROOT / "data" / "entity_master.csv"
STYLE = ROOT / "webapp" / "static" / "style.css"
DEFAULT_OUT = ROOT / "docs"

METRIC_LABELS = [
    ("aum_cr", "AUM (Rs cr)"),
    ("total_income_cr", "Total Income (Rs cr)"),
    ("pat_cr", "PAT (Rs cr)"),
    ("gnpa_pct", "GNPA %"),
    ("nnpa_pct", "NNPA %"),
    ("car_pct", "CAR %"),
    ("networth_cr", "Net Worth (Rs cr)"),
    ("borrowings_cr", "Borrowings (Rs cr)"),
]


def esc(value) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value))


def public_source_url(value: str | None) -> str | None:
    """Allow only web links in the public export; omit local/private paths."""
    if not value:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def load_entities() -> list[dict]:
    with open(ENTITY_MASTER, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def connect() -> sqlite3.Connection | None:
    if not DB.exists():
        return None
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def entity_names(entities: list[dict]) -> dict[int, str]:
    return {int(e["id"]): e["display_name"] for e in entities}


def recent_deltas(conn: sqlite3.Connection | None, names: dict[int, str], limit: int = 40) -> list[dict]:
    if conn is None or not all(table_exists(conn, t) for t in ("deltas", "snapshots", "raw_items")):
        return []
    rows = conn.execute(
        """
        SELECT d.entity_id, d.doc_type, d.agency, d.materiality, d.delta_note,
               r.published_on, r.title
        FROM deltas d
        JOIN snapshots s ON s.id = d.new_snapshot_id
        JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
        ORDER BY r.published_on DESC, d.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "entity_id": r["entity_id"],
            "entity": names.get(r["entity_id"], f"entity_id={r['entity_id']}"),
            "date": r["published_on"],
            "agency": r["agency"],
            "doc_type": r["doc_type"],
            "materiality": r["materiality"] or "low",
            "note": r["delta_note"],
            "title": r["title"],
        }
        for r in rows
    ]


def entity_snapshot_counts(conn: sqlite3.Connection | None) -> dict[int, int]:
    if conn is None or not table_exists(conn, "snapshots"):
        return {}
    return {
        int(r["entity_id"]): int(r["n"])
        for r in conn.execute(
            "SELECT entity_id, COUNT(*) AS n FROM snapshots GROUP BY entity_id"
        ).fetchall()
        if r["entity_id"] is not None
    }


def review_counts(conn: sqlite3.Connection | None) -> dict[str, int]:
    if conn is None or not table_exists(conn, "review_queue"):
        return {}
    return {
        r["reason"] or "unknown": int(r["n"])
        for r in conn.execute(
            "SELECT reason, COUNT(*) AS n FROM review_queue WHERE status='open' GROUP BY reason"
        ).fetchall()
    }


def entity_deltas(conn: sqlite3.Connection | None, entity_id: int, limit: int = 30) -> list[dict]:
    if conn is None or not all(table_exists(conn, t) for t in ("deltas", "snapshots", "raw_items")):
        return []
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT d.doc_type, d.agency, d.materiality, d.delta_note,
                   r.published_on, r.title
            FROM deltas d
            JOIN snapshots s ON s.id = d.new_snapshot_id
            JOIN raw_items r ON r.dedupe_hash = s.dedupe_hash
            WHERE d.entity_id=?
            ORDER BY r.published_on DESC, d.id DESC
            LIMIT ?
            """,
            (entity_id, limit),
        ).fetchall()
    ]


def rating_timeline(conn: sqlite3.Connection | None, entity_id: int) -> list[dict]:
    """Return rating rationales and informational credit updates newest first."""
    if conn is None or not all(table_exists(conn, t) for t in ("snapshots", "raw_items")):
        return []
    rows = conn.execute(
        """
        SELECT s.agency, s.doc_type, s.snapshot_json,
               r.published_on, r.title, r.pdf_url
        FROM snapshots s
        JOIN raw_items r ON r.dedupe_hash=s.dedupe_hash
        WHERE s.entity_id=?
          AND s.doc_type IN ('rating_rationale', 'sf_rationale', 'credit_update')
        ORDER BY r.published_on DESC, s.id DESC
        """,
        (entity_id,),
    ).fetchall()
    timeline = []
    for row in rows:
        try:
            snapshot = json.loads(row["snapshot_json"] or "{}")
        except json.JSONDecodeError:
            snapshot = {}
        if row["doc_type"] == "credit_update":
            label = snapshot.get("subject") or row["title"] or "Credit update"
        else:
            instruments = snapshot.get("instruments") or snapshot.get("instrument_tranches") or []
            labels = []
            for instrument in instruments:
                rating = instrument.get("rating")
                if rating and rating not in labels:
                    labels.append(rating)
            label = "; ".join(labels) or row["title"] or "Rating rationale"
        timeline.append({
            "date": snapshot.get("rating_date") or snapshot.get("date") or row["published_on"],
            "agency": row["agency"], "kind": row["doc_type"], "label": label,
            "source_link": public_source_url(row["pdf_url"]),
        })
    return timeline


def entity_financials(conn: sqlite3.Connection | None, entity_id: int) -> list[dict]:
    """Return source-linked financial rows, retaining their verification state."""
    if conn is None or not table_exists(conn, "financials"):
        return []
    has_sources = all(table_exists(conn, t) for t in ("snapshots", "raw_items"))
    if has_sources:
        sql = """
            SELECT f.*, r.agency, r.title, r.pdf_url, r.published_on
            FROM financials f
            LEFT JOIN snapshots s ON s.id=f.source_snapshot_id
            LEFT JOIN raw_items r ON r.dedupe_hash=s.dedupe_hash
            WHERE f.entity_id=? ORDER BY f.period DESC, f.id DESC
        """
    else:
        sql = """
            SELECT f.*, NULL AS agency, NULL AS title, NULL AS pdf_url,
                   NULL AS published_on
            FROM financials f WHERE f.entity_id=? ORDER BY f.period DESC, f.id DESC
        """
    return [dict(row) for row in conn.execute(sql, (entity_id,)).fetchall()]


def entity_sources(conn: sqlite3.Connection | None, entity_id: int) -> list[dict]:
    if conn is None or not table_exists(conn, "raw_items"):
        return []
    rows = [dict(row) for row in conn.execute(
        """SELECT published_on, agency, doc_type, title, pdf_url, processed
           FROM raw_items WHERE entity_id=?
           ORDER BY published_on DESC, ingested_at DESC""",
        (entity_id,),
    ).fetchall()]
    for row in rows:
        row["pdf_url"] = public_source_url(row["pdf_url"])
    return rows


def peer_ids(entity: dict, entities: list[dict], limit: int = 3) -> list[int]:
    """Choose a deterministic static peer group, preferring the same sub-sector."""
    same_sub_sector = [
        row for row in entities
        if row["sub_sector"] == entity["sub_sector"] and row["id"] != entity["id"]
    ]
    same_sector = [
        row for row in entities
        if row["sector"] == entity["sector"] and row["id"] != entity["id"]
        and row not in same_sub_sector
    ]
    peers = [entity, *(same_sub_sector + same_sector)[:limit - 1]]
    return [int(row["id"]) for row in peers]


def peer_financials(conn: sqlite3.Connection | None, ids: list[int], names: dict[int, str]) -> list[dict]:
    """Select one latest financial row per peer for a compact static table."""
    columns = []
    for entity_id in ids:
        rows = entity_financials(conn, entity_id)
        if not rows:
            columns.append({"entity_id": entity_id, "entity": names[entity_id]})
            continue
        row = rows[0]
        columns.append({"entity_id": entity_id, "entity": names[entity_id], **row})
    return columns


def page(title: str, active: str, body: str, prefix: str = "") -> str:
    links = []
    for key, href, label in [
        ("dashboard", "index.html", "Dashboard"),
        ("entities", "entities.html", "Entities"),
        ("review", "review.html", "Review Queue"),
    ]:
        cls = "active" if active == key else ""
        icon = {"dashboard": "⌂", "entities": "◇", "review": "✓"}[key]
        links.append(
            f'<a href="{prefix}{href}" class="{cls}">'
            f'<span class="nav-icon">{icon}</span>{label}</a>'
        )
    nav = "".join(links)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&amp;family=Inter:wght@400;500;600&amp;family=Spectral:wght@500;600&amp;display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{prefix}static/style.css">
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand-lockup" href="{prefix}index.html"><span class="brand-mark">CI</span><span><b>Credit Intelligence</b><small>BFSI demo export</small></span></a>
      <div class="nav-label">Workspace</div><nav class="side-nav">{nav}</nav>
      <div class="sidebar-footer"><span class="status-dot"></span><span><b>Read-only demo</b><small>Static · Source-linked</small></span></div>
    </aside>
    <section class="workspace"><header class="topbar"><div class="topbar-context"><span class="live-dot"></span> Surveillance workspace</div><div class="asof">GitHub Pages demo</div></header><main>{body}</main></section>
  </div>
</body>
</html>
"""


def render_dashboard(deltas: list[dict], reviews: dict[str, int], entity_count: int) -> str:
    cards = []
    for d in deltas:
        cards.append(
            f"""<article class="delta-card mat-{esc(d['materiality'])}"><div class="materiality-rail"></div><div class="delta-content">
  <div class="delta-head">
    <div>
    <div class="change-kicker">{esc(d['doc_type']).replace('_', ' ')} · {esc(d['agency'])}</div>
    <a class="entity-link" href="entities/{esc(d['entity_id'])}.html">{esc(d['entity'])}</a>
    </div><div class="delta-meta">
    <span class="date-dim">{esc(d['date'])}</span>
    <span class="tag mat-{esc(d['materiality'])}">{esc(str(d['materiality']).upper())}</span>
    </div>
  </div>
  <div class="delta-note">{esc(d['note'])}</div>
  <div class="date-dim">source: {esc(d['title'])}</div>
</div></article>"""
        )
    review_line = ", ".join(f"{esc(k)}: {v}" for k, v in sorted(reviews.items())) or "No open QC review items."
    high_count = sum(1 for item in deltas if item["materiality"] == "high")
    review_count = sum(reviews.values())
    return f"""
<section class="page-heading"><div><div class="eyebrow">Daily credit intelligence</div><h1>Surveillance Desk</h1><p>Read-only static demo of material BFSI credit developments.</p></div></section>
<section class="stat-grid"><a class="stat-card" href="entities.html"><span>Tracked entities</span><strong>{entity_count}</strong><small>Entity master</small></a><div class="stat-card"><span>Recent events</span><strong>{len(deltas)}</strong><small>Latest static export</small></div><div class="stat-card alert"><span>High-materiality</span><strong>{high_count}</strong><small>In recent feed</small></div><a class="stat-card review" href="review.html"><span>Open reviews</span><strong>{review_count}</strong><small>Read-only summary</small></a></section>
<div class="section-heading"><div><div class="eyebrow">Change feed</div><h2>Recent credit developments</h2></div></div>
<div class="card"><b>QC summary:</b> {review_line}</div>{''.join(cards) if cards else '<div class="empty-note">No delta notes found in the local database.</div>'}
"""


def render_entities(entities: list[dict], counts: dict[int, int]) -> str:
    rows = []
    for e in entities:
        eid = int(e["id"])
        rows.append(
            f"""<tr>
<td><a class="entity-link" href="entities/{eid}.html">{esc(e['display_name'])}</a></td>
<td>{esc(e['sector'])}</td><td>{esc(e['sub_sector'])}</td>
<td class="mono">{esc(e.get('listed'))}</td><td class="mono">{counts.get(eid, 0)}</td>
</tr>"""
        )
    return f"""
<h1>Entities</h1>
<div class="subtitle">Pilot entity directory exported from entity_master.csv.</div>
<table class="data"><tr><th>Name</th><th>Sector</th><th>Sub-sector</th><th>Listed</th><th class="num">Snapshots</th></tr>{''.join(rows)}</table>
"""


def render_entity(entity: dict, deltas: list[dict], timeline: list[dict],
                  financials: list[dict], sources: list[dict],
                  peers: list[dict]) -> str:
    cards = []
    for d in deltas:
        cards.append(
            f"""<div class="delta-card mat-{esc(d['materiality'] or 'low')}">
<div class="delta-head"><span class="date-dim">{esc(d['published_on'])}</span><span class="tag">{esc(d['agency'])}</span><span class="tag">{esc(d['doc_type'])}</span></div>
<div class="delta-note">{esc(d['delta_note'])}</div><div class="date-dim">source: {esc(d['title'])}</div></div>"""
        )
    profile = entity_profile(int(entity["id"]))
    profile_html = ""
    if profile:
        business_lines = "".join(f"<li>{esc(item)}</li>" for item in profile["business_lines"])
        monitoring_focus = "".join(f"<li>{esc(item)}</li>" for item in profile["monitoring_focus"])
        profile_html = f"""<div class="card entity-profile">
  <div class="eyebrow">Business profile</div><p>{esc(profile['summary'])}</p>
  <div class="profile-grid"><div><h3>Business lines</h3><ul>{business_lines}</ul></div>
  <div><h3>Credit monitoring focus</h3><ul>{monitoring_focus}</ul></div></div>
  <a class="src-link" href="{esc(profile['website'])}" target="_blank" rel="noopener">source: {esc(profile['source_label'])}</a>
</div>"""
    profile_block = f"{profile_html}\n" if profile_html else ""

    timeline_rows = "".join(
        f"""<tr><td class="mono">{esc(item['date'])}</td><td>{esc(item['agency'])}</td>
<td><span class="tag">{esc(item['kind']).replace('_', ' ')}</span></td><td>{esc(item['label'])}</td>
<td>{f'<a class="src-link" href="{esc(item["source_link"])}" target="_blank" rel="noopener">source</a>' if item['source_link'] else '—'}</td></tr>"""
        for item in timeline
    )
    timeline_html = (
        f'<table class="data"><tr><th>Date</th><th>Agency</th><th>Event</th><th>Rating / update</th><th>Source</th></tr>{timeline_rows}</table>'
        if timeline_rows else '<div class="empty-note">No rating actions or credit updates on record.</div>'
    )

    financial_blocks = []
    for row in financials:
        cells = "".join(
            f'<div class="metric-cell"><div class="mlabel">{esc(label)}</div><div class="mvalue">{esc(row.get(key))}</div></div>'
            for key, label in METRIC_LABELS if row.get(key) is not None
        )
        source = f"{row.get('agency') or 'Source'} — {row.get('title') or 'document'}"
        source_html = (
            f'<a class="src-link" href="{esc(row["pdf_url"])}" target="_blank" rel="noopener">{esc(source)}</a>'
            if public_source_url(row.get("pdf_url")) else esc(source)
        )
        state = "Verified" if row.get("verified") else "Unverified"
        financial_blocks.append(
            f'<div class="card"><div class="delta-head"><span class="tag mono">{esc(row.get("period"))}</span>'
            f'<span class="tag">{esc(row.get("basis"))}</span><span class="tag {"mat-low" if row.get("verified") else "mat-medium"}">{state}</span></div>'
            f'<div class="metric-grid">{cells}</div><div class="date-dim">source: {source_html}</div></div>'
        )
    financials_html = "".join(financial_blocks) or '<div class="empty-note">No financial rows on record.</div>'

    source_status = {0: "Pending", 1: "Processed", 2: "Needs OCR", 3: "Extract failed", 4: "Entity mismatch"}
    source_rows = "".join(
        f"""<tr><td class="mono">{esc(item['published_on'])}</td><td>{esc(item['agency'])}</td>
<td>{esc(item['doc_type'])}</td><td>{esc(item['title'])}</td><td>{esc(source_status.get(item['processed'], item['processed']))}</td>
<td>{f'<a class="src-link" href="{esc(item["pdf_url"])}" target="_blank" rel="noopener">open source</a>' if item['pdf_url'] else '—'}</td></tr>"""
        for item in sources
    )
    sources_html = (
        f'<table class="data"><tr><th>Date</th><th>Agency</th><th>Type</th><th>Document</th><th>Status</th><th>Link</th></tr>{source_rows}</table>'
        if source_rows else '<div class="empty-note">No source documents on record.</div>'
    )

    peer_headers = "".join(f'<th><a href="{esc(peer["entity_id"])}.html">{esc(peer["entity"])}</a></th>' for peer in peers)
    peer_meta = "".join(f'<td class="mono">{esc(peer.get("period"))}</td>' for peer in peers)
    peer_metric_rows = "".join(
        f'<tr><td>{esc(label)}</td>{"".join(f"<td class=\"num\">{esc(peer.get(key))}</td>" for peer in peers)}</tr>'
        for key, label in METRIC_LABELS
    )
    peers_html = f'<table class="data"><tr><th>Metric</th>{peer_headers}</tr><tr><td>Latest period</td>{peer_meta}</tr>{peer_metric_rows}</table>'

    return f"""
<h1>{esc(entity['display_name'])}</h1>
<div class="subtitle">{esc(entity['legal_name'])} · {esc(entity['sector'])} / {esc(entity['sub_sector'])}</div>
{profile_block}<div class="card">
  <b>CIN:</b> <span class="mono">{esc(entity.get('cin'))}</span><br>
  <b>BSE:</b> <span class="mono">{esc(entity.get('bse_code'))}</span><br>
  <b>NSE:</b> <span class="mono">{esc(entity.get('nse_symbol'))}</span>
</div>
<h2>Recent changes</h2>
{''.join(cards) if cards else '<div class="empty-note">No deltas found for this entity.</div>'}
<h2>Ratings timeline &amp; credit updates</h2>
{timeline_html}
<h2>Financials</h2>
{financials_html}
<h2>Sources</h2>
{sources_html}
<h2>Peer comparison</h2>
<div class="subtitle">Latest available financial row for deterministic same-sub-sector peers, falling back to the same sector.</div>
{peers_html}
"""


def render_review(reviews: dict[str, int]) -> str:
    rows = "".join(f"<tr><td>{esc(reason)}</td><td class=\"mono\">{count}</td></tr>" for reason, count in sorted(reviews.items()))
    return f"""
<h1>Review Queue</h1>
<div class="subtitle">Static count-only view. Use the FastAPI app to approve or resolve items.</div>
<table class="data"><tr><th>Reason</th><th>Open items</th></tr>{rows or '<tr><td colspan="2">No open review items.</td></tr>'}</table>
"""


def export(out: Path) -> None:
    entities = load_entities()
    names = entity_names(entities)
    conn = connect()
    out.mkdir(parents=True, exist_ok=True)
    (out / "static").mkdir(exist_ok=True)
    (out / "entities").mkdir(exist_ok=True)
    if STYLE.exists():
        shutil.copy2(STYLE, out / "static" / "style.css")

    deltas = recent_deltas(conn, names)
    counts = entity_snapshot_counts(conn)
    reviews = review_counts(conn)

    (out / "index.html").write_text(
        page("Dashboard", "dashboard", render_dashboard(deltas, reviews, len(entities))),
        encoding="utf-8",
    )
    (out / "entities.html").write_text(page("Entities", "entities", render_entities(entities, counts)), encoding="utf-8")
    (out / "review.html").write_text(page("Review Queue", "review", render_review(reviews)), encoding="utf-8")
    for entity in entities:
        eid = int(entity["id"])
        ids = peer_ids(entity, entities)
        body = render_entity(
            entity, entity_deltas(conn, eid), rating_timeline(conn, eid),
            entity_financials(conn, eid), entity_sources(conn, eid),
            peer_financials(conn, ids, names),
        )
        (out / "entities" / f"{eid}.html").write_text(
            page(entity["display_name"], "entities", body, prefix="../"),
            encoding="utf-8",
        )
    print(f"Static demo exported to {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a read-only static demo site.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    export(args.out.resolve())


if __name__ == "__main__":
    main()
