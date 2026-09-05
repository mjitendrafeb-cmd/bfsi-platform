import json
import sqlite3

from scripts.export_static_site import (
    entity_financials,
    entity_sources,
    export,
    peer_financials,
    public_source_url,
    rating_timeline,
)


def test_static_export_includes_full_directory_and_valid_nested_links(tmp_path):
    out = tmp_path / "docs"
    export(out)
    directory = (out / "entities.html").read_text(encoding="utf-8")
    assert "Namdev Finvest" in directory
    assert "Karnataka Bank" in directory
    nested = (out / "entities" / "4.html").read_text(encoding="utf-8")
    assert 'href="../static/style.css"' in nested
    assert 'href="../index.html"' in nested
    mintifi = (out / "entities" / "5.html").read_text(encoding="utf-8")
    assert "Supply-chain finance" in mintifi
    assert "Credit monitoring focus" in mintifi
    assert "https://www.mintifi.com/" in mintifi
    for heading in (
        "Ratings timeline &amp; credit updates",
        "Financials",
        "Sources",
        "Peer comparison",
    ):
        assert heading in mintifi


def test_static_entity_sections_read_source_linked_data():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE raw_items (
            dedupe_hash TEXT, entity_id INTEGER, agency TEXT, doc_type TEXT,
            title TEXT, published_on TEXT, pdf_url TEXT, processed INTEGER,
            ingested_at TEXT
        );
        CREATE TABLE snapshots (
            id INTEGER, dedupe_hash TEXT, entity_id INTEGER, agency TEXT,
            doc_type TEXT, snapshot_json TEXT
        );
        CREATE TABLE financials (
            id INTEGER, entity_id INTEGER, period TEXT, basis TEXT,
            aum_cr REAL, total_income_cr REAL, pat_cr REAL, gnpa_pct REAL,
            nnpa_pct REAL, car_pct REAL, networth_cr REAL, borrowings_cr REAL,
            source_snapshot_id INTEGER, verified INTEGER
        );
    """)
    conn.execute(
        "INSERT INTO raw_items VALUES (?,?,?,?,?,?,?,?,?)",
        ("credit", 5, "CRISIL", "credit_update", "Liquidity update",
         "2026-08-01", "https://example.test/update.pdf", 1, "2026-08-01"),
    )
    conn.execute(
        "INSERT INTO snapshots VALUES (?,?,?,?,?,?)",
        (1, "credit", 5, "CRISIL", "credit_update",
         json.dumps({"date": "2026-08-01", "subject": "Liquidity position"})),
    )
    conn.execute(
        "INSERT INTO financials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (1, 5, "FY26", "standalone", 100.0, 20.0, 3.0, 2.0,
         1.0, 25.0, 30.0, 70.0, 1, 0),
    )

    timeline = rating_timeline(conn, 5)
    assert timeline[0]["kind"] == "credit_update"
    assert timeline[0]["source_link"] == "https://example.test/update.pdf"
    assert entity_financials(conn, 5)[0]["verified"] == 0
    assert entity_sources(conn, 5)[0]["title"] == "Liquidity update"
    peers = peer_financials(conn, [5, 6], {5: "Mintifi", 6: "Peer"})
    assert peers[0]["aum_cr"] == 100.0
    assert peers[1] == {"entity_id": 6, "entity": "Peer"}


def test_public_export_rejects_local_and_unsafe_source_links():
    assert public_source_url("https://example.test/report.pdf")
    assert public_source_url("file:///private/report.pdf") is None
    assert public_source_url("C:\\private\\report.pdf") is None
    assert public_source_url("javascript:alert(1)") is None
