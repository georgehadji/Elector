"""Regression check on matching coverage: share of each constituency's votes placed on the map.

Compares the coverage embedded in every out/{election}_{ep}.html with tests/coverage_baseline.json
and fails if any page dropped by more than TOLERANCE. After an intended change, refresh with:
  python -I -X utf8 tests/test_coverage.py --update
Run: python -I -X utf8 -m unittest discover -s tests
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "coverage_baseline.json"
TOLERANCE = 0.002  # coverage is a 0..1 share


def current():
    out = {}
    for page in sorted((ROOT / "out").glob("*_*.html")):
        if not re.fullmatch(r"(2019|2023-may|2023-june|2024-euro)_\d+\.html", page.name):
            continue
        m = re.search(r'"coverage":\s*([\d.]+)', page.read_text(encoding="utf-8"))
        out[page.stem] = float(m.group(1))
    return out


@unittest.skipUnless(BASELINE.exists(), "no baseline: run with --update once")
class Coverage(unittest.TestCase):
    def test_no_drop(self):
        base, now = json.loads(BASELINE.read_text(encoding="utf-8")), current()
        missing = sorted(set(base) - set(now))
        drops = {k: (base[k], now[k]) for k in base if k in now and now[k] < base[k] - TOLERANCE}
        self.assertFalse(missing, f"pages missing: {missing}")
        self.assertFalse(drops, "coverage dropped: " + ", ".join(f"{k} {a:.1%} -> {b:.1%}" for k, (a, b) in drops.items()))


if __name__ == "__main__":
    if "--update" in sys.argv:
        cov = current()
        assert len(cov) == 4 * 59, len(cov)
        BASELINE.write_text(json.dumps(cov, indent=0, sort_keys=True), encoding="utf-8")
        print(f"wrote {BASELINE} ({len(cov)} pages, lowest {min(cov.values()):.1%})")
    else:
        unittest.main()
