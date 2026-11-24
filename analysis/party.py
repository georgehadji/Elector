"""Which party an analysis script studies: --party=ID and --rival=ID on its command line.

Defaults: config.NIKH and Ελληνική Λύση (108; NIKH when the party is 108), so a script run without the flags is the NIKH analysis, unchanged.
The flags are removed from sys.argv on import, so each script's own positional arguments keep their places:

  python -I -X utf8 analysis/nikh_regions.py data/stavroi.sqlite --party=108 --rival=131

Sections that rest on hand-entered NIKH inputs (exit poll, PyEI constants copied from NIKH.md) run only when IS_NIKH,
and only when REFERENCE where they describe June 2023 -> Euro 2024. Scripts that compare two elections take
--base=KEY --target=KEY (config.ELECTIONS keys, default 2023/june -> 2024/euro).
A script that writes a page uses page_path(): for another party it must not write into out/, which is published.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import ELECTION_NAMES, ELECTIONS, NIKH, OUT, PARTY_GEN, PARTY_SHORT


def _pop(flag, default):
    """Value of --flag=V in sys.argv (removed from it), else default."""
    for a in sys.argv[1:]:
        if a.startswith(f"--{flag}="):
            sys.argv.remove(a)
            return a.split("=", 1)[1]
    return default


ID = int(_pop("party", NIKH))
# Election pair of the scripts that compare two elections (base -> target); keys of config.ELECTIONS.
BASE, TARGET = _pop("base", "2023/june"), _pop("target", "2024/euro")
if BASE not in ELECTIONS or TARGET not in ELECTIONS or list(ELECTIONS).index(BASE) >= list(ELECTIONS).index(TARGET):
    raise SystemExit(f"--base={BASE} --target={TARGET}: need two keys of config.ELECTIONS {list(ELECTIONS)}, base older")
BASE_NAME, TARGET_NAME = ELECTION_NAMES[BASE], ELECTION_NAMES[TARGET]
ABBR = {"2019": "2019", "2023/may": "Μάι.", "2023/june": "Ιούν.", "2024/euro": "Ευρ."}  # column headers
DEFAULT_PAIR = (BASE, TARGET) == ("2023/june", "2024/euro")
RIVAL = int(_pop("rival", NIKH if ID == 108 else 108))  # never the party itself by default
_OUT = _pop("out", None)
IS_NIKH = ID == NIKH
REFERENCE = IS_NIKH and DEFAULT_PAIR  # the NIKH June 2023 -> Euro 2024 run that hand-entered constants describe
NAME, GEN = PARTY_SHORT.get(ID, str(ID)), PARTY_GEN.get(ID, PARTY_SHORT.get(ID, str(ID)))
RIVAL_NAME = PARTY_SHORT.get(RIVAL, str(RIVAL))


def page_path(nikh_name):
    """Where a page goes: out/<nikh_name> for NIKH, else --out=PATH, which must lie outside out/ (published)."""
    if IS_NIKH and _OUT is None:
        return OUT / nikh_name
    if _OUT is None:
        raise SystemExit(f"--party={ID}: pass --out=PATH (outside {OUT}, which is published)")
    p = Path(_OUT).resolve()
    if p.is_relative_to(OUT.resolve()):
        raise SystemExit(f"--out={_OUT}: inside {OUT}, which is published")
    return p
