"""National forecast, steps 1-3: poll average of every party, the ballot error (draws of election-day shares summing to 100),
then the seats of each draw under the electoral law.

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
Step 3, seats (needs the database; nikh_seats.allocate, the law of June 2023: 3%, bonus from 25%, 285 constituency + 15 State
seats). Each draw's national shares are spread over the 59 constituencies of June 2023 by a geography per party (GEO): its own
results of Euro 2024 where it ran then, SYRIZA June 2023 for ELAS and Spartiates' June 2023 [judgement: ELAS has no past
geography; the old main party of the left is the nearest], flat for ELPIDA, SE, DIMOKRATES (the poll column starts Nov 2024, so
it is not Loverdos' Euro 2024 list) and OTHER. Each constituency share gets a lognormal factor (sd GEO_SD) per draw, then the
party is rescaled to its national share, so national totals are exact. Every party is given a full list in every constituency
(the June 2023 lists would cap new parties at zero). Every draw is checked to give 300 seats.
Why Euro 2024 and not June 2023 for most parties: it is the latest election each of them ran in with its present size
(FL 3.1% then, 0.4% in June 2023; NA did not exist in 2023). National seat totals do not depend on the geography at all
(Hare over 300 on national votes, full lists), only which constituency each seat lands in; VARIANTS measures that: June 2023
for every party, and other proxies for the new ones (ELPIDA as PE Euro 2024 [judgement: both run on the Tempi protest],
SE as EL Euro 2024 [judgement: the nationalist right], DIMOKRATES as SYRIZA Euro 2024 [judgement: its leader came from it],
ELAS flat).
Writes analysis/forecast.json: probabilities, shares, national seats, ND and ND+PASOK histograms, per constituency (and State
list) the distribution of each party's seats there, and the sensitivity table.
Party columns other than niki come from Wikipedia (polls_wiki.py), not checked against the firms' releases.
Party codes follow Majorline's (ND, ELAS, NIKI ...), so their estimate (analysis/majorline_parties.csv) sits next to ours.
Unofficial.

  python -I -X utf8 analysis/forecast.py data/stavroi.sqlite [N] > analysis/forecast.txt   # without the db: steps 1-2 only
"""
import csv
import json
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
OUT = HERE / "forecast.json"
EURO, JUNE = "2024/euro", "2023/june"
# geography of each party: (election, party id) of past results; parties not listed are flat
GEO = {"ND": (EURO, 2), "SYRIZA": (EURO, 4), "PASOK": (EURO, 106), "EL": (EURO, 108), "KKE": (EURO, 3), "NIKI": (EURO, 131),
       "PE": (EURO, 123), "FL": (EURO, 158), "MERA25": (EURO, 122), "NEA_ARISTERA": (EURO, 166),
       "SPARTIATES": (JUNE, 157), "ELAS": (JUNE, 4)}
# sensitivity: June 2023 for every party that ran then (NA and ELAS as SYRIZA); other proxies for the parties without a past
VARIANTS = {"κύρια (GEO)": GEO,
            "Ιούνιος 2023 για όλα": {p: (JUNE, pid) for p, (_, pid) in GEO.items()} | {"NEA_ARISTERA": (JUNE, 4)},
            "άλλα proxy για τα νέα": {p: v for p, v in GEO.items() if p != "ELAS"}
            | {"ELPIDA": (EURO, 123), "SE": (EURO, 108), "DIMOKRATES": (EURO, 4)}}
MAIN = next(iter(VARIANTS))
GEO_SD = 0.10


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


@cache
def seats_module():
    """nikh_seats, imported on first use: it opens the database named by sys.argv[1]. Every party gets a full list everywhere."""
    import nikh_seats as S
    for ep, n in S.seats.items():
        for p in [*PARTIES, OTHER]:
            S.cands[ep, p] = n
    return S


@cache
def geography(variant=MAIN):
    """(June 2023 valid votes {ep: votes}, {party: {ep: relative share}}) for a key of VARIANTS; 1 = the party's national share."""
    S = seats_module()
    V = {ep: sum(pv.values()) for ep, pv in S.ep_votes(JUNE).items()}
    spec = VARIANTS[variant]
    past = {e: S.ep_votes(e) for e in {e for e, _ in spec.values()}}
    geo = {}
    for p, (e, pid) in spec.items():
        sh = {ep: past[e][ep].get(pid, 0) / sum(past[e][ep].values()) for ep in V}
        mean = sum(sh[ep] * V[ep] for ep in V) / sum(V.values())
        geo[p] = {ep: sh[ep] / mean for ep in V}
    return V, geo


def spread(shares, V, geo, rng=None, sd=GEO_SD):
    """{ep: {party: votes}} with national shares exactly `shares` (% of V's total); flat geography for parties not in geo."""
    tot = sum(V.values())
    out = {ep: {} for ep in V}
    for p, s in shares.items():
        g = geo.get(p)
        w = {ep: (g[ep] if g else 1.0) * (rng.lognormvariate(0, sd) if rng else 1.0) for ep in V}
        k = s / 100 * tot / sum(w[ep] * V[ep] for ep in V)
        for ep in V:
            out[ep][p] = round(k * w[ep] * V[ep])
    return out


def seat_sims(n=10000, horizon_days=0, seed=2026, variant=MAIN):
    """[(shares, {party: seats}, {party: {ep or 'state': seats}})] for n draws; parties under 3% have no entry."""
    S, (V, geo), rng = seats_module(), geography(variant), random.Random(seed + 1)
    out = []
    for sh in simulate(n, horizon_days, seed=seed):
        # OTHER is many small lists, never one party at 3%: split in 10 for the law, which counts them in the valid votes only
        votes = {p: s for p, s in sh.items() if p != OTHER} | {f"{OTHER}{i}": sh[OTHER] / 10 for i in range(10)}
        res, _ = S.allocate(spread(votes, V, geo, rng))
        tot = {p: sum(v.values()) for p, v in res.items()}
        assert sum(tot.values()) == 300 and not any(p.startswith(OTHER) for p in tot), tot
        out.append((sh, tot, res))
    return out


def summary(sims):
    """Probabilities, shares and seats of seat_sims() for analysis/forecast.json."""
    n = len(sims)
    bonus = [sh[max(sh, key=sh.get)] >= 25 for sh, *_ in sims]
    out = {"n": n, "p_nd_majority": sum(st.get("ND", 0) >= 151 for _, st, _ in sims) / n,
           "p_bonus": sum(bonus) / n,
           "p_nd_pasok_151": sum(st.get("ND", 0) + st.get("PASOK", 0) >= 151 for _, st, _ in sims) / n,
           "hist_nd": {}, "hist_nd_pasok": {}, "parties": {}, "eps": {}}
    for _, st, _ in sims:
        for k, v in (("hist_nd", st.get("ND", 0)), ("hist_nd_pasok", st.get("ND", 0) + st.get("PASOK", 0))):
            out[k][v] = out[k].get(v, 0) + 1
    for k in ("hist_nd", "hist_nd_pasok"):
        out[k] = dict(sorted(out[k].items()))
    rank = [sorted(sh, key=sh.get, reverse=True) for sh, *_ in sims]
    for p in [*PARTIES, OTHER]:
        xs = sorted(sh[p] for sh, *_ in sims)
        d = {"share": [round(q(xs, f), 2) for f in (.1, .5, .9)], "p_in": sum(x >= 3 for x in xs) / n,
             "p_first": sum(r[0] == p for r in rank) / n, "p_second": sum(r[1] == p for r in rank) / n}
        if p != OTHER:
            for label, keep in (("seats", lambda b: True), ("seats_bonus", lambda b: b), ("seats_nobonus", lambda b: not b)):
                ss = sorted(st.get(p, 0) for (_, st, _), b in zip(sims, bonus, strict=True) if keep(b))
                d[label] = [q(ss, f) for f in (.1, .5, .9)] if ss else None
        out["parties"][p] = d
    # per constituency (and 'state'): {party: {seats: share of the draws}}, draws where the party has 0 seats there included
    S = seats_module()
    for ep in [*S.seats, "state"]:
        dist = {}
        for _, _, res in sims:
            for p, by in res.items():
                k = by.get(ep, 0)
                if k:
                    dist.setdefault(p, {}).setdefault(k, 0)
                    dist[p][k] += 1
        dist = {p: {k: round(c / n, 4) for k, c in sorted(d.items())} for p, d in dist.items()}
        out["eps"][ep] = {"name": "Επικρατείας" if ep == "state" else S.ep_name[ep], "seats": S.STATE if ep == "state" else S.seats[ep],
                          "dist": dict(sorted(dist.items(), key=lambda kv: -sum(k * f for k, f in kv[1].items())))}
    return out


def mean_seats(dist):
    """Expected seats from a {seats: share of the draws} dict."""
    return sum(k * f for k, f in dist.items())


def q(xs, f):
    return xs[min(len(xs) - 1, int(f * len(xs)))]


def fmt(x, median_only=False):
    """'10-50-90' (or the median) of a [10%, 50%, 90%] list; '—' for None."""
    return "—" if not x else str(x[1]) if median_only else f"{x[0]}-{x[1]}-{x[2]}"


def check_june():
    """June 2023 rebuilt from its national shares and each party's own geography (no noise) gives the real allocation."""
    S = seats_module()
    june = S.ep_votes(JUNE)
    V = {ep: sum(pv.values()) for ep, pv in june.items()}
    nat = {}
    for pv in june.values():
        for p, v in pv.items():
            nat[p] = nat.get(p, 0) + v
    tot = sum(V.values())
    geo = {p: {ep: june[ep].get(p, 0) / V[ep] / (nat[p] / tot) for ep in V} for p in nat if nat[p]}
    got = {p: sum(v.values()) for p, v in S.allocate(spread({p: 100 * v / tot for p, v in nat.items() if v}, V, geo))[0].items()}
    want = {p: sum(v.values()) for p, v in S.allocate(june)[0].items()}
    assert got == want, (got, want)
    return want


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

    if len(sys.argv) < 2:
        sys.exit()
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    june = check_june()
    S = seats_module()
    print("\n=== Βήμα 3: έδρες (nikh_seats.allocate, νόμος Ιουνίου 2023, γεωγραφία ανά κόμμα: GEO) ===")
    print("Έλεγχος: ο Ιούνιος 2023 ξαναχτισμένος από τα εθνικά ποσοστά και τη γεωγραφία του δίνει τις ίδιες έδρες με το allocate "
          "πάνω στα πραγματικά αποτελέσματα: " + ", ".join(f"{S.PARTY_SHORT.get(p, p)} {v}" for p, v in sorted(june.items(), key=lambda kv: -kv[1])))
    print("  (Επίσημα: ΣΥΡΙΖΑ 48, ΚΚΕ 21, Σπαρτιάτες 12, Πλεύση 8· το allocate είναι απλοποίηση, βλ. nikh_seats.py: ±1 έδρα ανά κόμμα.)")
    print(f"Γεωγραφία: {', '.join(f'{names[p]} ← {e} {pid}' for p, (e, pid) in GEO.items())}; "
          f"ομοιόμορφα: {', '.join(names[p] for p in [*PARTIES, OTHER] if p not in GEO)}. Θόρυβος ανά περιφέρεια σ = {GEO_SD}.")
    res = {}
    for H in (0, 180):
        res[H] = summary(seat_sims(N, H))
        r = res[H]
        print(f"\n{'Εκλογές σήμερα' if H == 0 else f'Εκλογές σε {H} ημέρες'} ({N:,} προσομοιώσεις, σπόρος 2026)")
        print(f"  P(αυτοδυναμία ΝΔ, ≥151) {100 * r['p_nd_majority']:.1f}%   P(μπόνους, 1ο κόμμα ≥25%) {100 * r['p_bonus']:.1f}%   "
              f"P(ΝΔ+ΠΑΣΟΚ ≥151) {100 * r['p_nd_pasok_151']:.1f}%")
        print(f"  {'κόμμα':<20}{'P 1ο':>6}{'P 2ο':>6}{'έδρες 10-50-90%':>17}{'με μπόνους':>13}{'χωρίς':>13}")
        for p in order:
            d = r["parties"][p]
            print(f"  {names[p]:<20}{100 * d['p_first']:>5.0f}%{100 * d['p_second']:>5.0f}%{fmt(d['seats']):>17}"
                  f"{fmt(d['seats_bonus']):>13}{fmt(d['seats_nobonus']):>13}")
    with open(HERE / "majorline_runs.csv", encoding="utf-8") as f:
        mr = max(csv.DictReader(f), key=lambda r: r["as_of"])
    r = res[0]
    print(f"\nΣύγκριση με Majorline (εκτίμηση της {mr['as_of']}; πηγή: Majorline), εκλογές σήμερα:")
    print(f"  αυτοδυναμία ΝΔ {100 * r['p_nd_majority']:.1f}% έναντι {100 * float(mr['single_party_majority']):.1f}%; "
          f"χωρίς μπόνους {100 * (1 - r['p_bonus']):.1f}% έναντι {100 * float(mr['no_bonus']):.1f}%; "
          f"ΝΔ+ΠΑΣΟΚ ≥151 {100 * r['p_nd_pasok_151']:.1f}% έναντι {100 * float(mr['nd_pasok_151']):.1f}%")
    if ml:
        print(f"  {'κόμμα':<20}{'διάμεσος με μπόνους':>21}{'Majorline':>11}{'χωρίς':>8}{'Majorline':>11}")
        for p in order:
            d, m = r["parties"][p], ml.get(p, {})
            print(f"  {names[p]:<20}{fmt(d['seats_bonus'], True):>21}{m.get('seats_bonus') or '—':>11}"
                  f"{fmt(d['seats_nobonus'], True):>8}{m.get('seats_nobonus') or '—':>11}")

    print("\nΑνά περιφέρεια, εκλογές σήμερα: αναμενόμενες έδρες ανά κόμμα (μέσος όρος των προσομοιώσεων, ≥ 0,1)")
    for e in r["eps"].values():  # ministry order, State seats last
        means = {p: mean_seats(d) for p, d in e["dist"].items()}
        assert abs(sum(means.values()) - e["seats"]) < 0.01, (e["name"], means)
        print(f"  {e['name'][:30]:<31}{e['seats']:>3}  " + ", ".join(f"{names[p]} {m:.1f}" for p, m in means.items() if m >= 0.1))

    print(f"\nΕυαισθησία στη γεωγραφία (εκλογές σήμερα, {N:,} προσομοιώσεις, ίδια μερίδια, ίδιος σπόρος):")
    for v, spec in VARIANTS.items():
        flat = [names[p] for p in [*PARTIES, OTHER] if p not in spec]
        diff = [f"{names[p]} ← {e} {pid}" for p, (e, pid) in spec.items() if GEO.get(p) != (e, pid)]
        print(f"  {v}: " + (", ".join(diff) if diff else "όπως παραπάνω") + (f"; ομοιόμορφα: {', '.join(flat)}" if flat else ""))
    watch = ["ND", "ELAS", "PASOK", "PE", "FL", "ELPIDA", "SE", "MERA25"]
    print("  Οι έδρες κάθε κόμματος στο σύνολο της χώρας βγαίνουν από τα εθνικά ποσοστά (Hare στις 300), άρα η γεωγραφία αλλάζει "
          "μόνο σε ποια περιφέρεια πάνε. Μέτρο: έδρες που μετακινούνται = ½ Σ_περιφέρειες |αναμενόμενες έδρες − κύρια|.")
    print(f"  {'παραλλαγή':<24}{'αυτοδ.':>7}{'ΝΔ+ΠΑΣΟΚ':>9}  ίδια σύνολα  μετακινούμενες έδρες: " + ", ".join(names[p] for p in watch))
    sens = {}
    for v in VARIANTS:
        s = r if v == MAIN else summary(seat_sims(N, 0, variant=v))
        moved = {p: sum(abs(mean_seats(s["eps"][ep]["dist"].get(p, {})) - mean_seats(r["eps"][ep]["dist"].get(p, {})))
                        for ep in r["eps"]) / 2 for p in watch}
        same = all(s["parties"][p]["seats"] == r["parties"][p]["seats"] for p in PARTIES)
        sens[v] = {k: s[k] for k in ("p_nd_majority", "p_bonus", "p_nd_pasok_151")} | {"same_totals": same, "moved": moved}
        print(f"  {v:<24}{100 * s['p_nd_majority']:>6.1f}%{100 * s['p_nd_pasok_151']:>8.1f}%  {'ναι' if same else 'ΟΧΙ':>11}  "
              + ", ".join(f"{moved[p]:.1f}" for p in watch))
    OUT.write_text(json.dumps({"as_of": str(NP.TODAY), "seed": 2026, "geo": {p: list(v) for p, v in GEO.items()},
                               "names": names, "horizons": {str(H): v for H, v in res.items()}, "sensitivity": sens},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nΓράφτηκε {OUT.relative_to(HERE.parent).as_posix()}")
