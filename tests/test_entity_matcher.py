from pathlib import Path
from matching.entity_matcher import EntityMatcher

matcher = EntityMatcher(Path('data/entity_master.csv'))

def test_muthoot_finance_matches_ltd():
    assert matcher.match('Muthoot Finance Ltd').entity_id == 2

def test_muthoot_finance_rejects_siblings():
    assert matcher.match('Muthoot Microfin') is None
    assert matcher.match('Muthoot Capital') is None

def test_spandana_variants_match():
    assert matcher.match('Spandana Sphoorty Financial Ltd').entity_id == 1
    assert matcher.match('Spandana Sphoorty').entity_id == 1

def test_ikf_variants_match():
    assert matcher.match('IKF Home Finance Ltd').entity_id == 3
    assert matcher.match('IKF Home Finance Limited').entity_id == 3
