"""Database helpers for the FastAPI app package."""
from pathlib import Path

from common.storage import Storage
from webapp.queries import get_conn

DB_PATH = Path("db/tracker.sqlite")


def init_db(db_path: Path = DB_PATH) -> Storage:
    """Create/migrate SQLite tables and seed master data/metric definitions."""
    return Storage(db_path)


__all__ = ["DB_PATH", "get_conn", "init_db"]
