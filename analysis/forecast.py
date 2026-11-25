"""National forecast, steps 1-2: poll average of every party, then the ballot error, as draws of election-day shares summing to 100.

Step 1, poll average: the model of nikh_polls.py (random-walk level, house effect per firm, q and tau by maximum likelihood),
fitted on each party of analysis/nikh_polls.csv on its own. The grid of q and tau is wider than NIKH's, because big parties
move and scatter more. Empty cells (the party was not asked in that poll) are skipped; new parties (ELAS, ELPIDA since Apr
2026, SE since Oct 2026) have few polls. If the fit puts tau at the grid's floor (no non-sampling noise), the band is the
narrowest the model allows and likely too narrow. The levels need not sum to 100: the rest is OTHER. The average carries the
average firm's bias, not the truth.
Step 2, ballot error: pairs (election, party) of analysis/nikh_pollerror.csv (2007-2024) as in nikh_pollerror.py (plain mean
of the polls ending 1-14 days before, >= 2 polls), but for every party with an average >= 0.5%, not only 1-4%. Model:
log(ballot / poll average) ~ Normal(0, a / p + b), p = poll average in %. a / p is the scatter of small parties (binomial-like),
b a floor for big ones; a and b by maximum likelihood on a grid, national elections only (the forecast is for a national one;
with the European ones too as a check). Few pairs: 45 national, 6 of them under 2%, and Greek law bars publishing polls in
the last 15 days, so 2007-2012 give none.
Draw: each party's level ~ Normal(average, sd at the horizon) (floor 0.05%), times exp(error), OTHER included, then all scaled
to sum to 100. Errors are independent between parties apart from that scaling (a real election moves blocs together).
Party columns other than niki come from Wikipedia (polls_wiki.py), not checked against the firms' releases.
Party codes follow Majorline's (ND, ELAS, NIKI ...), so their estimate (analysis/majorline_parties.csv) sits next to ours.
Unofficial.

  python -I -X utf8 analysis/forecast.py > analysis/forecast.txt
"""
import csv
import math
import random
import sys
from datetime import date, timedelta
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python -I drops the script dir
import nikh_pollerror as NE
import nikh_polls as NP

# Majorline code: (column of nikh_polls.csv, Greek name)
PARTIES = {"ND": ("ND", "ΝΔ"), "ELAS": ("ELAS", "ΕΛΑΣ"), "PASOK": ("PASOK", "ΠΑΣΟΚ"), "EL": ("EL", "Ελληνική Λύση"),
           "KKE": ("KKE", "ΚΚΕ"), "PE": ("PE", "Πλεύση Ελευθερίας"), "ELPIDA": ("ELPIDA", "Ελπίδα"), "FL": ("FL", "Φωνή Λογικής"),
           "SE": ("SE", "Συμμαχία Ελλήνων"), "MERA25": ("M25", "ΜέΡΑ25"), "SYRIZA": ("SYRIZA", "ΣΥΡΙΖΑ"), "NIKI": ("niki", "ΝΙΚΗ"),
           "DIMOKRATES": ("DPK", "Δημοκράτες"), "SPARTIATES": ("SP", "Σπαρτιάτες"), "NEA_ARISTERA": ("NA", "Νέα Αριστερά")}
OTHER = "OTHER"
QS = NP.QS + (0.06, 0.12)
TAUS = NP.TAUS + (1.0, 1.3, 1.7, 2.2)
A_GRID = tuple(i / 50 for i in range(51))  # a of the ballot error, 0-1
B_GRID = tuple(i / 1000 for i in range(51))  # b of the ballot error, 0-0.05
MAJORLINE = HERE / "majorline_parties.csv"


@cache
def fitted(party):
    """(obs, house effects, q, tau2, loglik) for one party code."""
    obs = NP.load(PARTIES[party][0])
    return (obs, *NP.fit(obs, QS, TAUS))


def estimate(party, horizon_days=0):
    """(mean, sd) of the party's level (% of valid votes, average firm) at nikh_polls.TODAY + horizon_days."""
    obs, h, q, tau2, _ = fitted(party)
    x, P, _, _ = NP.kfilter(obs, h, q, tau2)[0][-1]
    return x, math.sqrt(P + q * ((NP.TODAY - obs[-1][0]).days + horizon_days))


def levels(horizon_days=0):
    """{party: (mean, sd)}; OTHER = 100 - the sum (floor 0.5), sd that of the sum (parties taken as independent)."""
    out = {p: estimate(p, horizon_days) for p in PARTIES}
    out[OTHER] = (max(0.5, 100 - sum(x for x, _ in out.values())), math.sqrt(sum(sd * sd for _, sd in out.values())))
    return out


@cache
def pairs():
    """[(election, party, poll average, ballot)]: >= 2 polls ending 1-14 days before, a ballot figure, average >= 0.5%."""
    polls, ballots, day = NE.load()
    out = []
    for el, parties in polls.items():
        for p, ps in parties.items():
            avg, n = NE.mean_between(ps, 0, 14, day[el])
            if p in ballots[el] and n >= 2 and avg >= 0.5:
                out.append((el, p, avg, ballots[el][p]))
    return sorted(out)


@cache
def error_fit(national=True):
    """(a, b, n) of log(ballot / average) ~ Normal(0, a / p + b), maximum likelihood on A_GRID x B_GRID."""
    xs = [(avg, math.log(b / avg)) for el, _, avg, b in pairs() if not (national and el in NE.EURO)]

    def ll(a, b):
        return -sum(math.log(a / p + b) + e * e / (a / p + b) for p, e in xs) / 2

    a, b = max(((a, b) for a in A_GRID for b in B_GRID if a or b), key=lambda ab: ll(*ab))
    return a, b, len(xs)


def draw(rng, lv, a, b):
    """{party: election-day share}, summing to 100, from levels lv {party: (mean, sd)} and error (a, b)."""
    out = {}
    for p, (x, sd) in lv.items():
        y = max(0.05, rng.gauss(x, sd))
        out[p] = y * math.exp(rng.gauss(0, math.sqrt(a / y + b)))
    s = sum(out.values())
    return {p: 100 * v / s for p, v in out.items()}


def simulate(n=20000, horizon_days=0, national=True, seed=2026):
    """n draws of election-day shares (list of dicts)."""
    rng, lv = random.Random(seed), levels(horizon_days)
    a, b, _ = error_fit(national)
    return [draw(rng, lv, a, b) for _ in range(n)]


def majorline():
    """({party: row} of Majorline's latest run, its date), or (None, None) without the csv."""
    if not MAJORLINE.exists():
        return None, None
    with open(MAJORLINE, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["src"] == "run"]
    last = max(r["as_of"] for r in rows)
    return {r["party"]: r for r in rows if r["as_of"] == last and r["share"]}, last


def q(xs, f):
    return xs[min(len(xs) - 1, int(f * len(xs)))]


def selftest():
    # two firms, +1 and -1 around a constant 30%: level near 30, house effects near +-1 shrunk by n/(n+3)
    obs = sorted((date(2025, 1, 1) + timedelta(days=5 * i), f, 1000, 30 + s) for i in range(40) for f, s in (("A", 1), ("B", -1)))
    h, q_, tau2, _ = NP.fit(obs, QS, TAUS)
    x = NP.kfilter(obs, h, q_, tau2)[0][-1][0]
    assert abs(x - 30) < 0.2 and abs(h["A"] - 40 / 43) < 0.1 and abs(h["B"] + 40 / 43) < 0.1, (x, h)
    with open(NP.CSV, encoding="utf-8") as f:
        assert {c for c, _ in PARTIES.values()} <= set(next(csv.reader(f))), "a party column is missing from nikh_polls.csv"
    d = draw(random.Random(1), {"A": (60, 1), "B": (30, 1), "C": (2, 0.2)}, 0.3, 0.01)
    assert abs(sum(d.values()) - 100) < 1e-9 and min(d.values()) > 0, d
    d = draw(random.Random(1), {"A": (60, 0), "B": (40, 0)}, 0, 0)  # no error at all: the levels come back
    assert abs(d["A"] - 60) < 1e-9, d


if __name__ == "__main__":
    selftest()
    ml, ml_day = majorline()
    names = {**{p: n for p, (_, n) in PARTIES.items()}, OTHER: "Άλλοι"}

    print(f"=== Βήμα 1: μέσος όρος δημοσκοπήσεων ανά κόμμα στις {NP.TODAY} (μοντέλο του nikh_polls.py, κάθε κόμμα χωριστά) ===")
    print("Ζώνη 90%: αβεβαιότητα του μέσου όρου μόνο, όχι λάθος της κάλπης. * = q ή τ στο πάνω άκρο του πλέγματος· "
          "° = τ στο ελάχιστο (καθόλου θόρυβος εκτός δειγματοληψίας, ζώνη μάλλον πολύ στενή).")
    head = f"{'κόμμα':<20}{'δημ.':>5}{'εταιρ.':>7}  {'τελευταία':<11}{'επίπεδο':>8}{'90%':>13}{'√q/μήνα':>9}{'τ':>6} "
    print(head + (f"{'Majorline':>10}{'διαφ.':>7}" if ml else ""))
    order = sorted(PARTIES, key=lambda p: -estimate(p)[0])
    tot = tot_ml = 0.0
    for p in order:
        obs, h, q_, tau2, _ = fitted(p)
        x, sd = estimate(p)
        edge = "*" if q_ == QS[-1] or round(math.sqrt(tau2), 6) == TAUS[-1] else "°" if round(math.sqrt(tau2), 6) == TAUS[0] else " "
        line = (f"{names[p]:<20}{len(obs):>5}{len(h):>7}  {obs[-1][0]!s:<11}{x:>8.1f}{f'{x - 1.645 * sd:.1f}–{x + 1.645 * sd:.1f}':>13}"
                f"{math.sqrt(q_ * 30):>9.2f}{math.sqrt(tau2):>6.2f}{edge}")
        if ml and p in ml:
            line += f"{float(ml[p]['share']):>10.1f}{x - float(ml[p]['share']):>+7.1f}"
            tot_ml += float(ml[p]["share"])
        tot += x
        print(line)
    print(f"{'Σύνολο':<43}{tot:>8.1f}" + (f"{'':>29}{tot_ml:>10.1f}" if ml else ""))
    print(f"Άλλοι (100 − σύνολο): {100 - tot:.1f}%")

    print("\n=== Βήμα 2: λάθος της κάλπης, log(κάλπη / μέσος όρος δημοσκοπήσεων) ~ Normal(0, a/p + b) ===")
    P = pairs()
    print(f"Ζεύγη εκλογής-κόμματος (μέσος όρος ≥ 0,5%, ≥ 2 δημοσκοπήσεις 1-14 ημέρες πριν): {len(P)} από {len({e for e, *_ in P})} εκλογές")
    print(f"  {'μέσος όρος':<12}{'n':>4}{'RMS λάθος (μον.)':>18}{'RMS log':>9}")
    for lo, hi in ((0.5, 2), (2, 4), (4, 8), (8, 15), (15, 25), (25, 100)):
        xs = [(b - a_, math.log(b / a_)) for el, _, a_, b in P if lo <= a_ < hi and el not in NE.EURO]
        if xs:
            print(f"  {f'{lo:g}-{hi:g}%':<12}{len(xs):>4}{math.sqrt(sum(e * e for e, _ in xs) / len(xs)):>18.2f}"
                  f"{math.sqrt(sum(v * v for _, v in xs) / len(xs)):>9.3f}")
    print("  (εθνικές εκλογές μόνο)")
    for nat in (True, False):
        a, b, n = error_fit(nat)
        edge = " (άκρο πλέγματος)" if a in (A_GRID[0], A_GRID[-1]) or b in (B_GRID[0], B_GRID[-1]) else ""
        sds = ", ".join(f"{p:g}% ±{p * math.sqrt(a / p + b):.2f}" for p in (1.4, 3, 6, 13, 30))
        print(f"{'εθνικές' if nat else 'εθνικές + ευρωεκλογές'} (n {n}): a = {a:.2f}, b = {b:.3f}{edge}; "
              f"τυπικό λάθος σε μονάδες: {sds}")

    a, b, _ = error_fit(True)
    sims = {H: simulate(20000, H) for H in (0, 180)}
    print("\n=== Μερίδια την ημέρα των εκλογών: 20.000 προσομοιώσεις, σπόρος 2026, εθνικό λάθος, άθροισμα 100 ===")
    print(f"{'κόμμα':<20}{'διάμεσος':>9}{'80% σήμερα':>14}{'P≥3% σήμερα':>13}{'σε 180 ημ.':>11}" + (f"{'Majorline P≥3%':>16}" if ml else ""))
    for p in [*order, OTHER]:
        xs = sorted(s[p] for s in sims[0])
        p3 = {H: sum(s[p] >= 3 for s in sims[H]) / len(sims[H]) for H in sims}
        line = f"{names[p]:<20}{q(xs, .5):>9.1f}{f'{q(xs, .1):.1f}–{q(xs, .9):.1f}':>14}{100 * p3[0]:>12.1f}%{100 * p3[180]:>10.1f}%"
        if ml and p in ml and ml[p]["p_in"]:
            line += f"{100 * float(ml[p]['p_in']):>15.1f}%"
        print(line)

    print("\n=== Έλεγχος ΝΙΚΗΣ με το NIKH.md §18 ===")
    ni = {H: sum(s["NIKI"] >= 3 for s in sims[H]) / len(sims[H]) for H in sims}
    alt = simulate(20000, 0, national=False)
    print(f"P(ΝΙΚΗ ≥ 3%): σήμερα {100 * ni[0]:.1f}% (με ευρωεκλογές στο λάθος {100 * sum(s['NIKI'] >= 3 for s in alt) / len(alt):.1f}%), "
          f"σε 180 ημέρες {100 * ni[180]:.1f}%")
    print("  §18 (λόγοι 23 μικρών κομμάτων, nikh_montecarlo.py): 0,3-0,6% σήμερα, 3,8-5,2% σε 180 ημέρες.")
    if ml and "NIKI" in ml:
        print(f"  Majorline, εκτίμηση της {ml_day}: {100 * float(ml['NIKI']['p_in']):.1f}%. Πηγή: Majorline.")
    x, _ = estimate("NIKI")
    print(f"  Για 3% από {x:.2f}% χρειάζεται λόγος {3 / x:.2f}: εδώ σ(log) = {math.sqrt(a / x + b):.2f} → "
          f"{math.log(3 / x) / math.sqrt(a / x + b):.1f} σ μόνο από το λάθος της κάλπης.")
