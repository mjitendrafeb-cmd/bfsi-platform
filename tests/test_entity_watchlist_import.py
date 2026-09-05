import csv
from pathlib import Path

from scripts.import_entity_watchlist import canonical_name, classify, merge


def test_canonical_name_removes_source_markers_and_preserves_legal_core():
    assert canonical_name("Bandhan Mutual Fund (BLR)") == "Bandhan Mutual Fund"
    assert canonical_name("ICICI Prudential Mutual Fund - BLR") == "ICICI Prudential Mutual Fund"
    assert canonical_name(
        "L&T Finance Limited (formerly known as L&T Finance Holdings Limited)"
    ) == "L&T Finance Limited"


def test_import_is_idempotent_and_preserves_aliases(tmp_path: Path):
    source = tmp_path / "watchlist.txt"
    source.write_text(
        "Bandhan Mutual Fund (BLR)\nBandhan Mutual Fund\n"
        "L&T Finance Limited (formerly known as L&T Finance Holdings Limited)\n",
        encoding="utf-8",
    )
    master = tmp_path / "master.csv"
    added, merged, ignored = merge(source, master)
    assert (added, merged, ignored) == (2, 1, 0)
    merge(source, master)
    with open(master, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    bandhan = next(row for row in rows if row["legal_name"] == "Bandhan Mutual Fund")
    assert "Bandhan Mutual Fund (BLR)" in bandhan["aliases"]
    ltf = next(row for row in rows if row["legal_name"] == "L&T Finance Limited")
    assert "L&T Finance Holdings Limited" in ltf["aliases"]


def test_sector_classification_for_key_bfsi_groups():
    assert classify("MINTIFI Finserve Private Limited") == ("NBFC", "supply_chain_finance")
    assert classify("ESAF Small Finance Bank Limited") == ("Bank", "small_finance_bank")
    assert classify("Fedbank Financial Services Limited") == ("NBFC", "other_finance")
    assert classify("LIC Housing Finance Limited") == ("HFC", "housing_finance")
    assert classify("Axis Mutual Fund") == ("Asset Management", "mutual_fund")
    assert classify("Universal Sompo General Insurance Company Limited") == (
        "Insurance", "insurance"
    )
