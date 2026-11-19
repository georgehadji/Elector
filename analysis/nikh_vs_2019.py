import sqlite3
import sys
from statistics import correlation, mean, median, quantiles, stdev

DB = sys.argv[1]
c = sqlite3.connect(DB)

# per (election, ep, den, ekd): registered, valid, {party_id: votes}; ordinary stations only
Q = """
SELECT s.election, s.ep_id, s.den_descr, s.ekd_descr, pv.party_id,
       SUM(pv.votes)
FROM station s JOIN party_votes pv ON pv.election=s.election AND pv.tm_id=s.tm_id
WHERE s.kind='Κ' AND s.election IN ('2019','2023/may','2023/june')
GROUP BY 1,2,3,4,5
"""
QT = """
SELECT election, ep_id, den_descr, ekd_descr, SUM(registered), SUM(valid)
FROM station WHERE kind='Κ' AND election IN ('2019','2023/may','2023/june')
GROUP BY 1,2,3,4
"""
tot, votes = {}, {}
for e, ep, den, ekd, reg, val in c.execute(QT):
    tot[e, (ep, den, ekd)] = (reg, val)
for e, ep, den, ekd, pid, v in c.execute(Q):
    votes.setdefault((e, (ep, den, ekd)), {})[pid] = v

names19 = dict(c.execute("SELECT party_id,name FROM party WHERE election='2019'"))
eps19 = {ep for (e, (ep, _, _)) in tot if e == '2019'}
keys23 = {k for (e, k) in tot if e == '2023/may' and k[0] in eps19}
keys = sorted(k for k in keys23 if ('2019', k) in tot and tot['2019', k][1] and tot['2023/may', k][1])
print(f"Διαμερίσματα 2023 στις {len(eps19)} περιφέρειες του 2019: {len(keys23)}, "
      f"ταιριάζουν με 2019: {len(keys)} ({100*len(keys)/len(keys23):.1f}%)")

def pct(e, k, pid):
    return 100 * votes.get((e, k), {}).get(pid, 0) / tot[e, k][1]

nikh_may = [pct('2023/may', k, 131) for k in keys]
nikh_jun = [pct('2023/june', k, 131) for k in keys if ('2023/june', k) in tot and tot['2023/june', k][1]]

def desc(label, xs):
    q = quantiles(xs, n=10)
    print(f"{label}: n={len(xs)} μέσος={mean(xs):.2f} διάμεσος={median(xs):.2f} "
          f"τ.απ.={stdev(xs):.2f} P10={q[0]:.2f} P90={q[-1]:.2f} max={max(xs):.2f}")

desc("ΝΙΚΗ Μάιος 2023 % εγκύρων", nikh_may)
desc("ΝΙΚΗ Ιούνιος 2023 % εγκύρων", nikh_jun)

for e in ('2023/may', '2023/june'):
    ks = [k for k in keys if (e, k) in tot]
    v = sum(votes.get((e, k), {}).get(131, 0) for k in ks)
    print(f"ΝΙΚΗ {e} συνολικά στα ίδια διαμερίσματα: {100*v/sum(tot[e, k][1] for k in ks):.2f}%")

print("\nΣυσχέτιση (Pearson) ΝΙΚΗ Μάιος 2023 με % κομμάτων 2019, ίδια διαμερίσματα:")
rows = []
for pid, name in names19.items():
    xs = [pct('2019', k, pid) for k in keys]
    if max(xs) > 0:
        rows.append((correlation(xs, nikh_may), mean(xs), name))
for r, m, name in sorted(rows, reverse=True):
    print(f"  r={r:+.2f}  (μέσο 2019 {m:5.2f}%)  {name}")

turn19 = [100 * tot['2019', k][1] / tot['2019', k][0] for k in keys]
turn23 = [100 * tot['2023/may', k][1] / tot['2023/may', k][0] for k in keys]
print(f"\nr(ΝΙΚΗ, έγκυρα/εγγεγρ. 2023) = {correlation(turn23, nikh_may):+.2f}")
print(f"r(ΝΙΚΗ, Δ έγκυρα/εγγεγρ. 2019→2023) = "
      f"{correlation([b - a for a, b in zip(turn19, turn23)], nikh_may):+.2f}")
print(f"r(ΝΙΚΗ, εγγεγραμμένοι διαμερίσματος) = "
      f"{correlation([tot['2023/may', k][0] for k in keys], nikh_may):+.2f}")

print("\nTop 15 διαμερίσματα (Μάιος 2023, ≥200 έγκυρα):")
top = sorted(((p, k) for p, k in zip(nikh_may, keys) if tot['2023/may', k][1] >= 200), reverse=True)[:15]
epn = dict(c.execute("SELECT ep_id,name FROM ep WHERE election='2023/may'"))
for p, (ep, den, ekd) in top:
    print(f"  {p:5.2f}%  {epn[ep]} / {den} / {ekd}  (έγκυρα {tot['2023/may', (ep, den, ekd)][1]})")
