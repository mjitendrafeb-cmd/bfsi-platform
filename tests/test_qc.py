from pathlib import Path
from matching.entity_matcher import EntityMatcher
from qc.figure_trace import audit_snapshot
from qc.mismatch_guard import check_entity_mismatch

def test_figure_trace_flags_missing_number():
    assert audit_snapshot({'pat_cr': 123.4}, 'PAT was 120.0 crore')
    assert not audit_snapshot({'pat_cr': 123.4}, 'PAT was 123.4 crore')

def test_mismatch_guard():
    matcher = EntityMatcher(Path('data/entity_master.csv'))
    assert check_entity_mismatch(matcher, 2, 'rating_rationale', {'entity_name':'Muthoot Microfin Limited'})['matched_entity_id'] is None
    assert check_entity_mismatch(matcher, 2, 'rating_rationale', {'entity_name':'Muthoot Finance Limited'}) is None
