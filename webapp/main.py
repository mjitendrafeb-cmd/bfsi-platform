"""Stage E — BFSI Intelligence Platform web app (local-only, read-mostly).

    python run_webapp.py

Serves the existing db/tracker.sqlite through four screens: Dashboard,
Entity pages, Peer Comparison (reuses pipeline.compare verbatim), and a
Review Queue whose only write path is marking a financials row verified
(the same UPDATE pipeline.verify's CLI performs) or filing/reprocessing
decisions a human makes about a flagged item — nothing here re-derives
or re-grades data on its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from webapp import queries as q
from pipeline.compare import build_columns, write_excel, METRIC_LABELS

app = FastAPI(title="BFSI Intelligence Platform")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

MATERIALITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@app.get("/")
def root():
    return RedirectResponse("/dashboard")


@app.get("/dashboard")
def dashboard(request: Request):
    conn = q.get_conn()
    deltas = q.recent_deltas(conn)
    return templates.TemplateResponse(request, "dashboard.html", {
        "active": "dashboard", "deltas": deltas,
    })


@app.get("/entity/{entity_id}")
def entity_page(request: Request, entity_id: int):
    entities = {int(e["id"]): e for e in q.load_entities()}
    entity = entities.get(entity_id)
    if not entity:
        raise HTTPException(404, f"No entity_id={entity_id}")
    conn = q.get_conn()
    return templates.TemplateResponse(request, "entity.html", {
        "active": "entity", "entity": entity,
        "entities": entities,
        "current_ratings": q.current_ratings(conn, entity_id),
        "timeline": q.rating_timeline(conn, entity_id),
        "financials": q.verified_financials(conn, entity_id),
        "deltas": q.entity_deltas(conn, entity_id),
    })


@app.get("/compare")
def compare(request: Request, entities: str = ""):
    all_entities = q.load_entities()
    ids = [int(x) for x in entities.split(",") if x.strip()] or [int(e["id"]) for e in all_entities]
    columns = build_columns(ids)
    return templates.TemplateResponse(request, "compare.html", {
        "active": "compare",
        "all_entities": all_entities, "selected_ids": ids,
        "metrics": METRIC_LABELS,
        "columns": columns,
    })


@app.get("/compare/download")
def compare_download(entities: str = ""):
    all_ids = [int(e["id"]) for e in q.load_entities()]
    ids = [int(x) for x in entities.split(",") if x.strip()] or all_ids
    columns = build_columns(ids)
    if not columns:
        raise HTTPException(404, "No financials data to export for the selected entities.")
    out_path = write_excel(columns, ids)
    return FileResponse(out_path, filename=out_path.name,
                         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/review")
def review(request: Request):
    conn = q.get_conn()
    return templates.TemplateResponse(request, "review.html", {
        "active": "review",
        "unverified": q.unverified_financials(conn),
        "mismatches": q.flagged_raw_items(conn, status=4),
        "needs_ocr": q.flagged_raw_items(conn, status=2),
        "extract_failed": q.flagged_raw_items(conn, status=3),
    })


@app.post("/review/verify/{financials_id}")
def review_verify_one(financials_id: int):
    conn = q.get_conn()
    q.mark_financials_verified(conn, [financials_id])
    return RedirectResponse("/review", status_code=303)


@app.post("/review/verify-all")
def review_verify_all():
    conn = q.get_conn()
    ids = [row["id"] for row in q.unverified_financials(conn)]
    q.mark_financials_verified(conn, ids)
    return RedirectResponse("/review", status_code=303)


@app.get("/source/{subpath:path}")
def source_file(subpath: str):
    target = (q.PDF_ROOT / subpath).resolve()
    if not str(target).startswith(str(q.PDF_ROOT)) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)
