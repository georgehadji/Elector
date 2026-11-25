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
A party in NEW (the expected party of Samaras) joins PARTIES and GEO by itself once its poll column has MIN_POLLS polls;
the run reports poll columns that no party reads.
Party columns other than niki come from Wikipedia (polls_wiki.py), not checked against the firms' releases.
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
import seats_law as L

# party code: (column of nikh_polls.csv, Greek name)
PARTIES = {"ND": ("ND", "ΝΔ"), "ELAS": ("ELAS", "ΕΛΑΣ"), "PASOK": ("PASOK", "ΠΑΣΟΚ"), "EL": ("EL", "Ελληνική Λύση"),
           "KKE": ("KKE", "ΚΚΕ"), "PE": ("PE", "Πλεύση Ελευθερίας"), "ELPIDA": ("ELPIDA", "Ελπίδα"), "FL": ("FL", "Φωνή Λογικής"),
           "SE": ("SE", "Συμμαχία Ελλήνων"), "MERA25": ("M25", "ΜέΡΑ25"), "SYRIZA": ("SYRIZA", "ΣΥΡΙΖΑ"), "NIKI": ("niki", "ΝΙΚΗ"),
           "DIMOKRATES": ("DPK", "Δημοκράτες"), "SPARTIATES": ("SP", "Σπαρτιάτες"), "NEA_ARISTERA": ("NA", "Νέα Αριστερά")}
OTHER = "OTHER"
QS = NP.QS + (0.06, 0.12)
TAUS = NP.TAUS + (1.0, 1.3, 1.7, 2.2)
A_GRID = tuple(i / 50 for i in range(51))  # a of the ballot error, 0-1
B_GRID = tuple(i / 1000 for i in range(51))  # b of the ballot error, 0-0.05
OUT = HERE / "forecast.json"
EURO, JUNE = "2024/euro", "2023/june"
# geography of each party: (election, party id) of past results; parties not listed are flat
GEO = {"ND": (EURO, 2), "SYRIZA": (EURO, 4), "PASOK": (EURO, 106), "EL": (EURO, 108), "KKE": (EURO, 3), "NIKI": (EURO, 131),
       "PE": (EURO, 123), "FL": (EURO, 158), "MERA25": (EURO, 122), "NEA_ARISTERA": (EURO, 166),
       "SPARTIATES": (JUNE, 157), "ELAS": (JUNE, 4)}
# Parties expected in the polls but not there yet: code -> (column of nikh_polls.csv, Greek name, geography until it has
# results of its own). One joins PARTIES and GEO, and so the forecast, its seats and out/forecast.html, by itself once its
# column has MIN_POLLS polls. polls_wiki.py names the columns after Wikipedia's header, unknown before the party exists: when
# forecast.py reports a new column, write that header here. Until then analysis/samaras_scenarios.py stands in for it.
NEW = {"SAM": ("SAM", "κόμμα Σαμαρά", (JUNE, 2))}  # [judgement] ND June 2023, as in samaras_scenarios.py
MIN_POLLS = 10


def poll_counts():
    """{column of nikh_polls.csv: polls with a figure in it}."""
    with open(NP.CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {c: sum(bool(r[c].strip()) for r in rows) for c in rows[0] if c not in ("firm", "end", "sample")}


def joined(counts):
    """{code: (column, name)} of the NEW parties with at least MIN_POLLS polls in counts {column: polls}."""
    return {p: (col, name) for p, (col, name, _) in NEW.items() if counts.get(col, 0) >= MIN_POLLS}


COUNTS = poll_counts()
PARTIES |= joined(COUNTS)
GEO |= {p: NEW[p][2] for p in joined(COUNTS) if p not in GEO}
UNKNOWN = sorted(set(COUNTS) - {col for col, _ in PARTIES.values()})  # columns no party reads: a new party in the polls?
# sensitivity: June 2023 for every party that ran then (NA and ELAS as SYRIZA); other proxies for the parties without a past
VARIANTS = {"κύρια (GEO)": GEO,
            "Ιούνιος 2023 για όλα": {p: (JUNE, pid) for p, (_, pid) in GEO.items()} | {"NEA_ARISTERA": (JUNE, 4)},
            "άλλα proxy για τα νέα": {p: v for p, v in GEO.items() if p != "ELAS"}
            | {"ELPIDA": (EURO, 123), "SE": (EURO, 108), "DIMOKRATES": (EURO, 4)}}
MAIN = next(iter(VARIANTS))
GEO_SD = 0.10
# who reaches a majority, as seat sums (arithmetic, not a forecast of who would govern); one place for the page and every run
COALITIONS = (("ND",), ("ND", "PASOK"), ("ND", "ELAS"), ("PASOK", "ELAS"), ("ND", "PASOK", "ELAS"))


def seats_of(st, c):
    """Summed seats of the parties of coalition c in one draw's seats st {party: seats}."""
    return sum(st.get(p, 0) for p in c)


def p_key(c):
    """JSON key of the probability that c reaches a majority: p_nd_majority for ND alone, else p_nd_pasok_151."""
    return "p_nd_majority" if c == ("ND",) else "p_" + "_".join(p.lower() for p in c) + "_151"


def h_key(c):
    """JSON key of the histogram of c's summed seats: hist_nd, hist_nd_pasok, ..."""
    return "hist_" + "_".join(p.lower() for p in c)


def _reaches(c):
    return lambda sh, st: seats_of(st, c) >= L.majority()


# every probability of a run, defined once: name -> fn(shares, seats) -> bool; rates() is the share of draws where it holds
METRICS = {p_key(COALITIONS[0]): _reaches(COALITIONS[0]),
           # first party at 25% or more (the largest share, OTHER included: it is never near 25%)
           "p_bonus": lambda sh, st: sh[max(sh, key=sh.get)] >= L.LAWS[L.CURRENT]["bonus"]["from"],
           **{p_key(c): _reaches(c) for c in COALITIONS[1:]},
           "p_nd_30": lambda sh, st: sh["ND"] >= 30}
# the two sides of parliament, as seat sums only [judgement: by where each party sits; not who would cooperate with whom];
# parties in neither (ELPIDA, born of the Tempi protest, and OTHER) count as open
BLOCS = {"right": ("ND", "EL", "NIKI", "SE", "FL", "SPARTIATES"),
         "left": ("ELAS", "PASOK", "KKE", "PE", "SYRIZA", "MERA25", "NEA_ARISTERA", "DIMOKRATES")}
GAP_STEP = 0.5  # bin of the histogram of the gap between the two contenders for second place, in points


def rates(sims):
    """{metric: share of the draws where it holds} for draws [(shares, seats, ...)]."""
    return {k: sum(f(sh, st) for sh, st, *_ in sims) / len(sims) for k, f in METRICS.items()}


def counts(xs):
    """{value: how many times}, sorted by value."""
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items()))


def partners(sims, base):
    """When the parties of base fall short of a majority: in how many draws that happens, and for each other party X the
    share of those draws where base + X reaches it (only X with a share above 0)."""
    short = [st for _, st, *_ in sims if seats_of(st, base) < L.majority()]
    p = {x: sum(seats_of(st, (*base, x)) >= L.majority() for st in short) / len(short) for x in PARTIES if x not in base} if short else {}
    return {"n_short": len(short), "p": {x: v for x, v in sorted(p.items(), key=lambda kv: -kv[1]) if v > 0}}


def second_gap(sims, a, b):
    """{bin: draws} of share(a) - share(b) in points, bins of GAP_STEP (the bin's lower edge)."""
    return counts(round(math.floor((sh[a] - sh[b]) / GAP_STEP) * GAP_STEP, 1) for sh, *_ in sims)


def median_parliament(sims):
    """{party: seats}: each party's median seats over the draws, rounded by largest remainders so the sum is the law's."""
    med = {p: q(sorted(st.get(p, 0) for _, st, *_ in sims), .5) for p in PARTIES}
    return {p: v for p, v in L.hare({p: m for p, m in med.items() if m}, L.LAWS[L.CURRENT]["seats"]).items() if v}


def firm_weights(obs):
    """{firm key of obs: weight} from the firms' past accuracy (pollster_record.weights, shrunk toward 1). Firms without a record: 1."""
    import pollster_record as PR
    w = PR.weights()
    return {f: w[PR.firm_of(f)] for f in {o[1] for o in obs} if PR.firm_of(f) in w}


@cache
def _fit(party, weighted):
    obs = NP.load(PARTIES[party][0])
    return (obs, *NP.fit(obs, QS, TAUS, wt=firm_weights(obs) if weighted else None))


def fitted(party, weighted=False):
    """(obs, house effects, q, tau2, loglik) for one party code. weighted: polls of firms with a better record count more.
    One cache entry per (party, weighted) however it is called."""
    return _fit(party, bool(weighted))


def estimate(party, horizon_days=0, weighted=False):
    """(mean, sd) of the party's level (% of valid votes, average firm) at nikh_polls.TODAY + horizon_days."""
    obs, h, q, tau2, _ = fitted(party, weighted)
    x, P, _, _ = NP.kfilter(obs, h, q, tau2, wt=firm_weights(obs) if weighted else None)[0][-1]
    return x, math.sqrt(P + q * ((NP.TODAY - obs[-1][0]).days + horizon_days))


def levels(horizon_days=0, weighted=False):
    """{party: (mean, sd)}; OTHER = 100 - the sum (floor 0.5), sd that of the sum (parties taken as independent)."""
    out = {p: estimate(p, horizon_days, weighted) for p in PARTIES}
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
    bonus = [METRICS["p_bonus"](sh, st) for sh, st, _ in sims]
    out = {"n": n, **rates(sims), **{h_key(c): {} for c in COALITIONS}, "parties": {}, "eps": {}}
    for _, st, _ in sims:
        for c in COALITIONS:
            h, v = out[h_key(c)], seats_of(st, c)
            h[v] = h.get(v, 0) + 1
    for c in COALITIONS:
        out[h_key(c)] = dict(sorted(out[h_key(c)].items()))
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
    # second place: the two parties most often second, and the gap between them
    a, b = sorted((p for p in PARTIES), key=lambda p: -out["parties"][p]["p_second"])[:2]
    out["second"] = {"pair": [a, b], "gap": second_gap(sims, a, b), "step": GAP_STEP}
    # third partner: when ND alone, or ND and PASOK, fall short of 151
    out["partners"] = {"_".join(c): partners(sims, c) for c in (("ND",), ("ND", "PASOK"))}
    # the 25% threshold: ND's seats and the probabilities with and without a bonus, and the median parliament of each
    split = {"bonus": [x for x, b in zip(sims, bonus, strict=True) if b], "nobonus": [x for x, b in zip(sims, bonus, strict=True) if not b]}
    out["scenarios"] = {k: {"n": len(v), "hist_nd": counts(st.get("ND", 0) for _, st, *_ in v), "rates": rates(v) if v else {},
                            "parliament": median_parliament(v) if v else {}} for k, v in split.items()}
    # full seat distributions (safe and toss-up seats on the page) and the two sides of parliament
    out["seat_hist"] = {p: counts(st.get(p, 0) for _, st, *_ in sims) for p in PARTIES}
    out["blocs"] = {k: {"parties": list(ps), "hist": counts(seats_of(st, ps) for _, st, *_ in sims),
                        "p_151": sum(seats_of(st, ps) >= L.majority() for _, st, *_ in sims) / n} for k, ps in BLOCS.items()}
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
    for p, (col, name, _) in NEW.items():  # a new party joins at MIN_POLLS polls, not before
        assert joined({col: MIN_POLLS - 1}) == {} and joined({col: MIN_POLLS}) == {p: (col, name)}


if __name__ == "__main__":
    selftest()
    names = {**{p: n for p, (_, n) in PARTIES.items()}, OTHER: "Άλλοι"}

    print(f"=== Βήμα 1: μέσος όρος δημοσκοπήσεων ανά κόμμα στις {NP.TODAY} (μοντέλο του nikh_polls.py, κάθε κόμμα χωριστά) ===")
    print("Ζώνη 90%: αβεβαιότητα του μέσου όρου μόνο, όχι λάθος της κάλπης. * = q ή τ στο πάνω άκρο του πλέγματος· "
          "° = τ στο ελάχιστο (καθόλου θόρυβος εκτός δειγματοληψίας, ζώνη μάλλον πολύ στενή).")
    head = f"{'κόμμα':<20}{'δημ.':>5}{'εταιρ.':>7}  {'τελευταία':<11}{'επίπεδο':>8}{'90%':>13}{'√q/μήνα':>9}{'τ':>6} "
    print(head)
    order = sorted(PARTIES, key=lambda p: -estimate(p)[0])
    tot = 0.0
    for p in order:
        obs, h, q_, tau2, _ = fitted(p)
        x, sd = estimate(p)
        edge = "*" if q_ == QS[-1] or round(math.sqrt(tau2), 6) == TAUS[-1] else "°" if round(math.sqrt(tau2), 6) == TAUS[0] else " "
        line = (f"{names[p]:<20}{len(obs):>5}{len(h):>7}  {obs[-1][0]!s:<11}{x:>8.1f}{f'{x - 1.645 * sd:.1f}–{x + 1.645 * sd:.1f}':>13}"
                f"{math.sqrt(q_ * 30):>9.2f}{math.sqrt(tau2):>6.2f}{edge}")
        tot += x
        print(line)
    print(f"{'Σύνολο':<43}{tot:>8.1f}")
    print(f"Άλλοι (100 − σύνολο): {100 - tot:.1f}%")
    for p, (col, name, _) in NEW.items():
        if p not in PARTIES:
            print(f"{name}: {COUNTS.get(col, 0)} δημοσκοπήσεις στη στήλη {col}, μπαίνει στην πρόβλεψη από {MIN_POLLS} (forecast.NEW).")
    if UNKNOWN:
        print(f"Στήλες του nikh_polls.csv που δεν διαβάζει κανένα κόμμα: {', '.join(UNKNOWN)}. Νέο κόμμα; "
              "Βάλε τη στήλη του στο forecast.PARTIES ή στο forecast.NEW.")

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
    print(f"{'κόμμα':<20}{'διάμεσος':>9}{'80% σήμερα':>14}{'P≥3% σήμερα':>13}{'σε 180 ημ.':>11}")
    for p in [*order, OTHER]:
        xs = sorted(s[p] for s in sims[0])
        p3 = {H: sum(s[p] >= 3 for s in sims[H]) / len(sims[H]) for H in sims}
        line = f"{names[p]:<20}{q(xs, .5):>9.1f}{f'{q(xs, .1):.1f}–{q(xs, .9):.1f}':>14}{100 * p3[0]:>12.1f}%{100 * p3[180]:>10.1f}%"
        print(line)

    print("\n=== Έλεγχος ΝΙΚΗΣ με το NIKH.md §18 ===")
    ni = {H: sum(s["NIKI"] >= 3 for s in sims[H]) / len(sims[H]) for H in sims}
    alt = simulate(20000, 0, national=False)
    print(f"P(ΝΙΚΗ ≥ 3%): σήμερα {100 * ni[0]:.1f}% (με ευρωεκλογές στο λάθος {100 * sum(s['NIKI'] >= 3 for s in alt) / len(alt):.1f}%), "
          f"σε 180 ημέρες {100 * ni[180]:.1f}%")
    print("  §18 (λόγοι 23 μικρών κομμάτων, nikh_montecarlo.py): 0,3-0,6% σήμερα, 3,8-5,2% σε 180 ημέρες.")
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
              f"P(ΝΔ+ΠΑΣΟΚ ≥151) {100 * r['p_nd_pasok_151']:.1f}%   P(ΝΔ+ΕΛΑΣ ≥151) {100 * r['p_nd_elas_151']:.1f}%   "
              f"P(ΝΔ+ΠΑΣΟΚ+ΕΛΑΣ ≥151) {100 * r['p_nd_pasok_elas_151']:.1f}%")
        print(f"  {'κόμμα':<20}{'P 1ο':>6}{'P 2ο':>6}{'έδρες 10-50-90%':>17}{'με μπόνους':>13}{'χωρίς':>13}")
        for p in order:
            d = r["parties"][p]
            print(f"  {names[p]:<20}{100 * d['p_first']:>5.0f}%{100 * d['p_second']:>5.0f}%{fmt(d['seats']):>17}"
                  f"{fmt(d['seats_bonus']):>13}{fmt(d['seats_nobonus']):>13}")
    r = res[0]
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
