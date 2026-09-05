"""Entity mismatch guard for extracted snapshots."""
from __future__ import annotations

from common.entity_match import EntityMatcher

ENTITY_FIELD_BY_DOC_TYPE = {
    "rating_rationale": "entity_name",
    "exchange_filing": "entity_name",
    "quarterly_results": "entity_name",
    "news": "entity_name",
    "sf_rationale": "originator",
    "credit_update": "entity_name",
}


def check_entity_mismatch(matcher: EntityMatcher, tagged_entity_id: int, doc_type: str, snapshot: dict) -> dict | None:
    field = ENTITY_FIELD_BY_DOC_TYPE.get(doc_type)
    stated = snapshot.get(field) if field else None
    if not stated:
        return None
    match = matcher.match(str(stated))
    if match and match.entity_id == tagged_entity_id:
        return None
    return {"tagged_entity_id": tagged_entity_id, "stated_name": stated, "matched_entity_id": match.entity_id if match else None}
