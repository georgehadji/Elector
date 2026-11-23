"""Summary of the PyEI models per region (analysis/pyei_regions/<base>_to_<target>_<N>.txt, written by
pyei_2019_2023.py --region=N) -> analysis/pyei_regions/summary.txt.

Per election pair, one row per region (N = index in config.REGIONS):
- base with NIKH (2023/may, 2023/june): where the base election's NIKH voters went (the "Ψηφοφόροι ΝΙΚΗΣ" block, % of the group).
- base 2019 (no NIKH): where the target election's NIKH voters came from (the "% ψήφων ΝΙΚΗ" column of the NIKH table).
Means, 90% credible interval in brackets, and the aggregate max rhat of the model (none converged: rhat >> 1.01).
The national row is the mean weighted by NIKH's votes in the region (base election for destinations, target for origins),
ordinary stations; it is a summary of 13 separate models, not a 14th model.

  python -I -X utf8 analysis/pyei_regions_summary.py data/stavroi.sqlite > analysis/pyei_regions/summary.txt
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import NIKH, REGIONS

DIR = Path(__file__).resolve().parent / "pyei_regions"
DEST = re.compile(r"^(.+?)\s+([\d.]+)%\s+\(([\d.]+)–([\d.]+)\)$")
COMP = re.compile(r"^(.+?)\s+[\d.]+\s+[\d.]+–[\d.]+\s+([\d.]+)\s+([\d.]+)–([\d.]+)$")


def parse(path):
    """(units, aggregate max rhat, {name: (mean, lo, hi)}, kind) of one model output; kind = dest | comp."""
    lines = path.read_text(encoding="utf-8").splitlines()
    head = next(x for x in lines if "δημοτικές ενότητες" in x)
    units = int(re.search(r"(\d+) δημοτικές ενότητες", head).group(1))
    rhat = float(re.search(r"aggregate max rhat: ([\d.]+)", "\n".join(lines)).group(1))
    out = {}
    if any(x.startswith("=== Ψηφοφόροι ΝΙΚΗΣ") for x in lines):
        kind, i = "dest", next(i for i, x in enumerate(lines) if x.startswith("=== Ψηφοφόροι ΝΙΚΗΣ")) + 1
        for x in lines[i:]:
            m = DEST.match(x.strip())
            if m:
                out[m.group(1)] = tuple(map(float, m.group(2, 3, 4)))
    else:
        kind, i = "comp", next(i for i, x in enumerate(lines) if x.startswith("=== ΝΙΚΗ ")) + 2
        for x in lines[i:]:
            if x.startswith("("):
                break
            m = COMP.match(x.strip())
            out[m.group(1)] = tuple(map(float, m.group(2, 3, 4)))
    assert abs(sum(v[0] for v in out.values()) - 100) < 2, (path, sum(v[0] for v in out.values()))  # shares sum to 100
    return units, rhat, out, kind


def nikh_votes(c, election, eps):
    q = ",".join("?" * len(eps))
    return c.execute(f"SELECT SUM(pv.votes) FROM station s JOIN party_votes pv ON pv.election=s.election AND pv.tm_id=s.tm_id "
                     f"WHERE s.kind='Κ' AND s.election=? AND pv.party_id=? AND s.ep_id IN ({q})",
                     (election, NIKH, *eps)).fetchone()[0] or 0


def key(slug):
    """'2023-may' -> '2023/may', '2019' -> '2019' (config.slug reversed)."""
    return slug.replace("-", "/", 1)


if __name__ == "__main__":
    c = sqlite3.connect(sys.argv[1])
    pairs = sorted({p.stem.rsplit("_", 1)[0] for p in DIR.glob("*_to_*_*.txt")})
    out = []
    for pair in pairs:
        base, target = map(key, pair.split("_to_"))
        rows = []
        for n, (name, eps) in enumerate(REGIONS):
            p = DIR / f"{pair}_{n}.txt"
            if p.exists():
                units, rhat, vals, kind = parse(p)
                rows.append((name, units, rhat, vals, nikh_votes(c, base if kind == "dest" else target, eps), kind))
        cols, kind = list(rows[0][3]), rows[0][5]
        what = f"ψηφοφόροι ΝΙΚΗΣ {base} → {target}: πού πήγαν (% της ομάδας)" if kind == "dest" else \
            f"ψηφοφόροι ΝΙΚΗΣ {target}: από πού ήρθαν, ως ψήφοι {base} (% των ψήφων ΝΙΚΗΣ)"
        out.append(f"\n{pair}: {what}, {len(rows)} από {len(REGIONS)} περιφέρειες")
        out.append(f"  {'περιφέρεια':<31}{'ενότ.':>6}{'rhat':>6}" + "".join(f"{x[:14]:>16}" for x in cols))
        for name, units, rhat, vals, _, _ in sorted(rows, key=lambda r: -r[3][cols[0]][0]):
            out.append(f"  {name:<31}{units:>6}{rhat:>6.2f}" + "".join(
                f"{f'{vals[x][0]:.0f} ({vals[x][1]:.0f}-{vals[x][2]:.0f})':>16}" for x in cols))
        W = sum(r[4] for r in rows)
        out.append(f"  {'σταθμισμένος μέσος (ψήφοι ΝΙΚΗΣ)':<43}" + "".join(
            f"{sum(r[3][x][0] * r[4] for r in rows) / W:>16.1f}" for x in cols))
        out.append(f"  rhat {min(r[2] for r in rows):.2f}-{max(r[2] for r in rows):.2f}: κανένα μοντέλο δεν συνέκλινε")
    print("\n".join(out).lstrip("\n"))
