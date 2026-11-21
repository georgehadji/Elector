"""Field-ops page (phase 1 of analysis/field_ops_research.md): per constituency and party, each polling venue's
strength index, turnout quadrant, swing and vote potential, plus a stop list routed in the browser.

Usage: python -I -X utf8 analysis/field_ops.py   (after analysis/venue_parties.py; positions as in venue_map.py)
Writes analysis/venue_parties/field_ops.html. Public aggregate results only: no voter or volunteer data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
from venue_map import SRC, build, write

TEMPLATE = Path(__file__).resolve().parent / "field_ops_template.html"

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    write(build(), TEMPLATE, SRC / "field_ops.html")
