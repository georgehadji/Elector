"""Types of community by vote profile (k-means), and where NIKH (party 131) lost votes in each.

Per ELSTAT community (>= 50 valid votes in June 2023 and Euro 2024, matched by area_match), 8 standardised variables:
June 2023 shares of NIKH, Ελλ. Λύση, Σπαρτιάτες, ΝΔ, ΚΚΕ; abstention in June 2023 (1 - valid / registered, a relative
measure); change of NIKH's share June 2023 -> Euro 2024 (points); log10 of registered voters.
k-means (k-means++ start, 10 restarts, seed fixed) for k = 4..8, k chosen by the mean silhouette. Clusters are
unweighted places: the tables then weight by votes. Unofficial results.

Run build.py <election> all first (area_match), then:
  python -I -X utf8 analysis/nikh_clusters.py data/stavroi.sqlite
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import REGIONS

NIKH = 131
J, E = "2023/june", "2024/euro"
VARS = {131: "ΝΙΚΗ", 108: "Ελλ. Λύση", 157: "Σπαρτιάτες", 2: "ΝΔ", 3: "ΚΚΕ"}
rng = np.random.default_rng(2026)


def kmeans(X, k, n_init=10, iters=100):
    """Labels and inertia of the best of n_init k-means++ runs."""
    best = None
    for _ in range(n_init):
        cen = X[[rng.integers(len(X))]]
        for _ in range(k - 1):
            d2 = ((X[:, None, :] - cen[None]) ** 2).sum(2).min(1)
            cen = np.vstack([cen, X[rng.choice(len(X), p=d2 / d2.sum())]])
        for _ in range(iters):
            lab = ((X[:, None, :] - cen[None]) ** 2).sum(2).argmin(1)
            new = np.array([X[lab == i].mean(0) if (lab == i).any() else cen[i] for i in range(k)])
            if np.allclose(new, cen):
                break
            cen = new
        inertia = ((X - cen[lab]) ** 2).sum()
        if best is None or inertia < best[1]:
            best = (lab, inertia)
    return best


def silhouette(X, lab, k, chunk=500):
    """Mean silhouette, in chunks so the distance matrix stays small."""
    onehot = np.eye(k)[lab]
    size = onehot.sum(0)
    out = np.empty(len(X))
    for s in range(0, len(X), chunk):
        d = np.sqrt(((X[s:s + chunk, None, :] - X[None]) ** 2).sum(2)) @ onehot
        own = lab[s:s + chunk]
        a = d[np.arange(len(d)), own] / np.maximum(size[own] - 1, 1)
        d = d / size
        d[np.arange(len(d)), own] = np.inf
        out[s:s + chunk] = (d.min(1) - a) / np.maximum(a, d.min(1))
    return out.mean()


# self-check: two far-apart blobs are recovered with silhouette close to 1
_X = np.vstack([rng.normal(0, .1, (50, 2)), rng.normal(5, .1, (50, 2))])
_lab, _ = kmeans(_X, 2, n_init=3)
assert len(set(_lab[:50])) == 1 and len(set(_lab[50:])) == 1 and _lab[0] != _lab[-1] and silhouette(_X, _lab, 2) > 0.9

c = sqlite3.connect(sys.argv[1])
region = {ep: name for name, eps in REGIONS for ep in eps}


def load(e):
    """{community: [registered, valid, ep, {party: votes}]}"""
    out = {k: [r, v, ep, {}] for k, r, v, ep in c.execute(
        "SELECT a.comm_code, SUM(s.registered), SUM(s.valid), MIN(s.ep_id) FROM station s JOIN area_match a "
        "ON a.election=s.election AND a.tm_id=s.tm_id WHERE s.election=? GROUP BY 1", (e,))}
    for k, p, v in c.execute(
            "SELECT a.comm_code, pv.party_id, SUM(pv.votes) FROM party_votes pv JOIN area_match a ON a.election=pv.election "
            f"AND a.tm_id=pv.tm_id WHERE pv.election=? AND pv.party_id IN ({','.join(map(str, VARS))}) GROUP BY 1, 2", (e,)):
        out[k][3][p] = v
    return out


dj, de = load(J), load(E)
codes = [k for k in dj if k in de and dj[k][0] > 0 and dj[k][1] >= 50 and de[k][1] >= 50 and dj[k][2] in region]
R = np.array([dj[k][0] for k in codes], float)
VJ, VE = (np.array([d[k][1] for k in codes], float) for d in (dj, de))
EP = np.array([dj[k][2] for k in codes])
sh = {p: 100 * np.array([dj[k][3].get(p, 0) for k in codes], float) / VJ for p in VARS}
nj = np.array([dj[k][3].get(NIKH, 0) for k in codes], float)
ne = np.array([de[k][3].get(NIKH, 0) for k in codes], float)
X = np.column_stack([*sh.values(), 100 * (1 - VJ / R), 100 * ne / VE - 100 * nj / VJ, np.log10(R)])
names = [*VARS.values(), "αποχή Ιουν.", "μεταβολή ΝΙΚΗΣ", "log10 εγγεγρ."]
Z = (X - X.mean(0)) / X.std(0)
print(f"{len(codes)} κοινότητες, {len(names)} μεταβλητές: {', '.join(names)}")

print("\nk-means: μέση silhouette (υψηλότερη = πιο καθαρός διαχωρισμός)")
fits = {}
for k in range(4, 9):
    lab, inertia = kmeans(Z, k)
    fits[k] = lab
    print(f"  k = {k}: {silhouette(Z, lab, k):.3f}")
k = max(fits, key=lambda k: silhouette(Z, fits[k], k))
lab = fits[k]
print(f"Επιλέγεται k = {k}.")



def ari(a, b):
    """Adjusted Rand index of two labelings (1 = identical partitions, 0 = chance)."""
    t = np.zeros((a.max() + 1, b.max() + 1))
    np.add.at(t, (a, b), 1)
    c2 = lambda x: (x * (x - 1) / 2).sum()
    exp = c2(t.sum(1)) * c2(t.sum(0)) / c2(np.array([len(a)]))
    return (c2(t) - exp) / ((c2(t.sum(1)) + c2(t.sum(0))) / 2 - exp)


assert ari(np.array([0, 0, 1, 1]), np.array([1, 1, 0, 0])) == 1
# check: are the types stable? k-means again from 5 other seeds, and the "stronghold" type (highest NIKH share) each time
print(f"\nΣταθερότητα των τύπων (k = {k}, 5 άλλοι σπόροι): ARI με την επιλεγμένη λύση, και ο τύπος με το υψηλότερο ποσοστό ΝΙΚΗΣ")
for seed in range(1, 6):
    rng = np.random.default_rng(seed)
    l2, _ = kmeans(Z, k)
    top = max(range(k), key=lambda i: nj[l2 == i].sum() / VJ[l2 == i].sum())
    m = l2 == top
    print(f"  σπόρος {seed}: ARI {ari(lab, l2):.2f}· κάστρα: {m.sum()} κοιν., {100 * nj[m].sum() / nj.sum():.0f}% των ψήφων ΝΙΚΗΣ, "
          f"κράτησε {100 * ne[m].sum() / nj[m].sum():.0f}%, χαμένες ανά 1000 εγγ. {1000 * (nj[m] - ne[m]).sum() / R[m].sum():.1f}")

tot_nj, tot_loss = nj.sum(), (nj - ne).sum()
print(f"\nΤύποι κοινοτήτων (σταθμισμένοι με ψήφους Ιουνίου 2023). Σύνολο ΝΙΚΗ {tot_nj:,.0f} → {ne.sum():,.0f}, καθαρή απώλεια {tot_loss:,.0f}")
print(f"  {'τύπος':<6}{'κοιν.':>6}{'ψήφοι ΝΙΚΗΣ':>12}{'%':>5}{'ΝΙΚΗ Ιούν.':>11}{'Ευρ.':>6}{'κράτησε':>9}{'Ελ.Λ.':>7}{'Σπαρτ.':>8}{'ΝΔ':>6}"
      f"{'ΚΚΕ':>6}{'αποχή':>7}{'εγγ. διάμ.':>11}{'χαμένες':>9}{'ανά 1000 εγγ.':>14}")
order = np.argsort([-nj[lab == i].sum() for i in range(k)])
for rank, i in enumerate(order, 1):
    m = lab == i
    v, nn, ee = VJ[m].sum(), nj[m].sum(), ne[m].sum()
    print(f"  {rank:<6}{m.sum():>6}{nn:>12,.0f}{100 * nn / tot_nj:>5.0f}{100 * nn / v:>10.2f}%{100 * ee / VE[m].sum():>5.2f}%{100 * ee / nn:>8.0f}%"
          f"{sh[108][m].dot(VJ[m]) / v:>7.1f}{sh[157][m].dot(VJ[m]) / v:>8.1f}{sh[2][m].dot(VJ[m]) / v:>6.1f}"
          f"{sh[3][m].dot(VJ[m]) / v:>6.1f}{100 * (1 - v / R[m].sum()):>7.0f}{np.median(R[m]):>11,.0f}{nn - ee:>9,.0f}"
          f"{1000 * (nn - ee) / R[m].sum():>14.1f}")
print("  (% ψήφων, ποσοστά σε % των έγκυρων· κράτησε = ΝΙΚΗ Ευρ. / ΝΙΚΗ Ιούν.· χαμένες = καθαρή απώλεια ψήφων)")

print("\nΠεριφέρειες ανά τύπο (οι 3 με τις περισσότερες ψήφους ΝΙΚΗΣ Ιουνίου):")
for rank, i in enumerate(order, 1):
    m = lab == i
    by = {}
    for ep, n in zip(EP[m], nj[m], strict=True):
        by[region[ep]] = by.get(region[ep], 0) + n
    print(f"  {rank}: " + ", ".join(f"{r} {100 * n / nj[m].sum():.0f}%" for r, n in sorted(by.items(), key=lambda x: -x[1])[:3]))
