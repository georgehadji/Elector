"""How far the ballot is from the polls for small parties: ballot / poll average, Greek elections 2007-2024 (A1 of NIKH_plan2.md).

Data: analysis/nikh_pollerror.csv (polls_wiki.py: Wikipedia tables, not checked against the firms' releases). The ballot is
rounded to 0.1 in the tables.
- Poll average of a party at an election = plain mean of its polls ending 1-14 days before the election day (the window
  of nikh_polls.miss_2023). A party needs >= 2 such polls and an average of 1.0-4.0% to enter the sample ("small").
- Ratio = ballot / poll average. NIKH (Niki, Victory) is left out of the sample and listed apart.
- Groups (national elections): new = first poll of the party less than a year before the election, in a table that starts
  more than 500 days before; rising / falling = mean of the last 14 days is >= 1.2x / <= 0.8x the mean of the polls 60-120 days
  before (needs >= 2 polls there); other = the rest.
- Base rate: parties at 1.0-1.8% in the polls 150-210 days before the election (mean of >= 2 polls), and how many got >= 3%.
- The parties are the columns of the Wikipedia tables, which are chosen after the fact: a party that fell out of the polls or
  never got a column is missing. The sample is biased towards parties that did get measured. Elections are not independent draws.
ratios(kind) gives the sorted ratios for nikh_montecarlo.py (kind: all, new, rising, falling, other, national, euro).

  python -I -X utf8 analysis/nikh_pollerror.py
"""
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

CSV = Path(__file__).resolve().parent / "nikh_pollerror.csv"
EURO = ("2014/euro", "2019/euro", "2024/euro")
LO, HI = 1.0, 4.0


def is_niki(party):
    return party.startswith(("Niki", "Victory"))


def load():
    """({election: {party: [(end, pct)]}}, {election: {party: ballot pct}}, {election: election day})."""
    polls, ballots, day = defaultdict(lambda: defaultdict(list)), defaultdict(dict), {}
    with open(CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            end = date.fromisoformat(r["end"])
            if r["kind"] == "ballot":
                ballots[r["election"]][r["party"]] = float(r["pct"])
                day[r["election"]] = end
            else:
                polls[r["election"]][r["party"]].append((end, float(r["pct"])))
    return polls, ballots, day


def mean_between(ps, lo, hi, e):
    """(mean, n) of the polls ending between `lo` and `hi` days before day e (lo < days <= hi)."""
    xs = [v for d, v in ps if lo < (e - d).days <= hi]
    return (sum(xs) / len(xs), len(xs)) if xs else (None, 0)


def pairs():
    """One dict per (election, party) with >= 2 polls in the last 14 days, a ballot figure and a poll average in LO..HI."""
    polls, ballots, day = load()
    out = []
    for el, parties in polls.items():
        e = day[el]
        first_any = min(d for ps in parties.values() for d, _ in ps)
        for p, ps in parties.items():
            if p not in ballots[el]:
                continue
            avg, n = mean_between(ps, 0, 14, e)
            if n < 2 or not LO <= avg <= HI:
                continue
            early, ne = mean_between(ps, 60, 120, e)
            new = el not in EURO and (e - min(d for d, _ in ps)).days < 365 and (e - first_any).days > 500
            group = "new" if new else "rising" if ne >= 2 and avg >= 1.2 * early else "falling" if ne >= 2 and avg <= 0.8 * early else "other"
            out.append({"el": el, "party": p, "avg": avg, "n": n, "ballot": ballots[el][p], "ratio": ballots[el][p] / avg,
                        "group": group, "niki": is_niki(p)})
    return out


def ratios(kind="all"):
    """Sorted ballot / poll-average ratios of the small parties other than NIKH."""
    pick = {"all": lambda x: True, "national": lambda x: x["el"] not in EURO, "euro": lambda x: x["el"] in EURO,
            "lt2": lambda x: x["avg"] < 2, "2to3": lambda x: 2 <= x["avg"] < 3, "ge3": lambda x: x["avg"] >= 3}
    keep = pick.get(kind, lambda x: x["group"] == kind)
    return sorted(x["ratio"] for x in pairs() if not x["niki"] and keep(x))


def q(xs, f):
    return xs[min(len(xs) - 1, int(f * len(xs)))]


def summary(xs):
    n = len(xs)
    return (f"n {n:>3}, median {q(xs, .5):.2f}, mean {sum(xs) / n:.2f}, 10%-90% {q(xs, .1):.2f}-{q(xs, .9):.2f}, "
            f"quartiles {q(xs, .25):.2f}-{q(xs, .75):.2f}, ratio > 1 in {100 * sum(x > 1 for x in xs) / n:.0f}%, ratio >= 1.5 in {100 * sum(x >= 1.5 for x in xs) / n:.0f}%")


def base_rate():
    """[(election, party, mean of the polls 150-210 days before, ballot)] for parties at 1.0-1.8% then."""
    polls, ballots, day = load()
    out = []
    for el, parties in polls.items():
        if el in EURO:
            continue
        for p, ps in parties.items():
            avg, n = mean_between(ps, 150, 210, day[el])
            if n >= 2 and 1.0 <= avg <= 1.8 and p in ballots[el]:
                out.append((el, p, avg, ballots[el][p]))
    return sorted(out)


if __name__ == "__main__":
    # self-check: the NIKH ratios of nikh_polls.miss_2023 (May 1.87, June 1.14), from Wikipedia ballots rounded to 0.1
    for el, want in (("2023/may", 1.87), ("2023/june", 1.14)):
        x = next(x for x in pairs() if x["el"] == el and x["niki"])
        assert abs(x["ratio"] - want) < 0.03, (el, x["ratio"])
    P = pairs()
    S = [x for x in P if not x["niki"]]
    print(f"Δείγμα: {len(S)} ζεύγη εκλογών-κόμματος με μέσο όρο δημοσκοπήσεων {LO}-{HI}% και ≥ 2 δημοσκοπήσεις στις τελευταίες 14 ημέρες, "
          f"από {len({x['el'] for x in S})} εκλογές (χωρίς ΝΙΚΗ).")
    print("\nΛόγος κάλπη / μέσος όρος δημοσκοπήσεων, ανά ομάδα")
    for kind in ("all", "national", "euro", "new", "rising", "falling", "other", "lt2", "2to3", "ge3"):
        xs = ratios(kind)
        print(f"  {kind:<9} {summary(xs) if xs else 'κανένα'}")
    print("  (lt2 = μέσος όρος δημοσκοπήσεων κάτω από 2%, 2to3 = 2-3%, ge3 = 3-4%)")
    print("\nΝΙΚΗ (δεν είναι στο δείγμα): " + ", ".join(f"{x['el']} {x['ratio']:.2f} (δημοσκ. {x['avg']:.2f}%, κάλπη {x['ballot']}%)" for x in P if x["niki"]))
    print("\nΑνά εκλογή: μεσαίος λόγος και πλήθος")
    for el in sorted({x["el"] for x in S}):
        xs = sorted(x["ratio"] for x in S if x["el"] == el)
        print(f"  {el:<10} n {len(xs):>2}, median {q(xs, .5):.2f}, εύρος {xs[0]:.2f}-{xs[-1]:.2f}")
    print("\nΚάθε ζεύγος (ταξινομημένα κατά εκλογή και λόγο)")
    for x in sorted(S, key=lambda x: (x["el"], x["ratio"])):
        print(f"  {x['el']:<10}{x['party'][:38]:<39}δημοσκ. {x['avg']:.2f}% ({x['n']})  κάλπη {x['ballot']:>4}%  λόγος {x['ratio']:.2f}  {x['group']}")
    B = base_rate()
    print(f"\nΒασικό ποσοστό: κόμματα με 1,0-1,8% στις δημοσκοπήσεις 150-210 ημέρες πριν (εθνικές εκλογές): {len(B)}")
    for el, p, a, b in B:
        print(f"  {el:<10}{p[:38]:<39}{a:.2f}% -> {b}%{'  ≥ 3%' if b >= 3 else ''}")
    if B:
        print(f"  Πέρασαν το 3%: {sum(b >= 3 for *_, b in B)} από {len(B)}")
        print(f"  Κάλπη / δημοσκοπήσεις 150-210 ημέρες πριν, διάμεσος: {q(sorted(b / a for _, _, a, b in B), .5):.2f}")
