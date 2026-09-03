import csv
from pathlib import Path

from common.storage import Storage


def test_storage_creates_canonical_tables_and_seeds_master(tmp_path):
    db = tmp_path / "tracker.sqlite"
    storage = Storage(db, Path("data/entity_master.csv"))
    tables = {
        row[0]
        for row in storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {
        "entities",
        "source_items",
        "documents",
        "snapshots",
        "diffs",
        "rating_actions",
        "financial_metrics",
        "financial_cells",
        "review_queue",
        "news_events",
        "ai_costs",
        "scraper_health",
    } <= tables
    with open("data/entity_master.csv", newline="", encoding="utf-8-sig") as handle:
        expected_entities = sum(1 for _ in csv.DictReader(handle))
    assert storage.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == expected_entities
    assert storage.conn.execute("SELECT COUNT(*) FROM financial_metrics").fetchone()[0] >= 10
