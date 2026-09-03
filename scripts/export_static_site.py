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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "tracker.sqlite"
ENTITY_MASTER = ROOT / "data" / "entity_master.csv"
STYLE = ROOT / "webapp" / "static" / "style.css"
DEFAULT_OUT = ROOT / "docs"


def esc(value) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value))


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


def render_entity(entity: dict, deltas: list[dict]) -> str:
    cards = []
    for d in deltas:
        cards.append(
            f"""<div class="delta-card mat-{esc(d['materiality'] or 'low')}">
<div class="delta-head"><span class="date-dim">{esc(d['published_on'])}</span><span class="tag">{esc(d['agency'])}</span><span class="tag">{esc(d['doc_type'])}</span></div>
<div class="delta-note">{esc(d['delta_note'])}</div><div class="date-dim">source: {esc(d['title'])}</div></div>"""
        )
    return f"""
<h1>{esc(entity['display_name'])}</h1>
<div class="subtitle">{esc(entity['legal_name'])} · {esc(entity['sector'])} / {esc(entity['sub_sector'])}</div>
<div class="card">
  <b>CIN:</b> <span class="mono">{esc(entity.get('cin'))}</span><br>
  <b>BSE:</b> <span class="mono">{esc(entity.get('bse_code'))}</span><br>
  <b>NSE:</b> <span class="mono">{esc(entity.get('nse_symbol'))}</span>
</div>
<h2>Recent changes</h2>
{''.join(cards) if cards else '<div class="empty-note">No deltas found for this entity.</div>'}
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
        body = render_entity(entity, entity_deltas(conn, eid))
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
