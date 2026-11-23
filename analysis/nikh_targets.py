"""Where NIKH (party 131) wins seats and where its vote can grow, per constituency.

For each constituency: seats (ministry statics), NIKH votes and share in May 2023, June 2023 and Euro 2024,
the June "space" (NIKH + Ελλ. Λύση + Σπαρτιάτες), and NIKH's June votes measured in electoral quotas
(valid votes / seats). Under π.δ. 26/2012 art. 100 a small party gets its constituency seats where its
unused votes (votes - seats x quota) rank highest, so the quota fraction approximates that ranking.

  python -I -X utf8 analysis/nikh_targets.py data/stavroi.sqlite
"""
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import ELECTED, NIKH, source
from fetch import statics

BLOC_JUNE = (NIKH, 108, 157)
c = sqlite3.connect(sys.argv[1])
seats = {e[0]: e[4] for e in statics(*source("2023/june"), "ep") if e[4] > 0}
name = dict(c.execute("SELECT ep_id, name FROM ep WHERE election='2023/june'"))


def totals(e, parties):
    """{ep: (valid, votes of the given parties)} over all stations of the election."""
    valid = dict(c.execute("SELECT ep_id, SUM(valid) FROM station WHERE election=? GROUP BY 1", (e,)))
    q = ",".join("?" * len(parties))
    votes = dict(c.execute(f"SELECT s.ep_id, SUM(pv.votes) FROM station s JOIN party_votes pv "
                           f"ON pv.election=s.election AND pv.tm_id=s.tm_id WHERE s.election=? "
                           f"AND pv.party_id IN ({q}) GROUP BY 1", (e, *parties)))
    return {ep: (v, votes.get(ep, 0)) for ep, v in valid.items()}


may, june, euro = (totals(e, (NIKH,)) for e in ("2023/may", "2023/june", "2024/euro"))
bloc = totals("2023/june", BLOC_JUNE)

for label, t in (("Μάιος 2023", may), ("Ιούνιος 2023", june), ("Ευρωεκλογές 2024", euro)):
    v, n = sum(x[0] for x in t.values()), sum(x[1] for x in t.values())
    print(f"{label}: ΝΙΚΗ {n:,} / {v:,} έγκυρα = {100 * n / v:.2f}%  (3% = {math.ceil(0.03 * v):,}, "
          f"διαφορά {n - math.ceil(0.03 * v):+,})")

rows = []
for ep, s in seats.items():
    v, n = june[ep]
    quota = v / s
    rows.append({"ep": ep, "name": name[ep], "seats": s, "q": n / quota,
                 "may": 100 * may[ep][1] / may[ep][0], "june": 100 * n / v, "euro": 100 * euro[ep][1] / euro[ep][0],
                 "bloc": 100 * bloc[ep][1] / bloc[ep][0], "votes": n, "pool": bloc[ep][1] - n,
                 "elected": ep in ELECTED})

total = sum(r["votes"] for r in rows)
print(f"\n{'Περιφέρεια':<24}{'έδρ':>4}{'Μάι%':>6}{'Ιούν%':>7}{'Ευρ%':>6}{'χώρος%':>8}{'ψήφοι Ιούν':>11}"
      f"{'% εθν.':>7}{'quota':>7}  εξελέγη")
for r in sorted(rows, key=lambda r: -r["q"]):
    print(f"{r['name'][:23]:<24}{r['seats']:>4}{r['may']:>6.1f}{r['june']:>7.1f}{r['euro']:>6.1f}{r['bloc']:>8.1f}"
          f"{r['votes']:>11,}{100 * r['votes'] / total:>7.1f}{r['q']:>7.2f}  {'ΝΑΙ' if r['elected'] else ''}")

# Check: the 9 constituency MPs should sit at the top of the quota ranking.
top = {r["ep"] for r in sorted(rows, key=lambda r: -r["q"])[:len(ELECTED)]}
print(f"\nΑπό τις {len(ELECTED)} περιφέρειες με το μεγαλύτερο quota, εξέλεξαν βουλευτή: {len(top & set(ELECTED))}")

cum = 0
for i, r in enumerate(sorted(rows, key=lambda r: -r["votes"]), 1):
    cum += r["votes"]
    if cum >= total / 2:
        print(f"Το 50% των ψήφων της ΝΙΚΗΣ (Ιούνιος) βρίσκεται σε {i} από τις {len(rows)} περιφέρειες.")
        break

# Neighbouring voters: June votes of Ελλ. Λύση + Σπαρτιάτες, the parties closest to NIKH.
print("\nΜεγαλύτερες δεξαμενές γειτονικών ψήφων (Ελλ. Λύση + Σπαρτιάτες, Ιούνιος 2023):")
for r in sorted(rows, key=lambda r: -r["pool"])[:12]:
    print(f"  {r['name']:<28}{r['pool']:>8,}  (ΝΙΚΗ {r['votes']:,})")
