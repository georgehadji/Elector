"""Ecological inference 2019 -> 2023 by electoral district (Ε.Δ.).

Bounded Goodman regression: party_2023/reg23 = sum_j beta_j * x_j,2019/reg19,
0 <= beta_j <= 1, weighted by registered, bootstrap CIs over districts.
beta_j ~ share of 2019 group j that voted the target party in 2023.
"""
import sqlite3
import sys

import numpy as np
from scipy.optimize import lsq_linear

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import NIKH

DB, ELECTION = sys.argv[1], sys.argv[2]  # e.g. 2023/may
c = sqlite3.connect(DB)

GROUPS19 = {"ΝΔ": [2], "ΣΥΡΙΖΑ": [4], "ΚΙΝΑΛ": [106], "ΚΚΕ": [3], "Ελλ. Λύση": [108],
            "Χρυσή Αυγή": [41], "ΜέΡΑ25": [122], "Ένωση Κεντρ.": [15], "Πλεύση": [123]}
TARGETS = {"ΝΙΚΗ": NIKH, "Ελλ. Λύση": 108, "ΝΔ": 2}
names23 = dict(c.execute("SELECT party_id,name FROM party WHERE election=?", (ELECTION,)))
names19 = dict(c.execute("SELECT party_id,name FROM party WHERE election='2019'"))
for g, ids in GROUPS19.items():
    assert all(i in names19 for i in ids), g
for t, i in TARGETS.items():
    print(f"target {t}: {names23[i]}")


def load(e):
    tot, votes = {}, {}
    for ep, den, ekd, reg, val in c.execute(
            "SELECT ep_id,den_descr,ekd_descr,SUM(registered),SUM(valid) FROM station "
            "WHERE kind='Κ' AND election=? GROUP BY 1,2,3", (e,)):
        tot[ep, den, ekd] = (reg, val)
    for ep, den, ekd, pid, v in c.execute(
            "SELECT s.ep_id,s.den_descr,s.ekd_descr,pv.party_id,SUM(pv.votes) FROM station s "
            "JOIN party_votes pv ON pv.election=s.election AND pv.tm_id=s.tm_id "
            "WHERE s.kind='Κ' AND s.election=? GROUP BY 1,2,3,4", (e,)):
        votes.setdefault((ep, den, ekd), {})[pid] = v
    return tot, votes


t19, v19 = load("2019")
t23, v23 = load(ELECTION)
keys = [k for k in t23 if k in t19 and t19[k][0] >= 50 and t23[k][0] >= 50 and t19[k][1] and t23[k][1]]
eps = {k[0] for k in keys}
print(f"{ELECTION}: {len(keys)} διαμερίσματα σε {len(eps)} περιφέρειες")

cols = list(GROUPS19) + ["Λοιπά", "Αποχή/άκυρα"]
named = {i for ids in GROUPS19.values() for i in ids}
X = np.zeros((len(keys), len(cols)))
reg23 = np.array([t23[k][0] for k in keys], float)
for r, k in enumerate(keys):
    reg, val = t19[k]
    pv = v19.get(k, {})
    for j, ids in enumerate(GROUPS19.values()):
        X[r, j] = sum(pv.get(i, 0) for i in ids) / reg
    X[r, -2] = sum(v for p, v in pv.items() if p not in named) / reg
    X[r, -1] = 1 - val / reg
X = np.clip(X, 0, 1)  # registered < valid happens in tiny districts (list changes)

rng = np.random.default_rng(0)


def fit(y, idx):
    w = np.sqrt(reg23[idx])
    return lsq_linear(X[idx] * w[:, None], y[idx] * w, bounds=(0, 1)).x


for tname, tid in TARGETS.items():
    y = np.array([v23.get(k, {}).get(tid, 0) / t23[k][0] for k in keys])
    all_idx = np.arange(len(keys))
    b = fit(y, all_idx)
    boots = np.array([fit(y, rng.integers(0, len(keys), len(keys))) for _ in range(200)])
    lo, hi = np.percentile(boots, [5, 95], axis=0)
    pred = X @ b
    ss = np.sum(reg23 * (y - pred) ** 2)
    st = np.sum(reg23 * (y - np.average(y, weights=reg23)) ** 2)
    # composition: share of the target's (fitted) votes coming from each 2019 group
    contrib = b * (X * reg23[:, None]).sum(0)
    comp = contrib / contrib.sum()
    cb = boots * (X * reg23[:, None]).sum(0)
    cb = cb / cb.sum(1, keepdims=True)
    clo, chi = np.percentile(cb, [5, 95], axis=0)
    print(f"\n=== {tname} {ELECTION}  (R²={1 - ss / st:.2f}, πραγματικό {100 * (y * reg23).sum() / reg23.sum():.2f}% "
          f"εγγεγρ., προβλεπόμενο {100 * (pred * reg23).sum() / reg23.sum():.2f}%)")
    print(f"{'ομάδα 2019':<14}{'β: % της ομάδας → ' + tname:>30}{'90% CI':>16}"
          f"{'% ψήφων ' + tname:>20}{'90% CI':>16}")
    for j, col in enumerate(cols):
        print(f"{col:<14}{100 * b[j]:>30.1f}{f'{100 * lo[j]:.1f}–{100 * hi[j]:.1f}':>16}"
              f"{100 * comp[j]:>20.1f}{f'{100 * clo[j]:.1f}–{100 * chi[j]:.1f}':>16}")
