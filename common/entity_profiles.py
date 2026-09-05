"""Curated, source-linked entity profile metadata for the analyst UI."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_FILE = ROOT / "data" / "entity_profiles.json"


@lru_cache(maxsize=1)
def load_entity_profiles() -> dict[int, dict]:
    """Load curated profiles keyed by stable entity ID."""
    if not PROFILE_FILE.exists():
        return {}
    profiles = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    return {int(entity_id): profile for entity_id, profile in profiles.items()}


def entity_profile(entity_id: int) -> dict | None:
    return load_entity_profiles().get(entity_id)
