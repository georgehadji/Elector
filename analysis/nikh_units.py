"""NIKH (party 131) per municipal unit (constituency, δημοτική ενότητα): strongholds, losses, neighbouring pools.

- Strongholds: most NIKH votes in June 2023.
- Shortfall June 2023 -> Euro 2024: June NIKH votes scaled by the unit's change in valid votes (turnout),
  minus actual Euro votes. Positive = NIKH kept fewer voters than turnout alone explains.
- Pool: June votes of Ελλ. Λύση + Σπαρτιάτες, the parties closest to NIKH.

  python -I -X utf8 analysis/nikh_units.py data/stavroi.sqlite
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import NIKH

c = sqlite3.connect(sys.argv[1])
ep_name = dict(c.execute("SELECT ep_id, name FROM ep WHERE election='2023/june'"))


def load(e):
    """{(ep, unit): (valid, {party: votes})}"""
    out = {(ep, den): (v, {}) for ep, den, v in c.execute(
        "SELECT ep_id, den_descr, SUM(valid) FROM station WHERE election=? GROUP BY 1, 2", (e,))}
    for ep, den, pid, v in c.execute(
            "SELECT s.ep_id, s.den_descr, pv.party_id, SUM(pv.votes) FROM station s JOIN party_votes pv "
            "ON pv.election=s.election AND pv.tm_id=s.tm_id WHERE s.election=? GROUP BY 1, 2, 3", (e,)):
        out[ep, den][1][pid] = v
    return out


june, euro = load("2023/june"), load("2024/euro")
rows = []
for k, (v, pv) in june.items():
    if k not in euro or v < 500 or k[1] is None:
        continue
    ev, epv = euro[k]
    n, en = pv.get(NIKH, 0), epv.get(NIKH, 0)
    rows.append({"name": f"{k[1]} ({ep_name[k[0]]})", "valid": v, "n": n, "pct": 100 * n / v, "epct": 100 * en / ev,
                 "short": n * ev / v - en, "pool": pv.get(108, 0) + pv.get(157, 0)})
print(f"{len(rows)} δημοτικές ενότητες με ≥500 έγκυρα και στις δύο εκλογές")


def show(title, key, n=15, fmt=lambda r: ""):
    print(f"\n{title}")
    for r in sorted(rows, key=key)[:n]:
        print(f"  {r['name'][:52]:<53}ΝΙΚΗ {r['n']:>6,} ({r['pct']:4.1f}% → Ευρ. {r['epct']:4.1f}%){fmt(r)}")


show("Περισσότερες ψήφοι ΝΙΚΗΣ (Ιούνιος 2023):", lambda r: -r["n"])
show("Υψηλότερο ποσοστό (Ιούνιος 2023, ≥2.000 έγκυρα):", lambda r: -r["pct"] if r["valid"] >= 2000 else 0)
show("Μεγαλύτερη απώλεια Ιούνιος → Ευρωεκλογές, πέρα από τη συμμετοχή:", lambda r: -r["short"],
     fmt=lambda r: f"  έλλειμμα {r['short']:,.0f}")
show("Μεγαλύτερες δεξαμενές Ελλ. Λύσης + Σπαρτιατών (Ιούνιος 2023):", lambda r: -r["pool"],
     fmt=lambda r: f"  δεξαμενή {r['pool']:,}")
tot_short = sum(r["short"] for r in rows)
print(f"\nΣυνολικό έλλειμμα πέρα από τη συμμετοχή: {tot_short:,.0f} ψήφοι "
      f"(θετικό σε {sum(r['short'] > 0 for r in rows)} από {len(rows)} ενότητες)")
