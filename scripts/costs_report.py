from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path("db/tracker.sqlite")
SETTINGS = Path("config/settings.yaml")


def _budget_cap() -> float | None:
    if not SETTINGS.exists():
        return None
    for line in SETTINGS.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("monthly_cap_usd:"):
            try:
                return float(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def main() -> None:
    if not DB.exists():
        print("No db/tracker.sqlite found; no AI costs recorded.")
        return
    conn = sqlite3.connect(DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ai_costs (
               id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, task TEXT,
               model TEXT, input_tokens INTEGER DEFAULT 0,
               output_tokens INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0,
               created_at TEXT)"""
    )
    rows = conn.execute(
        """SELECT COALESCE(model, 'unknown'), COUNT(*),
                  COALESCE(SUM(input_tokens), 0),
                  COALESCE(SUM(output_tokens), 0),
                  COALESCE(SUM(cost_usd), 0)
           FROM ai_costs GROUP BY model ORDER BY 5 DESC"""
    ).fetchall()
    total = sum(float(r[4]) for r in rows)
    cap = _budget_cap()
    if not rows:
        cap_text = f" Monthly budget cap: ${cap:.2f}." if cap is not None else ""
        print(f"No AI costs recorded yet.{cap_text}")
        return
    print("model,runs,input_tokens,output_tokens,cost_usd")
    for r in rows:
        print(f"{r[0]},{r[1]},{r[2]},{r[3]},{float(r[4]):.4f}")
    if cap is not None:
        remaining = cap - total
        status = "OK" if remaining >= 0 else "OVER_BUDGET"
        print(f"total_cost_usd={total:.4f},monthly_cap_usd={cap:.2f},remaining_usd={remaining:.4f},status={status}")


if __name__ == "__main__":
    main()
