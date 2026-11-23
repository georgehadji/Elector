"""Where NIKH (party 131) should work: concentration of its vote per municipal unit (constituency, δημοτική ενότητα).

- Peak = most votes NIKH got in the unit in May 2023, June 2023 or Euro 2024: people there who have already voted for it.
- Effort = registered voters of the unit (June 2023). Yield = peak votes per 100 registered.
- Units are ranked by yield. The curve shows what share of the peak vote sits in the first 10%, 20%, ... of the electorate.
  Tiers: A = first 20% of the electorate, B = next 30%, C = last 50%.
- THRESHOLD is 3% of the June 2023 valid votes.

  python -I -X utf8 analysis/nikh_pareto.py data/stavroi.sqlite
"""
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zones import assign_tiers, load_units, threshold

ELECTIONS = ("2023/may", "2023/june", "2024/euro")
c = sqlite3.connect(sys.argv[1])
THRESHOLD = threshold(c)
ep_name = dict(c.execute("SELECT ep_id, name FROM ep WHERE election='2023/june'"))

units = load_units(c, ELECTIONS)
for u in units:
    n = [u["v"][e] for e in ELECTIONS]
    u.update(june=n[1], euro=n[2], peak=max(n))
    u["yield"] = 100 * u["peak"] / u["reg"]
units.sort(key=lambda u: -u["yield"])
assign_tiers(units)
REG, PEAK, JUNE = (sum(u[f] for u in units) for f in ("reg", "peak", "june"))
print(f"{len(units)} δημοτικές ενότητες, {REG:,} εγγεγραμμένοι. ΝΙΚΗ Ιούνιος 2023: {JUNE:,}. "
      f"Άθροισμα κορυφών: {PEAK:,} ({100 * PEAK / THRESHOLD:.0f}% του ορίου των {THRESHOLD:,})")

print("\nΚαμπύλη συγκέντρωσης (ενότητες κατά φθίνουσα απόδοση = ψήφοι κορυφής ανά 100 εγγεγραμμένους):")
print(f"  {'εκλογικό σώμα':>14}{'ενότητες':>10}{'ψήφοι κορυφής':>15}{'% κορυφής':>11}{'% ορίου':>9}{'απόδοση ≥':>11}")
acc_r = acc_p = 0
marks = iter((10, 20, 30, 40, 50, 60, 80, 100))
m = next(marks)
for i, u in enumerate(units, 1):
    acc_r += u["reg"]
    acc_p += u["peak"]
    while m is not None and acc_r >= m / 100 * REG:
        print(f"  {m:>13}%{i:>10,}{acc_p:>15,}{100 * acc_p / PEAK:>10.0f}%{100 * acc_p / THRESHOLD:>8.0f}%{u['yield']:>11.1f}")
        m = next(marks, None)

by_votes = sorted(units, key=lambda u: -u["peak"])
acc = 0
for i, u in enumerate(by_votes, 1):
    acc += u["peak"]
    if acc >= 0.8 * PEAK:
        print(f"\nΚατά απόλυτο αριθμό: οι {i} μεγαλύτερες ενότητες ({100 * i / len(units):.0f}% των ενοτήτων) έχουν το 80% των ψήφων "
              f"και το {100 * sum(x['reg'] for x in by_votes[:i]) / REG:.0f}% του εκλογικού σώματος")
        break

tier = defaultdict(lambda: [0, 0, 0, 0])  # units, registered, peak, Euro 2024 votes
for u in units:
    for i, x in enumerate((1, u["reg"], u["peak"], u["euro"])):
        tier[u["tier"]][i] += x
print("\nΖώνες:")
for t, label in (("A", "A: δούλεψε περισσότερο (πρώτο 20% του σώματος)"), ("B", "B: συντήρηση (επόμενο 30%)"),
                 ("C", "C: άφησε (τελευταίο 50%)")):
    n, r, p, e = tier[t]
    print(f"  {label:<46}{n:>5} ενότητες, {r:>9,} εγγ., κορυφή {p:>7,} ({100 * p / PEAK:.0f}%), Ευρ. 2024 {e:>7,}, "
          f"{100 * p / r:.1f} ανά 100 εγγ.")

for t, title in (("A", "Ζώνη A ανά περιφέρεια (ψήφοι κορυφής)"), ("C", "Ζώνη C ανά περιφέρεια (εγγεγραμμένοι)")):
    eps = defaultdict(lambda: [0, 0, 0])
    for u in units:
        e = eps[u["k"][0]]
        e[2] += u["reg"]
        if u["tier"] == t:
            e[0] += u["reg"]
            e[1] += u["peak"]
    print(f"\n{title}:")
    for ep, (r, p, total) in sorted(eps.items(), key=lambda x: -x[1][1 if t == "A" else 0])[:22]:
        if r:
            print(f"  {ep_name[ep][:34]:<35}{r:>9,} εγγ. ({100 * r / total:3.0f}% της περιφέρειας), κορυφή {p:>6,}")

for t, title, key in (("A", "Ζώνη A: οι 40 ενότητες με τις περισσότερες ψήφους", lambda u: -u["peak"]),
                      ("C", "Ζώνη C: οι 25 μεγαλύτερες ενότητες που αφήνονται", lambda u: -u["reg"])):
    print(f"\n{title}:")
    for u in sorted((u for u in units if u["tier"] == t), key=key)[:40 if t == "A" else 25]:
        print(f"  {u['k'][1][:26]:<27}{ep_name[u['k'][0]][:26]:<27}κορυφή {u['peak']:>6,}  {u['yield']:4.1f} ανά 100 εγγ.  "
              f"Ιούν. {100 * u['june'] / u['valid']:4.1f}%  Ευρ. 2024 {u['euro']:>6,}")
