"""The forecast over time: the national forecast of forecast.py run again every TREND_STEP days, each time with only the
polls that had ended by then (forecast.levels(as_of=...): the fit itself, house effects included, knows nothing later).

Today's method throughout, recomputed from nikh_polls.csv each run (no stored state: a corrected old poll corrects its
line). Same seed on every day (common random numbers), so the lines move with the data, not with the draw. National seats
only (seats_law.national_seats): they do not depend on how the votes spread over constituencies. The first day is when
ANCHOR, the second force, has forecast.MIN_POLLS polls: before it the days do not compare.

Writes forecast_trend.json, which forecast_page.py reads:
{"step", "n", "anchor", "start", "points": [{"date", "n_polls", "rates" {metric of forecast.METRICS},
 "p_in" {party}, "p_first" {party}, "p_second" {party}, "share" {party: median}}]}

    python -I -X utf8 analysis/forecast_trend.py
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import forecast as F
import nikh_polls as NP
import seats_law as L

OUT = HERE / "forecast_trend.json"
TREND_STEP = 14  # days between points, counted back from today
N = F.N_SIMS
ANCHOR = "ELAS"


def start():
    """The day ANCHOR reached MIN_POLLS polls."""
    return F.polls_to(ANCHOR)[F.MIN_POLLS - 1][0]


def days():
    """Today, and every TREND_STEP days before it down to start(), oldest first."""
    out, d = [], NP.TODAY
    while d >= start():
        out.append(d)
        d -= timedelta(TREND_STEP)
    return out[::-1]


def point(d, n=N):
    """The forecast with the polls known on day d."""
    shares = F.simulate(n, 0, as_of=d)
    sims = [(sh, L.national_seats(F.law_votes(sh))) for sh in shares]
    ps = [p for p in shares[0] if p != F.OTHER]
    rank = [sorted(ps, key=sh.get, reverse=True) for sh in shares]
    share = lambda p: F.q(sorted(sh[p] for sh in shares), .5)
    return {"date": str(d), "n_polls": len({o[:2] for p in ps for o in F.polls_to(p, d)}),  # (day, firm): one poll
            "rates": {k: round(v, 4) for k, v in F.rates(sims).items()},
            "p_in": {p: round(sum(p in st for _, st in sims) / n, 4) for p in ps},
            "p_first": {p: round(sum(r[0] == p for r in rank) / n, 4) for p in ps},
            "p_second": {p: round(sum(r[1] == p for r in rank) / n, 4) for p in ps},
            "share": {p: round(share(p), 2) for p in ps}}


def main():
    pts = []
    for d in days():
        pts.append(point(d))
        r = pts[-1]["rates"]
        print(f"{d}  ΝΔ 151: {100 * r['p_nd_majority']:5.1f}%  ΝΔ+ΠΑΣΟΚ: {100 * r['p_nd_pasok_151']:5.1f}%  "
              f"ΝΔ+ΕΛΑΣ: {100 * r['p_nd_elas_151']:5.1f}%  μπόνους: {100 * r['p_bonus']:5.1f}%  κόμματα: {len(pts[-1]['share'])}")
    OUT.write_text(json.dumps({"step": TREND_STEP, "n": N, "anchor": ANCHOR, "start": str(start()), "points": pts},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT.name}: {len(pts)} ημερομηνίες, {start()} έως {NP.TODAY}")


if __name__ == "__main__":
    main()
