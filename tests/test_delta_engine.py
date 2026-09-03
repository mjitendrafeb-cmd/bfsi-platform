from pipeline.diff import diff_snapshots

def test_deterministic_field_diff():
    changes = diff_snapshots({'rating':'A','metrics':{'gnpa_pct':2.1}}, {'rating':'BBB','metrics':{'gnpa_pct':3.4}})
    assert {'field':'rating','old':'A','new':'BBB','kind':'modified'} in changes
    assert {'field':'metrics.gnpa_pct','old':2.1,'new':3.4,'kind':'increased'} in changes
