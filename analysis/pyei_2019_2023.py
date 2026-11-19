"""Bayesian R x C ecological inference 2019 -> 2023 with PyEI, by municipal unit.

Rows: 2019 parties (+ others, abstention/invalid) as shares of 2019 registered.
Columns: 2023 parties (+ others, abstention/invalid) as shares of 2023 registered.
Unit: (constituency, municipal unit) present in both elections, ordinary stations only.

Needs pyei (pymc). Run:
  python -I -X utf8 analysis/pyei_2019_2023.py data/stavroi.sqlite 2023/may [max_units]
"""
import sqlite3
import sys

import numpy as np
from pyei.r_by_c import RowByColumnEI

DB, ELECTION = sys.argv[1], sys.argv[2]
MAX_UNITS = int(sys.argv[3]) if len(sys.argv) > 3 else None
c = sqlite3.connect(DB)

ROWS = {"ΝΔ": 2, "ΣΥΡΙΖΑ": 4, "ΚΙΝΑΛ": 106, "ΚΚΕ": 3, "Ελλ. Λύση": 108, "Χρυσή Αυγή": 41,
        "ΜέΡΑ25": 122, "Ένωση Κεντρ.": 15, "Πλεύση": 123}
COLS = {"ΝΙΚΗ": 131, "ΝΔ": 2, "ΣΥΡΙΖΑ": 4, "ΠΑΣΟΚ": 106, "ΚΚΕ": 3, "Ελλ. Λύση": 108,
        "Πλεύση": 123, "ΜέΡΑ25": 122}
if ELECTION == "2023/june":
    COLS["Σπαρτιάτες"] = 157


def load(e):
    tot, votes = {}, {}
    for ep, den, reg, val in c.execute(
            "SELECT ep_id,den_descr,SUM(registered),SUM(valid) FROM station "
            "WHERE kind='Κ' AND election=? GROUP BY 1,2", (e,)):
        tot[ep, den] = (reg, val)
    for ep, den, pid, v in c.execute(
            "SELECT s.ep_id,s.den_descr,pv.party_id,SUM(pv.votes) FROM station s "
            "JOIN party_votes pv ON pv.election=s.election AND pv.tm_id=s.tm_id "
            "WHERE s.kind='Κ' AND s.election=? GROUP BY 1,2,3", (e,)):
        votes.setdefault((ep, den), {})[pid] = v
    return tot, votes


def fractions(tot, votes, keys, parties):
    """(len(parties)+2, n) shares of registered: parties, others, abstention/invalid."""
    out = np.zeros((len(parties) + 2, len(keys)))
    ids = set(parties.values())
    for i, k in enumerate(keys):
        reg, val = tot[k]
        val = min(val, reg)  # registered < valid in a few units (list changes)
        pv = votes.get(k, {})
        out[:-2, i] = [pv.get(p, 0) for p in parties.values()]
        out[-2, i] = sum(v for p, v in pv.items() if p not in ids)
        out[:-1, i] *= val / max(out[:-1, i].sum(), 1)  # scale party votes to valid
        out[-1, i] = reg - val
        out[:, i] /= reg
    return out


t19, v19 = load("2019")
t23, v23 = load(ELECTION)
keys = sorted(k for k in t23 if k in t19 and t19[k][0] >= 100 and t23[k][0] >= 100)
if MAX_UNITS:  # quick runtime test on a random subset
    pick = np.random.default_rng(0).choice(len(keys), MAX_UNITS, replace=False)
    keys = [keys[i] for i in sorted(pick)]
print(f"{ELECTION}: {len(keys)} δημοτικές ενότητες σε {len({k[0] for k in keys})} περιφέρειες")

row_names = list(ROWS) + ["Λοιπά", "Αποχή/άκυρα"]
col_names = list(COLS) + ["Λοιπά", "Αποχή/άκυρα"]
X = fractions(t19, v19, keys, ROWS)
Y = fractions(t23, v23, keys, COLS)
pops = np.array([t23[k][0] for k in keys])
assert np.allclose(X.sum(0), 1) and np.allclose(Y.sum(0), 1)

ei = RowByColumnEI(model_name="multinomial-dirichlet-modified", pareto_shape=100, pareto_scale=100)
ei.fit(X, Y, pops, demographic_group_names=row_names, candidate_names=col_names,
       draws=1000, tune=1000, chains=4, target_accept=0.9, random_seed=0)  # PyEI samples with numpyro

prefs = ei.sampled_voting_prefs  # (samples, rows, cols), group-population weighted
grp_pop = (X * pops).sum(1)  # people in each 2019 group (on 2023 registered base)
col_pop = (Y * pops).sum(1)


def table(target):
    j = col_names.index(target)
    b = prefs[:, :, j]
    comp = b * grp_pop / col_pop[j]
    print(f"\n=== {target} {ELECTION}  (πραγματικό {100 * col_pop[j] / pops.sum():.2f}% εγγεγρ.)")
    print(f"{'ομάδα 2019':<14}{'% ομάδας → ' + target:>22}{'90% CrI':>14}{'% ψήφων ' + target:>20}{'90% CrI':>14}")
    for r, name in enumerate(row_names):
        lo, hi = np.percentile(b[:, r], [5, 95])
        clo, chi = np.percentile(comp[:, r], [5, 95])
        print(f"{name:<14}{100 * b[:, r].mean():>22.1f}{f'{100 * lo:.1f}–{100 * hi:.1f}':>14}"
              f"{100 * comp[:, r].mean():>20.1f}{f'{100 * clo:.1f}–{100 * chi:.1f}':>14}")
    print(f"(άθροισμα σύνθεσης {100 * comp.sum(1).mean():.1f}%)")


for t in ("ΝΙΚΗ", "ΝΔ", "Ελλ. Λύση"):
    table(t)
