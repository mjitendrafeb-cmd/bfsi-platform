import json
import sqlite3

from pipeline.process import DDL, _record_review_item, _record_qc_trace_failures
from webapp.queries import review_queue_items


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return conn


def test_record_review_item_dedupes_open_items():
    conn = _conn()
    assert _record_review_item(
        conn,
        entity_id=1,
        item_type="raw_item",
        item_id="abc",
        reason="entity_mismatch",
        payload={"doc_name": "Wrong Co"},
    )
    assert not _record_review_item(
        conn,
        entity_id=1,
        item_type="raw_item",
        item_id="abc",
        reason="entity_mismatch",
        payload={"doc_name": "Wrong Co"},
    )
    assert conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0] == 1


def test_qc_trace_failures_create_review_item():
    conn = _conn()
    count = _record_qc_trace_failures(
        conn,
        entity_id=1,
        dedupe_hash="hash1",
        snapshot_id=42,
        schema_key="quarterly_results",
        text="PAT was 120.0 crore",
        snap={"entity_name": "Spandana Sphoorty", "pat_cr": 123.4},
    )
    assert count == 1
    row = conn.execute("SELECT reason, payload_json FROM review_queue").fetchone()
    assert row["reason"] == "figure_trace_failed"
    payload = json.loads(row["payload_json"])
    assert payload["failures"][0]["field"] == "pat_cr"


def test_review_queue_items_parses_payload():
    conn = _conn()
    _record_review_item(
        conn,
        entity_id=1,
        item_type="snapshot",
        item_id="42",
        reason="figure_trace_failed",
        payload={"failures": [{"field": "pat_cr", "value": 123.4}]},
    )
    items = review_queue_items(conn, reason="figure_trace_failed")
    assert len(items) == 1
    assert items[0]["payload"]["failures"][0]["field"] == "pat_cr"
