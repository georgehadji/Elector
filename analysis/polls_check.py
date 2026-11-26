"""Check of nikh_pollerror.csv (English Wikipedia, polls_wiki.py) against a second source, polls_second.csv: the poll tables
of el.wikipedia (2007, 2009, 2014/euro, 2019, 2019/euro, 2023/june, 2024/euro) and of de/fr.wikipedia for the rest (often
translations of the English tables, so a weak check there; 2012/may has none with full dates). Columns: election, source,
firm, end, sample, party (the Greek names of pollster_coef.PARTY), pct, basis (raw = vote intention with the undecided in,
estimate, or "" when the page does not say).

A poll of the second source is matched to the poll of the same election and firm (pollster_coef.firm) ending within 2 days,
the one with the closest figures. Bases differ (one source gives raw intention, the other the estimate), so the second
source's figures are scaled by the ratio of the two sums over the parties both list, when it is more than 3% off 1. A cell
is flagged when, after that, it differs by more than 0.5 points and 5%. Then: how much pollster_coef's k moves without the
flagged polls. Polls more than 400 days before the election are left out (the pages' windows are wider than a campaign).

    python -I -X utf8 analysis/polls_check.py   -> analysis/polls_check.txt
"""
import csv
import math
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pollster_coef as C

SECOND, OUT = HERE / "polls_second.csv", HERE / "polls_check.txt"
DAYS, GAP, REL = 2, 0.5, 0.05


def flags():
    """(matched polls, matched cells, [(election, firm, end, source, basis, scale, party, primary, second, residual)])."""
    ps, _, day = C.polls()
    prim = defaultdict(list)
    for el, fm, end, row in ps:
        prim[el, fm].append((end, {C.PARTY[p]: y for p, y in row.items() if p in C.PARTY}))
    sec = defaultdict(dict)
    with open(SECOND, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["pct"]:
                sec[r["election"], C.firm(r["firm"]), r["end"], r["basis"], r["source"]][r["party"]] = float(r["pct"])
    n_polls = n_cells = 0
    out = []
    for (el, fm, end, basis, src), g in sec.items():
        e = date.fromisoformat(end)
        if not 0 <= (day[el] - e).days <= 400:
            continue
        cands = [(pe, pg) for pe, pg in prim.get((el, fm), []) if abs((pe - e).days) <= DAYS and set(g) & set(pg)]
        if not cands:
            continue
        pe, pg = min(cands, key=lambda c: sum(abs(c[1][p] - g[p]) for p in set(g) & set(c[1])) / len(set(g) & set(c[1])))
        common = sorted(set(g) & set(pg))
        sc = sum(pg[p] for p in common) / sum(g[p] for p in common)
        sc = sc if abs(sc - 1) > 0.03 else 1.0
        n_polls, n_cells = n_polls + 1, n_cells + len(common)
        for p in common:
            res = pg[p] - sc * g[p]
            if abs(res) > GAP and abs(res) / max(pg[p], 0.1) > REL:
                out.append((el, fm, str(pe), src, basis or "?", sc, p, pg[p], g[p], res))
    return n_polls, n_cells, sorted(out)


def main():
    n_polls, n_cells, fl = flags()
    _, _, day = C.polls()
    bad = {(f[0], f[1], f[2]) for f in fl}
    cs = C.cells()
    kept = [c for c in cs if (c[0], c[1], str(day[c[0]] - timedelta(c[3]))) not in bad]
    a = {(r["firm"], r["party"]): r for r in C.coefficients(cs)}
    b = {(r["firm"], r["party"]): r for r in C.coefficients(kept)}
    ch = sorted(((abs(math.log(b[k]["k"] / a[k]["k"])), k) for k in a if k in b), reverse=True)
    big = [x for x in ch if a[x[1]]["n_polls"] >= 20]
    lines = [f"Δεύτερη πηγή: {n_polls} δημοσκοπήσεις ταιριάζουν ({n_cells} τιμές κόμματος). Διαφέρουν πάνω από {GAP} μονάδες "
             f"(και {100 * REL:.0f}%) μετά την αναγωγή βάσης: {len(fl)} τιμές σε {len(bad)} δημοσκοπήσεις.",
             "Ανά εκλογές: " + ", ".join(f"{el} {n}" for el, n in sorted(Counter(f[0] for f in fl).items())),
             f"Χωρίς αυτές τις δημοσκοπήσεις το k αλλάζει >2% σε {sum(x[0] > .02 for x in ch)} από {len(ch)} ζεύγη εταιρείας-κόμματος, "
             f"σε ζεύγη με >= 20 δημοσκοπήσεις έως {100 * (math.exp(big[0][0]) - 1):.1f}% ({big[0][1][0]}, {big[0][1][1]})." if big else "",
             "", "εκλογές, εταιρεία, λήξη, πηγή, βάση, αναγωγή, κόμμα, εδώ, δεύτερη πηγή, διαφορά μετά την αναγωγή"]
    lines += [f"{el:10}{fm:17}{end}  {src:13}{basis:9}{sc:6.3f}  {p:20}{x:6.1f}{y:6.1f}{r:+6.1f}" for el, fm, end, src, basis, sc, p, x, y, r in fl]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:4]))


if __name__ == "__main__":
    main()
