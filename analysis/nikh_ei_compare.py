"""NIKH (party 131) June 2023 -> Euro 2024: three ecological-inference methods side by side, 2x2 per region.

Unit: (constituency, municipal unit), ordinary stations, >= 200 registered (June), present in both elections.
Group = June 2023 NIKH voters (as a fraction of June registered); tables are 2x2 so each flow is run separately:
- kept: share of June NIKH voters who vote NIKH in Euro 2024 (votes / registered, registered of June for both);
- abstain: share of June NIKH voters who do not cast a valid vote in Euro 2024 (registered - valid).
Methods:
- Duncan-Davis bounds, summed over units (deterministic: the real national share must lie inside).
- Goodman regression (WLS, weights = registered): t = b_other + (b_group - b_other) x.
- Bayesian 2x2, three models, 4 chains each (own code: PyEI 1.1.4 has the Wakefield models commented out):
  king = King-style Beta/Pareto hyperpriors with the aggregate binomial likelihood (PyEI's king99_pareto_modification);
  wakefield_beta = the same priors with Wakefield's convolution of two binomials, approximated by a Normal;
  wakefield_normal = logit-normal unit rates with Normal/Gamma hyperpriors, same likelihood. The Normal approximation
  is rough for units with few NIKH votes. The group share is weighted by group size; rhat is that share's rhat.
Compared with the R x C PyEI per region of NIKH.md section 7 (constants below). A flow is called "agreed" when the three
Bayesian models are all within TOL points of the R x C value. Unofficial results.

Needs pyei (pymc, numpyro). Run:
  python -I -X utf8 analysis/nikh_ei_compare.py data/stavroi.sqlite
"""
import os
import sqlite3
import sys
from pathlib import Path

os.environ.setdefault("XLA_FLAGS", "--xla_force_host_platform_device_count=4")  # 4 CPU devices -> parallel chains

import arviz as az
import numpy as np
import pymc as pm
import pytensor.tensor as pt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import REGIONS

NIKH, J, E, TOL = 131, "2023/june", "2024/euro", 10
# NIKH.md section 7, PyEI R x C per region: % of June NIKH voters who stayed / abstained (posterior means)
RXC = {"Αττική": (72, 3), "Θεσσαλία": (68, 10), "Δυτική Ελλάδα": (67, 7), "Κρήτη": (66, 8), "Πελοπόννησος": (65, 12),
       "Δυτική Μακεδονία": (64, 13), "Ήπειρος": (63, 8), "Κεντρική Μακεδονία": (62, 25), "Στερεά Ελλάδα": (57, 11),
       "Βόρειο Αιγαίο": (57, 8), "Νότιο Αιγαίο": (55, 13), "Ανατολική Μακεδονία και Θράκη": (54, 5), "Ιόνια Νησιά": (22, 23)}


def bounds(x_n, t_n, r):
    """Duncan-Davis bounds on the group's share (summed over units). x_n, t_n: group and candidate counts, r: registered."""
    lo = np.maximum(0, t_n - (r - x_n)).sum() / x_n.sum()
    hi = np.minimum(x_n, t_n).sum() / x_n.sum()
    return lo, hi


def goodman(x, t, r):
    """Group and non-group shares from the weighted regression of t on x."""
    X = np.column_stack([np.ones(len(x)), x])
    sw = np.sqrt(r)
    a, b = np.linalg.lstsq(X * sw[:, None], t * sw, rcond=None)[0]
    return a + b, a


# self-check: exact linear data gives the exact shares and the truth lies inside the bounds
_r = np.array([100., 200, 300, 400])
_x = np.array([.1, .2, .3, .4])
_t = .6 * _x + .1 * (1 - _x)
assert np.allclose(goodman(_x, _t, _r), (.6, .1))
assert bounds(_x * _r, _t * _r, _r)[0] <= .6 <= bounds(_x * _r, _t * _r, _r)[1]

c = sqlite3.connect(sys.argv[1])


def load(e):
    reg = {(ep, den): (r, v) for ep, den, r, v in c.execute(
        "SELECT ep_id, den_descr, SUM(registered), SUM(valid) FROM station WHERE kind='Κ' AND election=? "
        "AND den_descr IS NOT NULL GROUP BY 1, 2", (e,))}
    nik = {(ep, den): n for ep, den, n in c.execute(
        "SELECT s.ep_id, s.den_descr, SUM(p.votes) FROM station s JOIN party_votes p ON p.election=s.election "
        "AND p.tm_id=s.tm_id AND p.party_id=? WHERE s.kind='Κ' AND s.election=? AND s.den_descr IS NOT NULL GROUP BY 1, 2", (NIKH, e))}
    return reg, nik


rj, nj = load(J)
re_, ne = load(E)
keys = [k for k in rj if k in re_ and rj[k][0] >= 200 and re_[k][0] > 0]
R = np.array([rj[k][0] for k in keys], float)
NJ = np.array([nj.get(k, 0) for k in keys], float)
FLOW = {"kept": np.array([ne.get(k, 0) for k in keys], float),  # Euro NIKH votes
        "abstain": R - np.array([re_[k][1] for k in keys], float)}  # registered - Euro valid
EP = np.array([k[0] for k in keys])
print(f"{len(keys)} δημοτικές ενότητες, {R.sum():,.0f} εγγεγραμμένοι Ιουνίου, ΝΙΚΗ Ιούνιος {NJ.sum():,.0f}, Ευρωεκλογές {FLOW['kept'].sum():,.0f}")


DRAWS = 600


def bayes(kind, x, t, r):
    """Posterior of the group's share (weighted by group size): mean, 95% interval, rhat of that share."""
    n0 = x * r
    n1 = r - n0
    obs = np.round(t * r)
    b = []
    with pm.Model():
        for g in (1, 2):
            if kind == "wakefield_normal":
                th = pm.Normal(f"theta_{g}", pm.Normal(f"mu_{g}", 0, 5), pm.Gamma(f"sigma_{g}", 1, 0.1), shape=len(x))
                b.append(pm.Deterministic(f"b_{g}", pm.math.sigmoid(th)))
            else:
                phi, kappa = pm.Uniform(f"phi_{g}", 0, 1), pm.Pareto(f"kappa_{g}", m=8, alpha=2)
                b.append(pm.Beta(f"b_{g}", alpha=phi * kappa, beta=(1 - phi) * kappa, shape=len(x)))
        if kind == "king":
            pm.Binomial("y", n=r, p=x * b[0] + (1 - x) * b[1], observed=obs)
        else:
            var = n0 * b[0] * (1 - b[0]) + n1 * b[1] * (1 - b[1]) + 1.0
            pm.Normal("y", mu=n0 * b[0] + n1 * b[1], sigma=pt.sqrt(var), observed=obs)
        tr = pm.sample(draws=DRAWS, tune=DRAWS, chains=4, target_accept=0.95, nuts_sampler="numpyro", progressbar=False)
    pref = (tr.posterior["b_1"].values * n0).sum(-1) / n0.sum()  # chain x draw
    return pref.mean(), np.percentile(pref, [2.5, 97.5]), float(az.rhat(pref))


MODELS = ("king", "wakefield_beta", "wakefield_normal")


def run(label, m, ref):
    """One row per flow; ref = {flow: R x C value in %} or None."""
    x = NJ[m] / R[m]
    for flow, cnt in FLOW.items():
        t = cnt[m] / R[m]
        lo, hi = bounds(NJ[m], cnt[m], R[m])
        g = goodman(x, t, R[m])[0]
        fits = [bayes(k, x, t, R[m]) for k in MODELS]
        rx = ref[flow] if ref else None
        agree = "" if rx is None else (" ✓" if all(abs(100 * f[0] - rx) <= TOL for f in fits) else " ✗")
        cells = "".join(f"{100 * f[0]:>6.0f}% ({100 * f[1][0]:.0f}-{100 * f[1][1]:.0f}) {f[2]:.2f}".ljust(24) for f in fits)
        print(f"  {label:<33}{flow:<9}{100 * lo:>4.0f}-{100 * hi:<4.0f}{100 * g:>6.0f}%{cells}{'' if rx is None else f'{rx:>5}%'}{agree}", flush=True)


print()
print(f"  {'':<33}{'ροή':<9}{'όρια':>9}{'Goodman':>7} " + "".join(k.ljust(24) for k in MODELS) + "R×C")
run("ΣΥΝΟΛΟ", np.ones(len(keys), bool), None)
for name, eps in REGIONS:
    m = np.isin(EP, eps)
    if m.sum() < 15:
        print(f"  {name:<33}λίγες ενότητες ({m.sum()}), παραλείπεται")
        continue
    kept, ab = RXC[name]
    run(f"{name} ({m.sum()})", m, {"kept": kept, "abstain": ab})
print()
print(f"Κελί μοντέλου: μέσος (95%) rhat. ✓ = και τα τρία μοντέλα μέσα σε {TOL} μονάδες από το R×C της ενότητας 7, ✗ = όχι. rhat > 1,1: δεν συγκλίνει.")
