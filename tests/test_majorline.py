"""Offline check of analysis/majorline_fetch.py (flatten + upsert on a synthetic file; no network)."""
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import majorline_fetch


class MajorlineFetch(unittest.TestCase):
    def test_selftest(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            majorline_fetch.selftest()
        self.assertIn("selftest ok", out.getvalue())


if __name__ == "__main__":
    unittest.main()
