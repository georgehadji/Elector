"""Bayesian R x C ecological inference between two elections with PyEI, by municipal unit.

Rows: base-election parties (+ others, abstention/invalid) as shares of base registered.
Columns: target-election parties (+ others, abstention/invalid) as shares of target registered.
Unit: (constituency, municipal unit) present in both elections, ordinary stations only.

Needs pyei (pymc). Run:
  python -I -X utf8 analysis/pyei_2019_2023.py data/stavroi.sqlite <target> [base] [max_units] [--full]
  target: 2023/may | 2023/june | 2024/euro; base: 2019 (default) | 2023/may | 2023/june
  Default: compact rows/columns (small parties in "Λοιπά") and longer sampling, so the chains converge.
  --full: the first runs' larger tables (analysis/pyei_*.txt, which did not converge).
"""
import os
import sqlite3
import sys

os.environ.setdefault("XLA_FLAGS", "--xla_force_host_platform_device_count=4")  # 4 CPU devices -> parallel chains

import numpy as np
from pyei.r_by_c import RowByColumnEI

FULL = "--full" in sys.argv
args = [a for a in sys.argv[1:] if a != "--full"]
DB, ELECTION = args[0], args[1]
BASE = args[2] if len(args) > 2 else "2019"
MAX_UNITS = int(args[3]) if len(args) > 3 else None
c = sqlite3.connect(DB)

ROWS = {
    "2019": {"ΝΔ": 2, "ΣΥΡΙΖΑ": 4, "ΚΙΝΑΛ": 106, "ΚΚΕ": 3, "Ελλ. Λύση": 108, "Χρυσή Αυγή": 41,
             "ΜέΡΑ25": 122, "Ένωση Κεντρ.": 15, "Πλεύση": 123},
    "2023/may": {"ΝΙΚΗ": 131, "ΝΔ": 2, "ΣΥΡΙΖΑ": 4, "ΠΑΣΟΚ": 106, "ΚΚΕ": 3, "Ελλ. Λύση": 108,
                 "Πλεύση": 123, "ΜέΡΑ25": 122},  # no Spartiates in May
    "2023/june": {"ΝΙΚΗ": 131, "ΝΔ": 2, "ΣΥΡΙΖΑ": 4, "ΠΑΣΟΚ": 106, "ΚΚΕ": 3, "Ελλ. Λύση": 108,
                  "Σπαρτιάτες": 157, "Πλεύση": 123, "ΜέΡΑ25": 122},
}[BASE] if FULL else {
    "2019": {"ΝΔ": 2, "ΣΥΡΙΖΑ": 4, "Ελλ. Λύση": 108, "Χρυσή Αυγή": 41, "Ένωση Κεντρ.": 15},
    "2023/may": {"ΝΙΚΗ": 131, "ΝΔ": 2, "ΣΥΡΙΖΑ": 4, "Ελλ. Λύση": 108},
    "2023/june": {"ΝΙΚΗ": 131, "ΝΔ": 2, "ΣΥΡΙΖΑ": 4, "Ελλ. Λύση": 108, "Σπαρτιάτες": 157},
}[BASE]
# few columns keeps the R x C model tractable (rows carry the detail we care about)
COLS = {"ΝΙΚΗ": 131, "ΝΔ": 2, "ΣΥΡΙΖΑ": 4, "ΠΑΣΟΚ": 106, "Ελλ. Λύση": 108} if FULL else     {"ΝΙΚΗ": 131, "ΝΔ": 2, "Ελλ. Λύση": 108}
if ELECTION == "2024/euro":
    COLS["Φωνή Λογικής"] = 158
TUNE, DRAWS, ACCEPT = (1500, 1000, 0.9) if FULL else (3000, 1500, 0.95)


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


tb, vb = load(BASE)
tt, vt = load(ELECTION)
keys = sorted(k for k in tt if k in tb and tb[k][0] >= 100 and tt[k][0] >= 100)
if MAX_UNITS:  # quick runtime test on a random subset
    pick = np.random.default_rng(0).choice(len(keys), MAX_UNITS, replace=False)
    keys = [keys[i] for i in sorted(pick)]
print(f"{BASE} → {ELECTION}: {len(keys)} δημοτικές ενότητες σε {len({k[0] for k in keys})} περιφέρειες")

row_names = list(ROWS) + ["Λοιπά", "Αποχή/άκυρα"]
col_names = list(COLS) + ["Λοιπά", "Αποχή/άκυρα"]
X = fractions(tb, vb, keys, ROWS)
Y = fractions(tt, vt, keys, COLS)
pops = np.array([tt[k][0] for k in keys])
assert np.allclose(X.sum(0), 1) and np.allclose(Y.sum(0), 1)

ei = RowByColumnEI(model_name="multinomial-dirichlet-modified", pareto_shape=100, pareto_scale=100)
ei.fit(X, Y, pops, demographic_group_names=row_names, candidate_names=col_names,
       draws=DRAWS, tune=TUNE, chains=4, target_accept=ACCEPT, random_seed=0,  # PyEI samples with numpyro
       nuts_sampler_kwargs={"chain_method": "parallel"})

import arviz as az

rhat = az.rhat(ei.sim_trace, var_names=["b"]) if "b" in ei.sim_trace.posterior else az.rhat(ei.sim_trace)
print("max rhat:", float(max(rhat[v].max() for v in rhat.data_vars)))
ess = az.ess(ei.sim_trace, var_names=["b"]) if "b" in ei.sim_trace.posterior else az.ess(ei.sim_trace)
print("min ess:", float(min(ess[v].min() for v in ess.data_vars)))

prefs = ei.sampled_voting_prefs  # (samples, rows, cols), group-population weighted
# The max above is over b per unit (units x rows x cols cells). What the tables report is the
# population-weighted aggregate; check its convergence too. Samples are stacked chain-major.
agg = az.convert_to_dataset(prefs.reshape(ei.sim_trace.posterior.sizes["chain"], -1, *prefs.shape[1:]))
agg_rhat = az.rhat(agg).to_array().values[0]
print("aggregate max rhat:", float(agg_rhat.max()), "min ess:", float(az.ess(agg).to_array().min()))
chain_means = prefs.reshape(ei.sim_trace.posterior.sizes["chain"], -1, *prefs.shape[1:]).mean(1)
for idx in np.argsort(agg_rhat, axis=None)[::-1][:8]:  # worst cells, with each chain's mean
    i, j = np.unravel_index(idx, agg_rhat.shape)
    print(f"  rhat {agg_rhat[i, j]:.2f} {row_names[i]} → {col_names[j]}, αλυσίδες:",
          " ".join(f"{100 * x:.1f}%" for x in chain_means[:, i, j]))
grp_pop = (X * pops).sum(1)  # people in each base group (on target registered base)
col_pop = (Y * pops).sum(1)


def table(target):
    j = col_names.index(target)
    b = prefs[:, :, j]
    comp = b * grp_pop / col_pop[j]
    print(f"\n=== {target} {ELECTION}  (πραγματικό {100 * col_pop[j] / pops.sum():.2f}% εγγεγρ.)")
    print(f"{'ομάδα ' + BASE:<14}{'% ομάδας → ' + target:>22}{'90% CrI':>14}{'% ψήφων ' + target:>20}{'90% CrI':>14}")
    for r, name in enumerate(row_names):
        lo, hi = np.percentile(b[:, r], [5, 95])
        clo, chi = np.percentile(comp[:, r], [5, 95])
        print(f"{name:<14}{100 * b[:, r].mean():>22.1f}{f'{100 * lo:.1f}–{100 * hi:.1f}':>14}"
              f"{100 * comp[:, r].mean():>20.1f}{f'{100 * clo:.1f}–{100 * chi:.1f}':>14}")
    print(f"(άθροισμα σύνθεσης {100 * comp.sum(1).mean():.1f}%)")


for t in ("ΝΙΚΗ", "ΝΔ", "Ελλ. Λύση"):
    table(t)

if "ΝΙΚΗ" in ROWS:  # where the base election's NIKH voters went
    r = row_names.index("ΝΙΚΗ")
    print(f"\n=== Ψηφοφόροι ΝΙΚΗΣ {BASE} → {ELECTION}")
    for j, name in enumerate(col_names):
        lo, hi = np.percentile(prefs[:, r, j], [5, 95])
        print(f"{name:<14}{100 * prefs[:, r, j].mean():>8.1f}%  ({100 * lo:.1f}–{100 * hi:.1f})")
