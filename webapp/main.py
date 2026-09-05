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
from common.entity_profiles import entity_profile

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
        "stats": q.dashboard_stats(conn),
    })


@app.get("/entities")
def entities_directory(request: Request, query: str = "", sector: str = "",
                       sub_sector: str = "", page: int = 1):
    page_size = 50
    rows = q.filter_entities(query, sector, sub_sector)
    page_count = max(1, (len(rows) + page_size - 1) // page_size)
    page = min(max(page, 1), page_count)
    start = (page - 1) * page_size
    all_entities = q.load_entities()
    return templates.TemplateResponse(request, "entities.html", {
        "active": "entity",
        "entities": rows[start:start + page_size],
        "total": len(rows),
        "page": page,
        "page_count": page_count,
        "query": query,
        "sector": sector,
        "sub_sector": sub_sector,
        "sectors": sorted({e["sector"] for e in all_entities if e.get("sector")}),
        "sub_sectors": sorted({
            e["sub_sector"] for e in all_entities if e.get("sub_sector")
        }),
    })


@app.get("/entity/{entity_id}")
def entity_page(request: Request, entity_id: int, tab: str = "overview"):
    entities = {int(e["id"]): e for e in q.load_entities()}
    entity = entities.get(entity_id)
    if not entity:
        raise HTTPException(404, f"No entity_id={entity_id}")
    conn = q.get_conn()
    return templates.TemplateResponse(request, "entity.html", {
        "active": "entity", "entity": entity, "active_tab": tab,
        "entities": entities,
        "current_ratings": q.current_ratings(conn, entity_id),
        "timeline": q.rating_timeline(conn, entity_id),
        "financials": q.verified_financials(conn, entity_id),
        "deltas": q.entity_deltas(conn, entity_id),
        "documents": q.entity_documents(conn, entity_id),
        "entity_reviews": q.entity_review_items(conn, entity_id),
        "news_events": q.entity_news_events(conn, entity_id),
        "profile": entity_profile(entity_id),
    })


@app.get("/compare")
def compare(request: Request, entities: str = ""):
    all_entities = q.load_entities()
    ids = [int(x) for x in entities.split(",") if x.strip()] or [1, 2, 3]
    columns = build_columns(ids)
    conn = q.get_conn()
    return templates.TemplateResponse(request, "compare.html", {
        "active": "compare",
        "all_entities": all_entities, "selected_ids": ids,
        "metrics": METRIC_LABELS,
        "columns": columns,
        "rating_matrix": q.peer_rating_matrix(conn, ids),
        "risk_flags": q.peer_risk_flags(conn, columns),
    })


@app.get("/compare/download")
def compare_download(entities: str = ""):
    ids = [int(x) for x in entities.split(",") if x.strip()] or [1, 2, 3]
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
        "review_items": q.review_queue_items(conn),
        "trace_failures": q.review_queue_items(conn, reason="figure_trace_failed"),
        "canonical_mismatches": q.review_queue_items(conn, reason="entity_mismatch"),
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


@app.post("/review/resolve/{review_id}")
def review_resolve_one(review_id: int):
    conn = q.get_conn()
    q.resolve_review_item(conn, review_id)
    return RedirectResponse("/review", status_code=303)


@app.get("/source/{subpath:path}")
def source_file(subpath: str):
    target = (q.PDF_ROOT / subpath).resolve()
    if not str(target).startswith(str(q.PDF_ROOT)) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)
