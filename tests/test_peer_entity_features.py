import sqlite3

from webapp.queries import (
    dashboard_stats,
    filter_entities,
    peer_rating_matrix,
    peer_risk_flags,
)


def test_peer_risk_flags_marks_unverified_and_thresholds():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("CREATE TABLE deltas (entity_id INTEGER, materiality TEXT);")
    conn.execute("INSERT INTO deltas VALUES (1, 'high')")
    flags = peer_risk_flags(conn, [{
        "entity_id": 1,
        "entity": "Demo NBFC",
        "basis": "standalone",
        "verified": "Unverified",
        "gnpa_pct": 6.2,
        "car_pct": 16.5,
        "pat_cr": -10,
    }])
    assert flags[0]["status"] == "Watch"
    assert "Unverified financials" in flags[0]["issues"]
    assert "GNPA ≥ 5%" in flags[0]["issues"]
    assert "CAR < 18%" in flags[0]["issues"]
    assert "Loss-making" in flags[0]["issues"]
    assert "1 high-materiality change(s)" in flags[0]["issues"]


def test_peer_rating_matrix_returns_placeholder_without_ratings():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("CREATE TABLE snapshots (id INTEGER, entity_id INTEGER, agency TEXT, doc_type TEXT, snapshot_json TEXT, dedupe_hash TEXT); CREATE TABLE raw_items (dedupe_hash TEXT, published_on TEXT);")
    rows = peer_rating_matrix(conn, [999])
    assert rows[0]["entity"] == "entity_id=999"
    assert rows[0]["rating"] == "—"


def test_entity_directory_filters_large_master():
    banks = filter_entities(query="karnataka", sector="Bank")
    assert any(row["legal_name"] == "Karnataka Bank Limited" for row in banks)
    hfc = filter_entities(sub_sector="housing_finance")
    assert any(row["legal_name"] == "LIC Housing Finance Limited" for row in hfc)


def test_dashboard_stats_are_safe_and_count_material_items():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE raw_items (published_on TEXT);
        CREATE TABLE deltas (materiality TEXT);
        CREATE TABLE review_queue (status TEXT);
        INSERT INTO raw_items VALUES ('2026-08-01');
        INSERT INTO raw_items VALUES ('2026-08-02');
        INSERT INTO deltas VALUES ('high');
        INSERT INTO review_queue VALUES ('open');
    """)
    stats = dashboard_stats(conn)
    assert stats["entities"] == 356
    assert stats["documents"] == 2
    assert stats["high_changes"] == 1
    assert stats["open_reviews"] == 1
    assert stats["latest_update"] == "2026-08-02"
