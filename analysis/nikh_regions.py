"""NIKH (party 131) June 2023 -> Euro 2024 per region, and what the 2024 exit poll implies for its own retention.

- Per region (config.REGIONS): votes kept (Euro / June), the same ratio for all valid votes, shares, and per ELSTAT
  community the WLS slope of the Euro share on the June share and the weighted correlation of NIKH's change with the
  change of Ελλ. Λύση. Ecological figures: they describe places, not measured voter flows.
- Exit poll 2024 (joint exit poll, naftemporiki.gr 10/6/2024): share of each big party's 2023 voters that voted NIKH.
  Base of a party = its 2024 votes / its consolidation, an upper bound because it ignores inflows to that party.
  What is left of NIKH's 2024 vote after these inflows also holds its gains from every other party and from new
  voters, so it caps the June 2023 voters NIKH kept. Exit poll shares carry sampling error: read it as "about two thirds".

  python -I -X utf8 analysis/nikh_regions.py data/stavroi.sqlite
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import NIKH, REGIONS

EL = 108
J, E = "2023/june", "2024/euro"
# party: (name, consolidation, share of its 2023 voters that went to NIKH)
EXIT_2024 = {2: ("ΝΔ", 0.724, 0.023), 4: ("ΣΥΡΙΖΑ", 0.669, 0.008), 106: ("ΠΑΣΟΚ", 0.774, 0.005)}
c = sqlite3.connect(sys.argv[1])
region = {ep: name for name, eps in REGIONS for ep in eps}


def load(e):
    """{community: [valid, NIKH votes, Ελλ. Λύση votes, ep]} over stations matched to a community."""
    return {k: [v, n, el, ep] for k, v, n, el, ep in c.execute(
        "SELECT a.comm_code, SUM(s.valid), SUM((SELECT votes FROM party_votes p WHERE p.election=s.election AND "
        "p.tm_id=s.tm_id AND p.party_id=?)), SUM((SELECT votes FROM party_votes p WHERE p.election=s.election AND "
        "p.tm_id=s.tm_id AND p.party_id=?)), MIN(s.ep_id) FROM station s JOIN area_match a ON a.election=s.election "
        "AND a.tm_id=s.tm_id WHERE s.election=? GROUP BY 1", (NIKH, EL, e))}


def wcorr(a, b, w):
    ma, mb = np.average(a, weights=w), np.average(b, weights=w)
    return np.average((a - ma) * (b - mb), weights=w) / np.sqrt(
        np.average((a - ma) ** 2, weights=w) * np.average((b - mb) ** 2, weights=w))


dj, de = load(J), load(E)
codes = [k for k in dj if k in de and dj[k][0] >= 50 and de[k][0] >= 50 and dj[k][3] in region]
print(f"{len(codes)} κοινότητες. Ιούνιος 2023 → Ευρωεκλογές 2024, ανά περιφέρεια")
print(f"{'':<30}{'ΝΙΚΗ Ιούν.':>11}{'Ευρ.':>8}{'κράτησε':>9}{'έγκυρα':>8}{'σχετικά':>9}{'% Ιούν.':>9}{'% Ευρ.':>8}"
      f"{'κλίση':>7}{'r με ΕΛ':>9}")
rows = []
for name, eps in REGIONS + [("ΣΥΝΟΛΟ", sorted(region))]:
    ks = [k for k in codes if dj[k][3] in eps]
    vj, nj, lj = (np.array([dj[k][i] or 0 for k in ks], float) for i in (0, 1, 2))
    ve, ne, le = (np.array([de[k][i] or 0 for k in ks], float) for i in (0, 1, 2))
    sj, se = 100 * nj / vj, 100 * ne / ve
    slope = np.polyfit(sj, se, 1, w=np.sqrt(vj))[0]
    kept, valid = ne.sum() / nj.sum(), ve.sum() / vj.sum()
    rows.append((name, kept / valid))
    print(f"{name:<30}{nj.sum():>11,.0f}{ne.sum():>8,.0f}{100 * kept:>8.0f}%{100 * valid:>7.0f}%{kept / valid:>9.2f}"
          f"{100 * nj.sum() / vj.sum():>9.2f}{100 * ne.sum() / ve.sum():>8.2f}{slope:>7.2f}"
          f"{wcorr(se - sj, 100 * le / ve - 100 * lj / vj, vj):>9.2f}")
assert abs(rows[-1][1] - 1.2) < 0.2, rows[-1]  # national: NIKH kept ~89% of its votes while valid votes fell to ~75%

tot = {e: dict(c.execute("SELECT party_id, SUM(votes) FROM party_votes WHERE election=? GROUP BY 1", (e,))) for e in (J, E)}
print(f"\nExit poll 2024: εισροές στη ΝΙΚΗ από τα τρία μεγάλα κόμματα (ΝΙΚΗ Ευρωεκλογών στις κάλπες: {tot[E][NIKH]:,})")
inflow = 0
for pid, (name, cons, to_nikh) in EXIT_2024.items():
    n = to_nikh * tot[E][pid] / cons
    inflow += n
    print(f"  {name:<8}{100 * to_nikh:.1f}% των ψηφοφόρων του 2023 που ψήφισαν το 2024 (έως {tot[E][pid] / cons:,.0f}) = έως {n:,.0f} ψήφοι")
own = tot[E][NIKH] - inflow
print(f"  Σύνολο έως {inflow:,.0f} ({100 * inflow / tot[E][NIKH]:.0f}% της ΝΙΚΗΣ). Μένουν {own:,.0f} για δικούς της του Ιουνίου, "
      f"Ελλ. Λύση, Σπαρτιάτες, άλλους και νέους:\n  με αυτές τις εισροές η ΝΙΚΗ κράτησε το πολύ περίπου {100 * own / tot[J][NIKH]:.0f}% των "
      f"{tot[J][NIKH]:,} ψηφοφόρων της του Ιουνίου 2023.")
