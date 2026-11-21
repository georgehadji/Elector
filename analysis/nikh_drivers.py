"""What explains NIKH's (party 131) vote per ELSTAT community, how stable it is, and the arithmetic of the 3%.

- Weighted least squares (weights = June 2023 valid votes): NIKH June share on 2019 party shares, June turnout,
  community size (log registered) and a Macedonia/Thrace dummy. Shares in %, so a coefficient is points of NIKH per
  point of the regressor.
- Size bands: NIKH share in each election by community size (registered voters).
- Stability: weighted correlations between May 2023, June 2023 and Euro 2024 shares; votes in communities >= 3% in all.
- Turnout: registered includes emigrants and the dead, so turnout here is a relative measure, not the official one.

Run build.py <election> all first (area_match), then:
  python -I -X utf8 analysis/nikh_drivers.py data/stavroi.sqlite
"""
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import REGIONS

NIKH = 131
ELECTIONS = ["2019", "2023/may", "2023/june", "2024/euro"]
X2019 = {2: "ΝΔ", 4: "ΣΥΡΙΖΑ", 106: "ΚΙΝΑΛ", 3: "ΚΚΕ", 108: "Ελλ. Λύση", 122: "ΜέΡΑ25", 41: "Χρυσή Αυγή", 15: "Ένωση Κεντρώων"}
NORTH = {ep for name, eps in REGIONS if "Μακεδονία" in name for ep in eps}
c = sqlite3.connect(sys.argv[1])


def load(e):
    """{community: [registered, valid, {party: votes}, ep]} over stations matched to a community."""
    out = {}
    for code, reg, val, ep in c.execute(
            "SELECT a.comm_code, SUM(s.registered), SUM(s.valid), MIN(s.ep_id) FROM station s JOIN area_match a "
            "ON a.election=s.election AND a.tm_id=s.tm_id WHERE s.election=? GROUP BY 1", (e,)):
        out[code] = [reg, val, {}, ep]
    for code, pid, v in c.execute(
            "SELECT a.comm_code, pv.party_id, SUM(pv.votes) FROM party_votes pv JOIN area_match a "
            "ON a.election=pv.election AND a.tm_id=pv.tm_id WHERE pv.election=? GROUP BY 1, 2", (e,)):
        out[code][2][pid] = v
    return out


D = {e: load(e) for e in ELECTIONS}
codes = [k for k in D["2023/june"] if all(k in D[e] and D[e][k][1] >= 50 for e in ELECTIONS)]
print(f"{len(codes)} κοινότητες με ≥50 έγκυρα σε όλες τις εκλογές "
      f"({sum(D['2023/june'][k][2].get(NIKH, 0) for k in codes):,} ψήφοι ΝΙΚΗΣ Ιουνίου)")


def share(e, k, p=NIKH):
    return 100 * D[e][k][2].get(p, 0) / D[e][k][1]


def turnout(e, k):
    return 100 * D[e][k][1] / D[e][k][0] if D[e][k][0] else 0


w = np.array([D["2023/june"][k][1] for k in codes], float)
y = np.array([share("2023/june", k) for k in codes])


def wls(cols, names):
    X = np.column_stack([np.ones(len(codes)), *cols])
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    res = y - X @ beta
    ybar = np.average(y, weights=w)
    r2 = 1 - np.sum(w * res ** 2) / np.sum(w * (y - ybar) ** 2)
    # shortcut: plain WLS SE ignore spatial correlation, fine for ranking effects, not for significance tests
    sigma2 = np.sum(w * res ** 2) / (len(codes) - X.shape[1])
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv((X * w[:, None]).T @ X)))
    return beta, se, r2, names


xs = {n: np.array([share("2019", k, p) for k in codes]) for p, n in X2019.items()}
north = np.array([float(D["2023/june"][k][3] in NORTH) for k in codes])
turn = np.array([turnout("2023/june", k) for k in codes])
size = np.array([math.log10(max(D["2023/june"][k][0], 1)) for k in codes])
models = {
    "μόνο Μακεδονία/Θράκη": wls([north], ["Μακεδονία/Θράκη"]),
    "μόνο κόμματα 2019": wls(list(xs.values()), list(xs)),
    "όλα": wls([*xs.values(), north, turn, size], [*xs, "Μακεδονία/Θράκη", "συμμετοχή Ιουν.", "log10 εγγεγραμμένων"]),
}
print("\nΠαλινδρόμηση (WLS): ποσοστό ΝΙΚΗΣ Ιουνίου 2023 ανά κοινότητα")
for label, (beta, se, r2, names) in models.items():
    print(f"  {label}: R² = {r2:.2f}")
beta, se, r2, names = models["όλα"]
for n, b, s in zip(["σταθερά", *names], beta, se, strict=True):
    print(f"    {n:<22}{b:+7.3f}  (±{s:.3f})")

print("\nΑνά μέγεθος κοινότητας (εγγεγραμμένοι Ιουνίου): ποσοστό ΝΙΚΗΣ Μάιος / Ιούνιος / Ευρωεκλογές, μερίδιο ψήφων")
bands = [(0, 500), (500, 2000), (2000, 10000), (10000, 50000), (50000, 10 ** 9)]
total_j = sum(D["2023/june"][k][2].get(NIKH, 0) for k in codes)
for lo, hi in bands:
    ks = [k for k in codes if lo <= D["2023/june"][k][0] < hi]
    agg = {e: (sum(D[e][k][2].get(NIKH, 0) for k in ks), sum(D[e][k][1] for k in ks)) for e in ELECTIONS[1:]}
    pc = " / ".join(f"{100 * n / v:.2f}%" for n, v in agg.values())
    tj = sum(D["2023/june"][k][1] for k in ks) / sum(D["2023/june"][k][0] for k in ks)
    print(f"  {lo:>6,}–{hi if hi < 10 ** 9 else '∞':<7} {len(ks):>5} κοιν.  {pc}   "
          f"{100 * agg['2023/june'][0] / total_j:4.1f}% των ψήφων, συμμετοχή {100 * tj:.0f}%")

print("\nΣταθερότητα (σταθμισμένη συσχέτιση ποσοστών ανά κοινότητα)")
s = {e: np.array([share(e, k) for k in codes]) for e in ELECTIONS[1:]}


def wcorr(a, b):
    ma, mb = np.average(a, weights=w), np.average(b, weights=w)
    return np.average((a - ma) * (b - mb), weights=w) / math.sqrt(np.average((a - ma) ** 2, weights=w) *
                                                                   np.average((b - mb) ** 2, weights=w))


print(f"  Μάιος–Ιούνιος {wcorr(s['2023/may'], s['2023/june']):.2f}, Ιούνιος–Ευρωεκλογές "
      f"{wcorr(s['2023/june'], s['2024/euro']):.2f}, Μάιος–Ευρωεκλογές {wcorr(s['2023/may'], s['2024/euro']):.2f}")
allk = [k for k in codes if all(share(e, k) >= 3 for e in ELECTIONS[1:])]
v = sum(D["2023/june"][k][2].get(NIKH, 0) for k in allk)
print(f"  ≥3% και στις τρεις εκλογές: {len(allk)} κοινότητες, {v:,} ψήφοι Ιουνίου ({100 * v / total_j:.0f}%)")

print("\nΣυμμετοχή")
print(f"  συσχέτιση ποσοστού ΝΙΚΗΣ με συμμετοχή Ιουνίου: {wcorr(y, turn):+.2f}")
d_turn = np.array([turnout("2024/euro", k) - turnout("2023/june", k) for k in codes])
d_nikh = s["2024/euro"] - s["2023/june"]
print(f"  συσχέτιση μεταβολής ΝΙΚΗΣ με μεταβολή συμμετοχής (Ιούν. → Ευρ.): {wcorr(d_nikh, d_turn):+.2f}")
for label, ks in (("κάστρα (≥6% Ιουν.)", [k for k in codes if share("2023/june", k) >= 6]), ("όλες", codes)):
    tj = 100 * sum(D["2023/june"][k][1] for k in ks) / sum(D["2023/june"][k][0] for k in ks)
    te = 100 * sum(D["2024/euro"][k][1] for k in ks) / sum(D["2024/euro"][k][0] for k in ks)
    print(f"  {label}: έγκυρα/εγγεγραμμένοι Ιουνίου {tj:.1f}%, Ευρωεκλογών {te:.1f}%")

print("\nΑριθμητική του 3% (έγκυρα όπως στη βάση, χωρίς επιστολικές)")
nat = {e: c.execute("SELECT SUM(valid) FROM station WHERE election=?", (e,)).fetchone()[0] for e in ELECTIONS}
nv = {e: c.execute("SELECT SUM(votes) FROM party_votes WHERE election=? AND party_id=?", (e, NIKH)).fetchone()[0]
      for e in ELECTIONS[1:]}
for e in ("2023/june", "2024/euro"):
    print(f"  {e}: έγκυρα {nat[e]:,}, 3% = {0.03 * nat[e]:,.0f}, ΝΙΚΗ {nv[e]:,} ({100 * nv[e] / nat[e]:.2f}%)")
for pct in (0.6, 1.0, 1.7):
    print(f"  δημοσκόπηση {pct}% με έγκυρα Ιουνίου: {pct / 100 * nat['2023/june']:,.0f} ψήφοι, "
          f"λείπουν {(0.03 - pct / 100) * nat['2023/june']:,.0f}")
