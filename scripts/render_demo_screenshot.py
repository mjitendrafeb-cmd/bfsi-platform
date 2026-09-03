"""Render a lightweight PNG screenshot of the static demo dashboard.

This is a dependency-light fallback for environments without a browser. It uses
Pillow to draw the same dashboard content from SQLite into
`docs/demo_screenshot.png` for sharing in PRs/chat.
"""
from __future__ import annotations

import csv
import sqlite3
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "tracker.sqlite"
ENTITY_MASTER = ROOT / "data" / "entity_master.csv"
OUT = ROOT / "docs" / "demo_screenshot.png"
ENTITIES_OUT = ROOT / "docs" / "entities_screenshot.png"

BG = "#141310"
DEEP = "#0f0e0c"
PANEL = "#1d1b17"
PANEL2 = "#25221d"
BORDER = "#3a352d"
TEXT = "#eee9de"
DIM = "#928a7c"
ACCENT = "#c09a5b"
HIGH = "#e36d62"
MED = "#d5a54e"
LOW = "#71ae83"


def font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def entity_names() -> dict[int, str]:
    with open(ENTITY_MASTER, newline="", encoding="utf-8-sig") as f:
        return {int(r["id"]): r["display_name"] for r in csv.DictReader(f)}


def entities() -> list[dict[str, str]]:
    with open(ENTITY_MASTER, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def rows(limit: int = 4) -> list[dict]:
    if not DB.exists():
        return []
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    names = entity_names()
    try:
        data = conn.execute(
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
    except sqlite3.Error:
        return []
    return [{**dict(r), "entity": names.get(r["entity_id"], f"entity_id={r['entity_id']}")} for r in data]


def pill(draw, xy, text, fill, outline=BORDER, fnt=None):
    fnt = fnt or font(14)
    x, y = xy
    bbox = draw.textbbox((x, y), text, font=fnt)
    w = bbox[2] - bbox[0] + 20
    h = bbox[3] - bbox[1] + 10
    draw.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=PANEL2, outline=outline)
    draw.text((x + 10, y + 5), text, fill=fill, font=fnt)
    return w


def shell(draw, active: str, width: int) -> None:
    """Draw the warm graphite sidebar/topbar shared by demo screenshots."""
    draw.rectangle((0, 0, 248, 1050), fill=DEEP)
    draw.line((248, 0, 248, 1050), fill="#2b2822")
    draw.ellipse((24, 22, 62, 60), outline=ACCENT, width=1)
    draw.text((33, 32), "CI", fill="#dab879", font=font(13, True))
    draw.text((74, 25), "Credit Intelligence", fill=TEXT, font=font(15, True))
    draw.text((74, 46), "BFSI SURVEILLANCE", fill=DIM, font=font(8))
    draw.text((28, 98), "WORKSPACE", fill="#70695d", font=font(8, True))
    for i, label in enumerate(("Dashboard", "Entities", "Peer comparison", "Review queue")):
        y = 120 + i * 48
        if label == active:
            draw.rounded_rectangle((16, y, 232, y + 39), radius=7, fill="#302719", outline="#4b3d27")
        draw.text((32, y + 12), label, fill="#dab879" if label == active else DIM, font=font(11))
    draw.line((16, 968, 232, 968), fill="#2b2822")
    draw.ellipse((28, 991, 35, 998), fill=LOW)
    draw.text((46, 983), "Local workspace", fill=TEXT, font=font(9))
    draw.text((46, 1001), "SOURCE-LINKED · QC ENABLED", fill=DIM, font=font(7))
    draw.rectangle((249, 0, width, 62), fill=BG)
    draw.line((249, 62, width, 62), fill="#2b2822")
    draw.ellipse((280, 28, 287, 35), fill=LOW)
    draw.text((298, 24), "SURVEILLANCE WORKSPACE", fill=DIM, font=font(8))
    draw.text((width - 120, 24), "LOCAL · SQLITE", fill=DIM, font=font(8))


def render() -> Path:
    W, H = 1440, 1050
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f12, f14, f16, f18, f24 = font(12), font(14), font(16), font(18, True), font(28, True)

    shell(d, "Dashboard", W)
    d.text((290, 92), "DAILY CREDIT INTELLIGENCE", fill=ACCENT, font=font(8, True))
    d.text((290, 112), "Surveillance Desk", fill=TEXT, font=f24)
    d.text((290, 151), "Material rating, financial and filing changes across the tracked BFSI universe.", fill=DIM, font=f12)

    stats = [("TRACKED ENTITIES", "356", "3 priority names"), ("SOURCE DOCUMENTS", "479", "Deduplicated collection"),
             ("HIGH-MATERIALITY", "18", "Across available history"), ("OPEN REVIEWS", "4", "Awaiting analyst action")]
    sx = 290
    for idx, (label, value, note) in enumerate(stats):
        sw = 252
        d.rounded_rectangle((sx, 190, sx + sw, 306), radius=8, fill=PANEL, outline="#2b2822")
        d.text((sx + 17, 208), label, fill=DIM, font=font(8, True))
        d.text((sx + 17, 235), value, fill=HIGH if idx == 2 else (MED if idx == 3 else TEXT), font=font(25, True))
        d.text((sx + 17, 280), note, fill=DIM, font=font(8))
        sx += sw + 12

    d.text((290, 344), "CHANGE FEED", fill=ACCENT, font=font(8, True))
    d.text((290, 362), "Recent credit developments", fill=TEXT, font=f18)
    d.line((290, 395, 1140, 395), fill="#2b2822")

    y = 414
    data = rows()
    if not data:
        data = [{"entity": "Demo Entity", "published_on": "—", "agency": "demo", "doc_type": "rating_rationale", "materiality": "low", "delta_note": "No delta notes found in the local database.", "title": "—"}]
    colors = {"high": HIGH, "medium": MED, "low": LOW}
    for r in data:
        mat = (r.get("materiality") or "low").lower()
        c = colors.get(mat, LOW)
        card_h = 176
        d.rounded_rectangle((290, y, 1140, y + card_h), radius=9, fill=PANEL, outline="#2b2822")
        d.rectangle((290, y, 294, y + card_h), fill=c)
        d.text((314, y + 17), f"{str(r.get('doc_type') or '—').replace('_',' ').upper()} · {str(r.get('agency') or '—').upper()}", fill=DIM, font=font(8))
        d.text((314, y + 38), str(r.get("entity") or "—"), fill=TEXT, font=f18)
        d.text((1000, y + 20), str(r.get("published_on") or "—"), fill=DIM, font=font(9))
        pill(d, (1050, y + 40), mat.upper(), c, outline=c, fnt=font(8))
        note = str(r.get("delta_note") or "")
        lines = textwrap.wrap(note, width=105)[:3]
        ty = y + 77
        for line in lines:
            d.text((314, ty), line, fill="#c8c0b1", font=font(10))
            ty += 17
        d.text((314, y + card_h - 25), f"View source · {r.get('title') or '—'}"[:115], fill=ACCENT, font=font(8))
        y += card_h + 12
        if y > 1000:
            break

    d.rounded_rectangle((1162, 344, 1400, 575), radius=9, fill=PANEL, outline="#2b2822")
    d.text((1182, 364), "MATERIALITY GUIDE", fill=ACCENT, font=font(8, True))
    d.text((1182, 386), "Credit signal", fill=TEXT, font=f16)
    for iy, (label, note, color) in enumerate((("High", "Rating, capital or asset quality", HIGH), ("Medium", "Monitor next review cycle", MED), ("Low", "Informational update", LOW))):
        ly = 426 + iy * 48
        d.ellipse((1183, ly + 3, 1191, ly + 11), fill=color)
        d.text((1205, ly), label, fill=TEXT, font=font(10, True))
        d.text((1205, ly + 18), note, fill=DIM, font=font(7))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"Wrote {OUT}")
    return OUT


def render_entity_directory() -> Path:
    """Render the scalable entity-directory view for demo feedback."""
    width, height = 1440, 1050
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    f12, f14, f16, f18, f24 = font(12), font(14), font(16), font(18, True), font(28, True)
    shell(draw, "Entities", width)

    all_entities = entities()
    draw.text((290, 94), "ENTITY MASTER", fill=ACCENT, font=font(8, True))
    draw.text((290, 114), "Entities", fill=TEXT, font=f24)
    draw.text((290, 153), f"{len(all_entities)} tracked BFSI entities · searchable by legal name, alias or identifier", fill=DIM, font=f12)

    # Filter controls
    controls = [(290, 190, 700, "Search name, alias, BSE or NSE symbol"),
                (714, 190, 920, "All sectors"), (934, 190, 1160, "All sub-sectors")]
    for x1, y1, x2, label in controls:
        draw.rounded_rectangle((x1, y1, x2, y1 + 42), radius=6, fill=PANEL, outline=BORDER)
        draw.text((x1 + 12, y1 + 13), label, fill=DIM, font=f12)
    draw.rounded_rectangle((1174, 190, 1264, 232), radius=6, fill=ACCENT)
    draw.text((1195, 204), "Filter", fill=DEEP, font=f12)

    y = 260
    headers = [(300, "Name"), (760, "Sector"), (950, "Sub-sector"), (1160, "Listed"), (1260, "Priority")]
    for hx, label in headers:
        draw.text((hx, y), label.upper(), fill=DIM, font=f12)
    y += 30
    for row in sorted(all_entities, key=lambda item: item["display_name"].casefold())[:15]:
        draw.line((290, y + 47, width - 40, y + 47), fill="#2b2822")
        draw.text((300, y + 5), row["display_name"][:48], fill=TEXT, font=f14)
        draw.text((300, y + 27), row["legal_name"][:64], fill=DIM, font=font(9))
        draw.text((760, y + 15), row["sector"] or "—", fill="#c8c0b1", font=f12)
        draw.text((950, y + 15), row["sub_sector"] or "—", fill="#c8c0b1", font=f12)
        listed = "Yes" if row["listed"] == "TRUE" else ("No" if row["listed"] == "FALSE" else "—")
        draw.text((1160, y + 15), listed, fill="#c8c0b1", font=f12)
        draw.text((1285, y + 15), row["priority_tier"] or "—", fill="#c8c0b1", font=f12)
        y += 48

    draw.text((805, height - 34), "Page 1 of 8", fill=DIM, font=f12)
    ENTITIES_OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(ENTITIES_OUT)
    print(f"Wrote {ENTITIES_OUT}")
    return ENTITIES_OUT


if __name__ == "__main__":
    render()
    render_entity_directory()
