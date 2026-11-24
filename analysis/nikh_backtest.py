"""Backtest of the zone score (A4 of NIKH_plan2.md): does a score built from 2023 predict where NIKH votes in Euro 2024?

Units and tiers: zones.py (municipal units, A = first 20% of the registered voters, B = next 30%, C = rest).
Rules, each ranks the units best first:
- zone2023  the zone score of nikh_pareto.py with 2023 only: peak = max(May, June 2023) votes / registered
- share     June 2023 share of valid votes
- votes     June 2023 votes (absolute)
- oracle    Euro 2024 votes / registered (upper bound: it sees the answer)
Outcome: Euro 2024 NIKH votes. Capture(x) = share of the Euro 2024 votes that sit in the first x% of the registered voters
(a random order gives x). Also Spearman correlation between the score and the Euro 2024 yield (votes per registered).
Bootstrap: 1000 resamples of the units with replacement (seed 2026), the same resample for every rule; 95% interval = 2.5-97.5
percentile. Differences are paired. One election pair, one party: the result says how stable the vote was between 2023 and 2024,
not how it will move in 2026. Euro 2024 has lower turnout than a national election.
Any other party: --party=ID (see party.py); nothing here is NIKH-only input, the rules use only that party's votes.

  python -I -X utf8 analysis/nikh_backtest.py data/stavroi.sqlite [--party=ID] [--rival=ID]
"""
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
import party
from zones import assign_tiers, load_units

ELECTIONS = ("2023/may", "2023/june", "2024/euro")
RULES = {"zone2023": lambda u: max(u["v"]["2023/may"], u["v"]["2023/june"]) / u["reg"],
         "share": lambda u: u["v"]["2023/june"] / u["valid"] if u["valid"] else 0.0,
         "votes": lambda u: u["v"]["2023/june"],
         "oracle": lambda u: u["v"]["2024/euro"] / u["reg"]}
CUTS = (0.2, 0.5)


def capture(order, units, cut):
    """Share of Euro 2024 votes in the first `cut` of the registered voters, units taken in the given order (indices)."""
    total_reg = sum(units[i]["reg"] for i in order)
    total_euro = sum(units[i]["v"]["2024/euro"] for i in order)
    acc = got = 0
    for i in order:
        acc += units[i]["reg"]
        if acc > cut * total_reg:
            break
        got += units[i]["v"]["2024/euro"]
    return got / total_euro


def ranks(xs):
    """Average ranks (ties share the mean rank)."""
    idx = sorted(range(len(xs)), key=lambda i: xs[i])
    r, i = [0.0] * len(xs), 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and xs[idx[j + 1]] == xs[idx[i]]:
            j += 1
        for k in range(i, j + 1):
            r[idx[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x, y):
    a, b = ranks(x), ranks(y)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    sab = sum((p - ma) * (q - mb) for p, q in zip(a, b, strict=True))
    return sab / (sum((p - ma) ** 2 for p in a) * sum((q - mb) ** 2 for q in b)) ** .5


def pct(xs, f):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(f * len(xs)))]


if __name__ == "__main__":
    c = sqlite3.connect(sys.argv[1])
    units = load_units(c, ELECTIONS, party.ID)
    n = len(units)
    # self-checks: no order beats the oracle by more than one unit (capture drops the unit that crosses the cut, so a rule can
    # fill the cut more fully; the fractional oracle is an upper bound and loses at most that one unit), and any order captures > 0
    pos = {name: sorted(range(n), key=lambda i: -f(units[i])) for name, f in RULES.items()}
    biggest = max(u["v"]["2024/euro"] for u in units) / sum(u["v"]["2024/euro"] for u in units)
    assert all(capture(pos["oracle"], units, x) + biggest >= capture(pos[r], units, x) for r in RULES for x in CUTS)
    assert all(capture(list(range(n)), units, x) > 0 for x in CUTS)
    print(f"{n} δημοτικές ενότητες, {sum(u['reg'] for u in units):,} εγγεγραμμένοι. Ευρωεκλογές 2024, ψήφοι {party.GEN}: "
          f"{sum(u['v']['2024/euro'] for u in units):,}")

    print("\nΖώνες από το σκορ του 2023 (μόνο Μάιος+Ιούνιος 2023), αποτέλεσμα Ευρωεκλογές 2024")
    z = sorted(units, key=lambda u: -RULES["zone2023"](u))
    assign_tiers(z)
    print(f"  {'ζώνη':<6}{'ενότητες':>9}{'εγγεγρ.':>11}{'κορυφή 2023':>13}{'Ευρ. 2024':>11}{'% Ευρ.':>8}{'ανά 100 εγγ.':>14}")
    te = sum(u["v"]["2024/euro"] for u in z)
    for t in "ABC":
        g = [u for u in z if u["tier"] == t]
        r, p, e = (sum(f(u) for u in g) for f in (lambda u: u["reg"], lambda u: max(u["v"]["2023/may"], u["v"]["2023/june"]),
                                                    lambda u: u["v"]["2024/euro"]))
        print(f"  {t:<6}{len(g):>9}{r:>11,}{p:>13,}{e:>11,}{100 * e / te:>7.0f}%{100 * e / r:>14.2f}")

    # same units, zones of the full score (nikh_pareto.py, three elections): how much of A and C is the same set
    tier23 = {u["k"]: u["tier"] for u in z}  # assign_tiers writes u["tier"] on the shared dicts: keep the 2023 zones first
    full = sorted(units, key=lambda u: -max(u["v"].values()) / u["reg"])
    assign_tiers(full)
    same = {t: sum(u["reg"] for u in units if tier23[u["k"]] == t and u["tier"] == t) /
            sum(u["reg"] for u in units if tier23[u["k"]] == t) for t in "ABC"}
    print("  Ίδια ζώνη με το σκορ τριών εκλογών (% των εγγεγραμμένων της ζώνης): "
          + ", ".join(f"{t} {100 * v:.0f}%" for t, v in same.items()))

    rng = random.Random(2026)
    BOOT = 1000
    pos_rank = {name: {i: k for k, i in enumerate(order)} for name, order in pos.items()}
    sample = {name: {x: [] for x in CUTS} for name in RULES}
    for _ in range(BOOT):
        draw = [rng.randrange(n) for _ in range(n)]
        tmp = [units[i] for i in draw]
        for name in RULES:
            order = sorted(range(n), key=lambda k: pos_rank[name][draw[k]])
            for x in CUTS:
                sample[name][x].append(capture(order, tmp, x))
    sp = {name: spearman([RULES[name](u) for u in units], [u["v"]["2024/euro"] / u["reg"] for u in units]) for name in RULES}
    print(f"\nΣύλληψη ψήφων Ευρωεκλογών 2024 στο πρώτο x% των εγγεγραμμένων (τυχαία σειρά: x%), bootstrap {BOOT} επαναλήψεων")
    print(f"  {'κανόνας':<10}{'Spearman':>10}" + "".join(f"{f'πρώτο {int(100 * x)}%':>26}" for x in CUTS))
    for name in RULES:
        cells = "".join(f"{100 * capture(pos[name], units, x):>9.1f}% [{100 * pct(sample[name][x], .025):.1f}-"
                        f"{100 * pct(sample[name][x], .975):.1f}]".rjust(26) for x in CUTS)
        print(f"  {name:<10}{sp[name]:>10.2f}{cells}")
    print("\nΔιαφορά zone2023 μείον κανόνα (εκατοστιαίες μονάδες, ζευγαρωτό bootstrap)")
    for name in ("share", "votes"):
        for x in CUTS:
            d = [100 * (a - b) for a, b in zip(sample["zone2023"][x], sample[name][x], strict=True)]
            print(f"  έναντι {name:<6} στο {int(100 * x)}%: {100 * (capture(pos['zone2023'], units, x) - capture(pos[name], units, x)):+.1f} "
                  f"[{pct(d, .025):+.1f}, {pct(d, .975):+.1f}]")
