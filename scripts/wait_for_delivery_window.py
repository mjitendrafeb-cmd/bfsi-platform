"""Wait until the configured IST delivery window opens."""
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

root = Path(__file__).resolve().parents[1]
hour, minute = map(int, json.loads((root / "config.json").read_text())["delivery_window_ist"].split(":"))
now = datetime.now(UTC)
ist = now + timedelta(hours=5, minutes=30)
target = ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
if ist < target:
    seconds = (target - ist).total_seconds()
    print(f"Delivery window not open; sleeping {seconds:.0f} seconds", flush=True)
    time.sleep(seconds)
