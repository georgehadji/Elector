"""Who moves against NIKH in the polls: changes of the other parties between consecutive polls of the same firm (A3 of NIKH_plan2.md).

Data: analysis/nikh_polls.csv (niki column hand-checked; the other party columns come from polls_wiki.py, Wikipedia, not
checked against the firms' releases). An empty cell = the party was not shown in that poll (not 0).
1. Pairs: two consecutive polls of the same firm, at most 120 days apart; change = later - earlier. The house effect cancels.
   For each party: correlation and OLS slope of the change of NIKH on the change of the party (pairs where both are present),
   whole period and before / after 20 Apr 2026 (when two new parties, ELPIDA and ELAS, enter the polls).
   Permutation test: the changes of NIKH are shuffled among the pairs 2000 times (seed 2026); the p of a party is the share of
   shuffles whose largest |correlation| over all parties of the period is at least its own (so 13 parties are tested at once).
2. Window comparison, the fall of Apr-Jul 2026: per firm, mean of each party in 1 Jan-19 Apr 2026 vs 1 Jul-22 Nov 2026
   (firms with NIKH in both); mean change over firms. A party not yet in the polls in the first window counts as 0 there;
   a party absent from a window's polls of a firm that has it in the other is skipped for that firm.
This is a correlation of published totals, not a count of voters moving: shares that sum to 100 move against each other by
arithmetic, and the changes carry sampling noise (about 0.3 points for NIKH).

  python -I -X utf8 analysis/nikh_flows.py
"""
import csv
import math
import random
from datetime import date
from pathlib import Path

CSV = Path(__file__).resolve().parent / "nikh_polls.csv"
NEW = date(2026, 4, 20)
PARTIES = ["ND", "SYRIZA", "PASOK", "KKE", "SP", "EL", "PE", "M25", "FL", "NA", "SE", "DPK", "ELPIDA", "ELAS"]
MIN_PAIRS = 25


def load():
    """[(firm, end, {party or 'niki': pct})] sorted by date; firm = first part of 'Firm/Commissioner' (as nikh_polls.load)."""
    with open(CSV, encoding="utf-8") as f:
        rows = [(r["firm"].split("/")[0].replace(" RC", "").strip(), date.fromisoformat(r["end"]),
                 {c: float(r[c]) for c in ["niki"] + PARTIES if r[c] != ""}) for r in csv.DictReader(f)]
    return sorted(rows, key=lambda r: r[1])


def pairs(rows, gap=120):
    """[(later date, {column: later - earlier})] over consecutive polls of the same firm."""
    last, out = {}, []
    for firm, d, v in rows:
        if firm in last and (d - last[firm][0]).days <= gap:
            p = last[firm][1]
            out.append((d, {c: v[c] - p[c] for c in v if c in p}))
        last[firm] = (d, v)
    return out


def corr_slope(x, y):
    """(correlation, slope of y on x, standard error of the slope) of paired lists."""
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx, syy, sxy = (sum((a - mx) ** 2 for a in x), sum((b - my) ** 2 for b in y), sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)))
    if sxx == 0 or syy == 0:
        return 0.0, 0.0, 0.0
    b = sxy / sxx
    se = math.sqrt(max(syy - b * sxy, 0) / max(n - 2, 1) / sxx)
    return sxy / math.sqrt(sxx * syy), b, se


def table(title, ps, rng):
    print(f"\n{title}: {len(ps)} ζεύγη διαδοχικών δημοσκοπήσεων της ίδιας εταιρείας")
    res = {}
    for c in PARTIES:
        xy = [(p[c], p["niki"]) for _, p in ps if c in p and "niki" in p]
        if len(xy) >= MIN_PAIRS:
            res[c] = xy
    if not res:
        return
    obs = {c: corr_slope(*zip(*xy, strict=True)) for c, xy in res.items()}
    cols = {c: ([a for a, _ in xy], [b for _, b in xy]) for c, xy in res.items()}
    mx = []
    for _ in range(2000):  # the changes of NIKH are shuffled among the pairs of each party
        best = 0.0
        for xs, ys in cols.values():
            ys = ys[:]
            rng.shuffle(ys)
            best = max(best, abs(corr_slope(xs, ys)[0]))
        mx.append(best)
    print(f"  {'κόμμα':<8}{'ζεύγη':>6}{'συσχέτιση':>11}{'κλίση ΝΙΚΗΣ ανά +1':>20}{'p (όλα μαζί)':>14}")
    for c in sorted(obs, key=lambda c: obs[c][0]):
        r, b, se = obs[c]
        p = sum(m >= abs(r) for m in mx) / len(mx)
        print(f"  {c:<8}{len(res[c]):>6}{r:>+11.2f}{f'{b:+.3f} ± {1.96 * se:.3f}':>20}{p:>14.3f}")


def windows(rows, a=(date(2026, 1, 1), date(2026, 4, 19)), b=(date(2026, 7, 1), date(2026, 11, 22))):
    """{firm: ({col: mean in window a}, {col: mean in window b})} for firms with NIKH in both windows."""
    def mean(firm, w):
        acc = {}
        for f, d, v in rows:
            if f == firm and w[0] <= d <= w[1]:
                for c, x in v.items():
                    acc.setdefault(c, []).append(x)
        return {c: sum(xs) / len(xs) for c, xs in acc.items()}
    out = {}
    for firm in {f for f, *_ in rows}:
        ma, mb = mean(firm, a), mean(firm, b)
        if "niki" in ma and "niki" in mb:
            out[firm] = (ma, mb)
    return out


if __name__ == "__main__":
    # self-check: if party B takes exactly what party A loses, the slope of A's change on B's change is -1
    xs = [0.5, -1.0, 2.0, 0.0, -0.5, 1.5]
    assert abs(corr_slope(xs, [-x for x in xs])[1] + 1) < 1e-9 and abs(corr_slope(xs, [-x for x in xs])[0] + 1) < 1e-9
    rows = load()
    ps = pairs(rows)
    rng = random.Random(2026)
    print(f"{len(rows)} δημοσκοπήσεις, {len(ps)} ζεύγη (≤ 120 ημέρες μεταξύ τους).")
    table("Όλη η περίοδος", ps, rng)
    table("Πριν τις 20.4.2026", [x for x in ps if x[0] < NEW], rng)
    table("Από τις 20.4.2026", [x for x in ps if x[0] >= NEW], rng)

    w = windows(rows)
    print(f"\nΠαράθυρα: 1.1–19.4.2026 έναντι 1.7–22.11.2026, {len(w)} εταιρείες με ΝΙΚΗ και στα δύο: {', '.join(sorted(w))}")
    print(f"  {'κόμμα':<8}{'εταιρείες':>10}{'πριν':>8}{'μετά':>8}{'αλλαγή':>9}")
    for c in ["niki"] + PARTIES:
        d = []
        for ma, mb in w.values():
            a = ma.get(c, 0.0 if c in ("ELPIDA", "ELAS", "SE") and c in mb else None)
            if a is not None and c in mb:
                d.append((a, mb[c]))
        if d:
            a, b = (sum(x[i] for x in d) / len(d) for i in (0, 1))
            print(f"  {c:<8}{len(d):>10}{a:>8.2f}{b:>8.2f}{b - a:>+9.2f}")
