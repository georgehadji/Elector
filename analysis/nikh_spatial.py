"""Spatial clustering of NIKH (party 131) votes per ELSTAT community: Moran's I and Getis-Ord Gi*.

- Neighbours: communities sharing at least one boundary vertex (queen contiguity from data/koinotites_2021.json).
  Communities with no neighbour among the analysed ones (islands) are left out.
- Global Moran's I (row-standardised weights, 999 random permutations) for NIKH share in June 2023, Euro 2024 and
  the change between them (points of share).
- Gi* of the June 2023 share (binary weights including the place itself). Hot = z >= 2.58. Hot communities that touch
  form a cluster. Clusters are ranked by NIKH June 2023 votes.
- The 40 biggest zone A units of nikh_pareto.py (same tiers): how much of each unit's NIKH vote is in hot communities.
- Cluster-robust (by municipal unit) standard errors for the abstention slope of nikh_abstention.py.
- Checks at the end: hot spots under Benjamini-Hochberg FDR 5%; Moran's I of retention; Moran's I with the left-out
  communities linked to their 3 nearest centroids.
Shares of small communities are noisy: >= 50 valid votes in both elections. Unofficial results.

Run build.py <election> all first (area_match), then:
  python -I -X utf8 analysis/nikh_spatial.py data/stavroi.sqlite
"""
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import NIKH, REGIONS
from matching import boundaries

J, E, M = "2023/june", "2024/euro", "2023/may"
HOT = 2.58
c = sqlite3.connect(sys.argv[1])
region = {ep: name for name, eps in REGIONS for ep in eps}
ep_name = dict(c.execute("SELECT ep_id, name FROM ep WHERE election=?", (J,)))


def moran(x, ia, ja, w):
    """Moran's I with weights w on pairs (ia, ja); row-standardised, so sum(w) = n."""
    z = x - x.mean()
    return (w * z[ia] * z[ja]).sum() / (z * z).sum()


# self-check: chain 0-1-2-3 with increasing values, I = 0.4 by hand
_I, _J = np.array([0, 1, 1, 2, 2, 3]), np.array([1, 0, 2, 1, 3, 2])
assert abs(moran(np.array([1., 2, 3, 4]), _I, _J, np.array([1, .5, .5, .5, .5, 1])) - 0.4) < 1e-9


def load(e):
    """{community: [registered, valid, NIKH votes, ep, unit]}"""
    return {k: [r, v, n or 0, ep, den] for k, r, v, n, ep, den in c.execute(
        "SELECT a.comm_code, SUM(s.registered), SUM(s.valid), SUM((SELECT votes FROM party_votes p WHERE p.election=s.election "
        "AND p.tm_id=s.tm_id AND p.party_id=?)), MIN(s.ep_id), MIN(s.den_descr) FROM station s JOIN area_match a "
        "ON a.election=s.election AND a.tm_id=s.tm_id WHERE s.election=? GROUP BY 1", (NIKH, e))}


dj, de = load(J), load(E)
_, comm, _ = boundaries()
verts = defaultdict(set)
for code, f in comm.items():
    g = f["geometry"]
    for poly in g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]:
        for ring in poly:
            for pt in ring:
                verts[tuple(pt)].add(code)
adj = defaultdict(set)
for s in verts.values():
    for a in s:
        adj[a] |= s - {a}

ok = {k for k in dj if k in de and dj[k][0] > 0 and dj[k][1] >= 50 and de[k][1] >= 50 and dj[k][3] in region}
codes = sorted(k for k in ok if adj[k] & ok)
island = len(ok) - len(codes)
pos = {k: i for i, k in enumerate(codes)}
n = len(codes)
pairs = [(pos[a], pos[b]) for a in codes for b in adj[a] & set(codes)]
ia = np.array([p[0] for p in pairs])
ja = np.array([p[1] for p in pairs])
deg = np.bincount(ia, minlength=n).astype(float)
w = 1 / deg[ia]
print(f"{n} κοινότητες με γείτονες (έξω {island} νησιά/απομονωμένες), {len(pairs) // 2} σύνορα, μέσος αριθμός γειτόνων {deg.mean():.1f}")

nj = np.array([dj[k][2] for k in codes], float)
vj = np.array([dj[k][1] for k in codes], float)
ne = np.array([de[k][2] for k in codes], float)
ve = np.array([de[k][1] for k in codes], float)
sj, se = 100 * nj / vj, 100 * ne / ve
rng = np.random.default_rng(2026)
print("\nGlobal Moran's I (αναμενόμενο ≈ 0), 999 τυχαίες μεταθέσεις")
for label, x in (("ποσοστό ΝΙΚΗΣ Ιούνιος 2023", sj), ("ποσοστό ΝΙΚΗΣ Ευρωεκλογές 2024", se),
                 ("μεταβολή ποσοστού Ιούν. → Ευρ. (μονάδες)", se - sj)):
    obs = moran(x, ia, ja, w)
    sim = np.array([moran(rng.permutation(x), ia, ja, w) for _ in range(999)])
    print(f"  {label:<44} I = {obs:+.3f}  (τυχαία: {sim.mean():+.3f} ± {sim.std():.3f}, p = {(1 + (sim >= obs).sum()) / 1000:.3f})")

# Gi*, binary weights including the place itself
lag = sj.copy()
np.add.at(lag, ia, sj[ja])
ws = 1 + deg
xbar, S = sj.mean(), sj.std()
gz = (lag - xbar * ws) / (S * np.sqrt((n * ws - ws ** 2) / (n - 1)))
hot = gz >= HOT
tot = nj.sum()
print(f"\nGi* ποσοστού Ιουνίου 2023: {hot.sum()} θερμές κοινότητες (z ≥ {HOT}), {nj[hot].sum():,.0f} ψήφοι ΝΙΚΗΣ "
      f"({100 * nj[hot].sum() / tot:.0f}% του συνόλου) σε {100 * vj[hot].sum() / vj.sum():.0f}% των έγκυρων. "
      f"Ψυχρές (z ≤ -{HOT}): {(gz <= -HOT).sum()}")

# clusters = connected hot communities
cl = -np.ones(n, int)
nxt = 0
nbr = defaultdict(list)
for a, b in zip(ia, ja, strict=True):
    nbr[a].append(b)
for s in np.flatnonzero(hot):
    if cl[s] >= 0:
        continue
    cl[s], stack = nxt, [s]
    while stack:
        for t in nbr[stack.pop()]:
            if hot[t] and cl[t] < 0:
                cl[t] = nxt
                stack.append(t)
    nxt += 1
rows = []
for g in range(nxt):
    m = np.flatnonzero(cl == g)
    byunit = defaultdict(float)
    for i in m:
        byunit[dj[codes[i]][3], dj[codes[i]][4]] += nj[i]
    rows.append((nj[m].sum(), len(m), g, sorted(byunit, key=byunit.get, reverse=True)[:3]))
rows.sort(reverse=True)
print(f"\n{nxt} συστάδες. Οι 12 μεγαλύτερες κατά ψήφους ΝΙΚΗΣ Ιουνίου (σωρευτικά ως % των θερμών ψήφων):")
acc = 0
for v, m, g, us in rows[:12]:
    acc += v
    print(f"  {v:>7,.0f} ψήφοι, {m:>4} κοιν., σωρ. {100 * acc / nj[hot].sum():>3.0f}%  {region[us[0][0]]}: " +
          ", ".join(den for _, den in us))
for k in (5, 10, 20):
    print(f"  οι {k} μεγαλύτερες συστάδες: {sum(r[0] for r in rows[:k]):,.0f} ψήφοι ({100 * sum(r[0] for r in rows[:k]) / tot:.0f}% του συνόλου)")

# units and tiers as in nikh_pareto.py
U = {}
for e in (J, E, M):
    for ep, den, r, nv in c.execute(
            "SELECT s.ep_id, s.den_descr, SUM(s.registered), SUM((SELECT votes FROM party_votes p WHERE p.election=s.election "
            "AND p.tm_id=s.tm_id AND p.party_id=?)) FROM station s WHERE s.election=? AND s.den_descr IS NOT NULL GROUP BY 1, 2",
            (NIKH, e)):
        u = U.setdefault((ep, den), {"reg": 0, "peak": 0})
        if e == J:
            u["reg"] = r or 0
        u["peak"] = max(u["peak"], nv or 0)
units = sorted((k for k in U if U[k]["reg"]), key=lambda k: -U[k]["peak"] / U[k]["reg"])
REG = sum(U[k]["reg"] for k in units)
acc, tier = 0, {}
for k in units:
    acc += U[k]["reg"]
    tier[k] = "A" if acc <= 0.2 * REG else "B" if acc <= 0.5 * REG else "C"
inhot, allv = defaultdict(float), defaultdict(float)
for i, k in enumerate(codes):
    allv[dj[k][3], dj[k][4]] += nj[i]
    if hot[i]:
        inhot[dj[k][3], dj[k][4]] += nj[i]
top = sorted((k for k in units if tier[k] == "A"), key=lambda k: -U[k]["peak"])[:40]
print("\nΟι 40 μεγαλύτερες ενότητες της ζώνης Α: ποσοστό ψήφων Ιουνίου σε θερμές κοινότητες")
in_hot = 0
for k in top:
    f = inhot[k] / allv[k] if allv[k] else 0
    in_hot += f >= 0.5
    print(f"  {k[1][:26]:<27}{ep_name[k[0]][:24]:<25}κορυφή {U[k]['peak']:>6,}  σε θερμές {100 * f:>3.0f}%")
print(f"  ≥50% σε θερμές: {in_hot} από {len(top)}")
a_hot = sum(inhot[k] for k in units if tier[k] == "A")
print(f"  Ζώνη Α: {100 * a_hot / sum(inhot.values()):.0f}% των ψήφων των θερμών κοινοτήτων, "
      f"{100 * sum(allv[k] for k in units if tier[k] == 'A') / sum(allv.values()):.0f}% των ψήφων όλων των κοινοτήτων")


def robust(y, x, wt, groups):
    """Slope of y on x (WLS weights wt) with plain and cluster-robust SE."""
    X = np.column_stack([np.ones(len(y)), x])
    bread = np.linalg.inv((X * wt[:, None]).T @ X)
    beta = bread @ (X * wt[:, None]).T @ y
    e = y - X @ beta
    sc = defaultdict(lambda: np.zeros(2))
    for g, row in zip(groups, X * (wt * e)[:, None], strict=True):
        sc[g] += row
    meat = sum(np.outer(s, s) for s in sc.values())
    plain = np.sqrt(np.sum(wt * e ** 2) / (len(y) - 2) * bread[1, 1])
    return beta[1], plain, np.sqrt((bread @ meat @ bread)[1, 1])


R = np.array([dj[k][0] for k in codes], float)
dv, dn = (ve - vj) / R, (ne - nj) / R
print("\nΚλίση b της ΝΙΚΗΣ στη μεταβολή έγκυρων (ανάλυση αποχής): σφάλμα απλό → ανά δημοτική ενότητα")
grp = [(dj[k][3], dj[k][4]) for k in codes]
for label, m in (("εθνικά", np.ones(n, bool)),
                 ("Κεντρική Μακεδονία", np.array([region[dj[k][3]] == "Κεντρική Μακεδονία" for k in codes]))):
    b, s1, s2 = robust(dn[m], dv[m], R[m], [g for g, f in zip(grp, m, strict=True) if f])
    print(f"  {label:<20}b = {b:+.3f}  ±{s1:.3f} → ±{s2:.3f}")

# --- checks ---
# 1. Gi* hot spots under Benjamini-Hochberg FDR 5% instead of the uncorrected z >= 2.58
pv = np.array([0.5 * math.erfc(z / math.sqrt(2)) for z in gz])
srt = np.sort(pv)
passed = np.flatnonzero(srt <= 0.05 * np.arange(1, n + 1) / n)
cut = srt[passed[-1]] if len(passed) else -1
fdr = pv <= cut
print(f"\nΈλεγχος πολλαπλών συγκρίσεων (Benjamini-Hochberg, FDR 5%): {fdr.sum()} θερμές κοινότητες (z ≥ {gz[fdr].min():.2f}), "
      f"{nj[fdr].sum():,.0f} ψήφοι ΝΙΚΗΣ ({100 * nj[fdr].sum() / tot:.0f}% του συνόλου). Από τις {hot.sum()} με z ≥ {HOT} μένουν {(hot & fdr).sum()}.")

# 2. Moran's I of retention (Euro votes / June votes, log, +1 so that zeros stay defined)
ret = np.log((ne + 1) / (nj + 1))
obs = moran(ret, ia, ja, w)
sim = np.array([moran(rng.permutation(ret), ia, ja, w) for _ in range(999)])
print(f"Συγκράτηση (log ψήφων Ευρ. / Ιουν.): I = {obs:+.3f}  (τυχαία: {sim.mean():+.3f} ± {sim.std():.3f}, p = {(1 + (sim >= obs).sum()) / 1000:.3f})")

# 3. the communities left out (no neighbour by shared vertex): link each to its 3 nearest centroids and recompute
cen = {}
for k in ok:
    g = comm[k]["geometry"]
    pts = np.array([pt for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]) for ring in poly for pt in ring])
    cen[k] = pts.mean(0)
allc = sorted(ok)
P = np.array([cen[k] for k in allc])
p2 = {k: i for i, k in enumerate(allc)}
adj2 = {k: set(adj[k] & ok) for k in allc}
for k in allc:
    if not adj2[k]:
        for j in np.argsort(((P - cen[k]) ** 2).sum(1))[1:4]:
            adj2[k].add(allc[j])
            adj2[allc[j]].add(k)
pr = [(p2[a], p2[b]) for a in allc for b in adj2[a]]
i2, j2 = np.array([p[0] for p in pr]), np.array([p[1] for p in pr])
x2 = np.array([100 * dj[k][2] / dj[k][1] for k in allc])
print(f"Με τις {island} απομονωμένες (3 πλησιέστερα κέντρα ως γείτονες), {len(allc)} κοινότητες: I ποσοστού Ιουνίου = "
      f"{moran(x2, i2, j2, 1 / np.bincount(i2, minlength=len(allc))[i2]):+.3f}")
