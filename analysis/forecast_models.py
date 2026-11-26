"""Two more forecasts beside forecast.py, from the same polls (nikh_polls.csv), the same poll-average model and the same
ballot error; only how each poll counts changes. Elections today; national seats only (seats_law.national_seats: they do not
depend on how the votes spread over constituencies).

- base: forecast.py as it is (forecast.levels()).
- coef (model A): each poll times k of its firm, method and party (pollster_coef.coef: ballot / poll over 12 elections,
  2007-2024, party + method + firm parts, each shrunk); firm and method form the key of the house effect. A party without
  past elections (ELAS, ELPIDA, SE) keeps k = 1. k carries every past error, also the ones all firms shared at an election,
  which need not repeat.
- weights (model B): polls as they are, but each poll's noise divided by the weight of its firm, method and party
  (pollster_coef.weight: inverse mean square error near past elections, relative to the other firms of the same election,
  shrunk, clipped to [1/3, 3]), so a firm that fell closer for that party counts more in that party's average.
Method of a poll: pollster_coef.mode (analysis/pollster_methods.csv). Same seed and draws for all three (common random numbers).

Writes analysis/forecast_models.json (read by forecast_page.py):
{"n", "models": {key: {"shares": {party: [10%, 50%, 90%]}, "seats": {party: median}, "p_in": {party}, "rates": {metric}}},
 "coef": {party: {firm method: k}}, "weight": {party: {firm method: w}}}

    python -I -X utf8 analysis/forecast_models.py
"""
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import forecast as F
import nikh_polls as NP
import pollster_coef as C
import seats_law as L

OUT = HERE / "forecast_models.json"
MODELS = ("base", "coef", "weights")


def obs_of(code, model):
    """The party's polls [(day, 'firm|method', n, pct)], pct times k for model coef."""
    out = []
    for d, f, n, y in F.polls_to(code):
        fm = C.firm(f)
        m = C.mode(fm, d)
        out.append((d, f"{fm}|{m}", n, y * C.coef(fm, m, F.PARTIES[code][1]) if model == "coef" else y))
    return out


def wt_of(code, obs):
    """{'firm|method': weight} for the party's polls."""
    return {lab: C.weight(*lab.split("|"), F.PARTIES[code][1]) for lab in {o[1] for o in obs}}


def estimate(code, model):
    """(mean, sd) of the party's level today under model."""
    if model == "base":
        return F.estimate(code)
    obs = obs_of(code, model)
    wt = wt_of(code, obs) if model == "weights" else None
    h, q, tau2, _ = NP.fit(obs, F.QS, F.TAUS, wt=wt)
    x, P, _, _ = NP.kfilter(obs, h, q, tau2, wt=wt)[0][-1]
    return x, math.sqrt(P + q * (NP.TODAY - obs[-1][0]).days)


def levels(model):
    """{party: (mean, sd)} with OTHER, as forecast.levels()."""
    out = {p: estimate(p, model) for p in F.PARTIES}
    out[F.OTHER] = (max(0.5, 100 - sum(x for x, _ in out.values())), math.sqrt(sum(sd * sd for _, sd in out.values())))
    return out


def run(model, n=F.N_SIMS):
    rng, lv = random.Random(F.SEED), levels(model)
    a, b, _ = F.error_fit()
    shares = [F.draw(rng, lv, a, b) for _ in range(n)]
    sims = [(sh, L.national_seats(F.law_votes(sh))) for sh in shares]
    return {"shares": {p: [round(F.q(sorted(sh[p] for sh in shares), f), 2) for f in (.1, .5, .9)] for p in F.PARTIES},
            "seats": F.median_parliament(sims),
            "p_in": {p: round(sum(p in st for _, st in sims) / n, 4) for p in F.PARTIES},
            "rates": {k: round(v, 4) for k, v in F.rates(sims).items()}}


def tables():
    """Coefficients and weights of the firms polling now, by the method of their latest poll, per party."""
    cur = C.current()
    return ({p: {f"{fm}|{m}": round(C.coef(fm, m, name), 3) for fm, m in cur.items()} for p, (_, name) in F.PARTIES.items()},
            {p: {f"{fm}|{m}": round(C.weight(fm, m, name), 3) for fm, m in cur.items()} for p, (_, name) in F.PARTIES.items()})


def main():
    res = {m: run(m) for m in MODELS}
    k, w = tables()
    OUT.write_text(json.dumps({"n": F.N_SIMS, "models": res, "coef": k, "weight": w}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'κόμμα':20}" + "".join(f"{m:>22}" for m in MODELS))
    for p in sorted(F.PARTIES, key=lambda p: -res["base"]["shares"][p][1]):
        print(f"{F.PARTIES[p][1]:20}" + "".join(f"{s[1]:6.1f} ({s[0]:4.1f}-{s[2]:4.1f}) {r['seats'].get(p, 0):3}"
                                                 for r in res.values() for s in [r["shares"][p]]))
    for key in res["base"]["rates"]:
        print(f"{key:20}" + "".join(f"{100 * r['rates'][key]:21.1f}%" for r in res.values()))
    print(f"wrote {OUT.name}")


if __name__ == "__main__":
    main()
