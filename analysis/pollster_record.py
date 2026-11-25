"""Track record of each polling firm: how far its last poll before an election was from the ballot (A/B of the benchmark idea
in benchmark_plan.md, computed from our own data instead of copied).

Data: analysis/nikh_pollerror.csv (polls_wiki.py: Wikipedia tables, not checked against the firms' releases; rows of kind
"ballot" carry the result of each party). Elections: 2019, 2023/may, 2023/june (the three national elections of the present
party system).
- A firm = the part of the poll's `firm` before "/" (the outlet), Greek look-alike capitals turned into Latin, a few spellings
  merged (FIRM_ALIAS). Only firms that still poll today (analysis/nikh_polls.csv) are scored.
- Last poll of a firm at an election = its latest poll ending 0-WINDOW days before election day (the polls of one firm ending
  the same day are averaged: one firm, one poll).
- Error of one poll = mean over the parties with a ballot >= MIN_BALLOT % and a figure in that poll of |poll - ballot|, in points;
  the poll must cover at least MIN_PARTIES of them.
- avg of a firm = plain mean of its errors over the elections it was scored in (n of them). bench = plain mean of all errors.
- Three elections at most per firm, and May 2023 alone is far worse than the other two for everybody: the ranking is mostly
  noise. weights() therefore shrinks towards 1 (see there). It is a cross-check and a mild weight, not a verdict.

  python -I -X utf8 analysis/pollster_record.py
"""
import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HERE = Path(__file__).resolve().parent
ERRORS = HERE / "nikh_pollerror.csv"
POLLS = HERE / "nikh_polls.csv"
ELECTIONS = ("2019", "2023/may", "2023/june")
LABEL = {"2019": "2019", "2023/may": "Μάι. 2023", "2023/june": "Ιούν. 2023"}
WINDOW = 21
MIN_BALLOT = 3.0
MIN_PARTIES = 4
# Greek capitals that look like Latin ones occur in the Wikipedia tables ("Μarc", "Κapa")
LOOKALIKE = str.maketrans("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "ABEZHIKMNOPTYX")
FIRM_ALIAS = {"RealPolls": "Real Polls", "Prorata": "ProRata", "Pulse": "Pulse RC"}


def firm_of(name):
    """Firm of a poll row: 'Μarc/Alpha' -> 'Marc', 'RealPolls/Dimokratia' -> 'Real Polls'."""
    f = name.translate(LOOKALIKE).split("/")[0].strip()
    return FIRM_ALIAS.get(f, f)


def current_firms():
    with open(POLLS, encoding="utf-8") as f:
        return {firm_of(r["firm"]) for r in csv.DictReader(f)}


def load():
    """({election: {party: ballot}}, {election: day}, {election: {firm: {end: {party: [pct]}}}}) of ERRORS."""
    ballot, day = defaultdict(dict), {}
    polls = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    with open(ERRORS, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            el, end = r["election"], date.fromisoformat(r["end"])
            if el not in ELECTIONS or not r["pct"]:
                continue
            if r["kind"] == "ballot":
                ballot[el][r["party"]] = float(r["pct"])
                day[el] = end
            else:
                polls[el][firm_of(r["firm"])][end][r["party"]].append(float(r["pct"]))
    return ballot, day, polls


def errors():
    """{firm: {election: (poll end, mean absolute error in points, parties scored)}} for the firms that poll today."""
    ballot, day, polls = load()
    now, out = current_firms(), defaultdict(dict)
    for el in ELECTIONS:
        big = {p: v for p, v in ballot[el].items() if v >= MIN_BALLOT}
        for firm, by_end in polls[el].items():
            if firm not in now:
                continue
            ends = [d for d in by_end if 0 <= (day[el] - d).days <= WINDOW]
            if not ends:
                continue
            end = max(ends)
            cells = {p: sum(v) / len(v) for p, v in by_end[end].items() if p in big}
            if len(cells) < MIN_PARTIES:
                continue
            out[firm][el] = (end, sum(abs(v - big[p]) for p, v in cells.items()) / len(cells), len(cells))
    return out


def table():
    """(rows sorted best first, bench). A row: {firm, avg, n, by: {election: error}}; bench = mean of all single errors."""
    err = errors()
    rows = [{"firm": f, "avg": sum(e for _, e, _ in b.values()) / len(b), "n": len(b),
             "by": {el: b[el][1] for el in ELECTIONS if el in b}} for f, b in err.items()]
    rows.sort(key=lambda r: r["avg"])
    allerr = [e for b in err.values() for _, e, _ in b.values()]
    return rows, (sum(allerr) / len(allerr) if allerr else None)


def weights(k=3.0):
    """{firm: weight} for a poll average. A firm's error is shrunk to the mean of all firms as n / (n + k) (k = 3: one
    election counts a quarter, three elections a half), then weight = bench / shrunk error, so an average firm has 1.
    Firms without a record get 1. Range of the weights is narrow on purpose (the record is thin)."""
    rows, bench = table()
    w = {}
    for r in rows:
        s = r["n"] / (r["n"] + k)
        w[r["firm"]] = bench / (s * r["avg"] + (1 - s) * bench)
    return w


def ranks(xs):
    order = sorted(range(len(xs)), key=xs.__getitem__)
    r = [0.0] * len(xs)
    for i, j in enumerate(order):
        r[j] = float(i)
    return r


def house_check(min_obs=8):
    """[(firm, past error, mean |house effect|, parties)], Spearman rho between the two.
    Mean |house effect| = mean over the parties of forecast.py (>= min_obs polls of the firm in that party) of the firm's
    fitted house effect in points (distance from the average firm today). A positive rho says: firms that sit far from the
    consensus now were also far from the ballot before, so the house effects carry real information, not only noise."""
    import forecast as F  # imports nikh_polls / nikh_pollerror, no database
    rows, _ = table()
    out = []
    for r in rows:
        key = r["firm"].replace(" RC", "")
        hs = []
        for p in F.PARTIES:
            obs, h, *_ = F.fitted(p)
            if key in h and sum(1 for o in obs if o[1] == key) >= min_obs:
                hs.append(abs(h[key]))
        if hs:
            out.append((r["firm"], r["avg"], sum(hs) / len(hs), len(hs)))
    ra, rb = ranks([o[1] for o in out]), ranks([o[2] for o in out])
    m = (len(out) - 1) / 2  # the mean of both rank lists
    cov = sum((a - m) * (b - m) for a, b in zip(ra, rb, strict=True))
    var = sum((a - m) ** 2 for a in ra)
    return out, (cov / var if var else 0.0)


def main():
    rows, bench = table()
    print(f"Μέσο σφάλμα όλων των δημοσκοπήσεων: {bench:.2f} μον. (κόμματα ≥ {MIN_BALLOT:g}% στην κάλπη, "
          f"τελευταία δημοσκόπηση ≤ {WINDOW} ημέρες πριν)")
    print(f"{'εταιρεία':<18}{'μ.ό.':>6}{'n':>3}  " + "  ".join(f"{LABEL[e]:>10}" for e in ELECTIONS) + "  βάρος")
    w = weights()
    for r in rows:
        cells = "  ".join(f"{r['by'][e]:>10.2f}" if e in r["by"] else f"{'':>10}" for e in ELECTIONS)
        print(f"{r['firm']:<18}{r['avg']:>6.2f}{r['n']:>3}  {cells}  {w[r['firm']]:>5.2f}")
    out, rho = house_check()
    print("\nΠαλιό σφάλμα και σημερινή απόσταση από τον μέσο όρο (μ.ό. |σταθερής απόκλισης| στα κόμματα με ≥ 8 δημοσκοπήσεις):")
    for f, e, h, k in sorted(out, key=lambda o: o[1]):
        print(f"{f:<18}{e:>6.2f}{h:>8.2f}  ({k} κόμματα)")
    print(f"Spearman ρ = {rho:.2f} (n = {len(out)} εταιρείες)")
    import forecast as F
    a, b = F.levels(), F.levels(weighted=True)
    print("\nΕπίπεδο σήμερα, χωρίς και με βάρη (% έγκυρων, μέση εταιρεία):")
    for p, (x, sd) in a.items():
        xw, sdw = b[p]
        print(f"{p:<14}{x:>6.2f} ± {sd:.2f}   {xw:>6.2f} ± {sdw:.2f}   διαφορά {xw - x:+.2f}")


if __name__ == "__main__":
    main()
