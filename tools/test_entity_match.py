"""Quick check: does the entity matcher handle real-world name variants
correctly, including NOT matching similarly-named sister companies?

    python tools/test_entity_match.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.entity_match import EntityMatcher

# (name as it might appear on a CRA/exchange site, should it match our master?)
CASES = [
    ("Muthoot Finance Ltd", True),
    ("Muthoot Finance Ltd.", True),
    ("MUTHOOT FINANCE LIMITED", True),
    ("Muthoot Finance", True),
    ("Spandana Sphoorty Financial Ltd", True),
    ("SPANDANA SPHOORTY FINANCIAL LTD", True),
    ("IKF Home Finance Pvt Ltd", True),
    ("Muthoot Microfin Limited", False),          # different Muthoot group co.
    ("Muthoot Capital Services Limited", False),  # different Muthoot group co.
]


def main() -> None:
    matcher = EntityMatcher(ROOT / "data/entity_master.csv")

    rows = []
    all_ok = True
    for name, should_match in CASES:
        m = matcher.match(name)
        got_match = m is not None
        ok = got_match == should_match
        all_ok &= ok
        rows.append((
            name,
            f"id={m.entity_id} ({m.display_name})" if m else "NO MATCH",
            f"{m.confidence:.3f}" if m else "-",
            "PASS" if ok else "FAIL",
        ))

    widths = [max(len(r[i]) for r in rows + [("Input name", "Matched to", "Confidence", "Result")]) for i in range(4)]
    header = ("Input name", "Matched to", "Confidence", "Result")
    for row in [header, tuple("-" * w for w in widths), *rows]:
        print(" | ".join(cell.ljust(w) for cell, w in zip(row, widths)))

    print(f"\n{'ALL PASSED' if all_ok else 'SOME FAILED'}")


if __name__ == "__main__":
    main()
