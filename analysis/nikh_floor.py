"""NIKH floor: the votes it keeps whatever the election (A5 of NIKH_plan2.md).

Per ELSTAT community (area_match): share_e = NIKH votes / valid votes in election e, for May 2023, June 2023 and Euro 2024.
Floor share = min of the three; floor votes = floor share x June 2023 valid votes of the community.
Summed nationwide and per region (config.REGIONS), next to the votes of the poll level today (nikh_polls.estimate(0)) and
the 3% threshold (zones.threshold).
Only communities matched in all three elections count (coverage is printed), so the floor is a lower bound; "scaled" divides
by the coverage of the June 2023 valid votes, assuming the unmatched part behaves the same. Not tested.
Different electorates and turnouts: a floor in shares is not a promise in votes. Turnout check (valid / registered per
election): which election sets the minimum; the floor in absolute votes (min of NIKH votes over the elections, no
denominator) and over the two national elections only; and, per community, the weighted slope of the change of NIKH's share
on the change of turnout from June 2023 to Euro 2024 (bootstrap 1000 communities, seed 2026). Ecological: it compares
places, not voters.

  python -I -X utf8 analysis/nikh_floor.py data/stavroi.sqlite
"""
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import NIKH, REGIONS
from zones import threshold, valid_votes

ELECTIONS = ("2023/may", "2023/june", "2024/euro")


def community_rows(c):
    """{(comm_code, ep_id): {election: (valid, NIKH votes, registered)}} for communities present in all three elections."""
    out = defaultdict(dict)
    for e in ELECTIONS:
        for code, ep, valid, v, reg in c.execute(
                "SELECT a.comm_code, s.ep_id, SUM(s.valid), SUM(COALESCE(p.votes, 0)), SUM(s.registered) FROM area_match a "
                "JOIN station s ON s.election=a.election AND s.tm_id=a.tm_id "
                "LEFT JOIN party_votes p ON p.election=s.election AND p.tm_id=s.tm_id AND p.party_id=? "
                "WHERE a.election=? GROUP BY 1, 2", (NIKH, e)):
            out[(code, ep)][e] = (valid, v, reg)
    return {k: v for k, v in out.items() if len(v) == len(ELECTIONS) and all(x[0] and x[2] for x in v.values())}


def floors(rows):
    """{key: (floor share, floor votes)}: min share over the elections, times the June 2023 valid votes."""
    out = {}
    for k, d in rows.items():
        share = min(v / valid for valid, v, _ in d.values())
        out[k] = (share, share * d["2023/june"][0])
    return out


if __name__ == "__main__":
    c = sqlite3.connect(sys.argv[1])
    rows = community_rows(c)
    fl = floors(rows)
    june_valid = valid_votes(c)
    june_nikh = c.execute("SELECT SUM(votes) FROM party_votes WHERE election='2023/june' AND party_id=?", (NIKH,)).fetchone()[0]
    thr = threshold(c)
    m_valid = sum(d["2023/june"][0] for d in rows.values())
    m_nikh = sum(d["2023/june"][1] for d in rows.values())
    F = sum(v for _, v in fl.values())
    # self-check: the floor of every community is at most its June 2023 votes, so the sum is too
    assert F <= m_nikh + 1e-6 and all(0 <= s <= 1 for s, _ in fl.values())
    cov = m_valid / june_valid
    print(f"{len(rows):,} κοινότητες με αντιστοίχιση και στις 3 εκλογές: {100 * cov:.0f}% των έγκυρων του Ιουνίου 2023 "
          f"({m_valid:,} από {june_valid:,}), {100 * m_nikh / june_nikh:.0f}% των ψήφων ΝΙΚΗΣ ({m_nikh:,} από {june_nikh:,}).")
    print(f"\nΤαπεινό όριο (floor): {F:,.0f} ψήφοι = {100 * F / m_valid:.2f}% των έγκυρων των αντιστοιχισμένων κοινοτήτων")
    print(f"  κλιμακωμένο στο σύνολο (διαίρεση με την κάλυψη): {F / cov:,.0f} ψήφοι = {100 * F / m_valid:.2f}% των έγκυρων")
    print(f"  όριο 3%: {thr:,} ψήφοι. Το floor είναι {100 * F / cov / thr:.0f}% του ορίου.")
    for e in ELECTIONS:
        n = sum(d[e][1] for d in rows.values())
        print(f"  ψήφοι ΝΙΚΗΣ στις αντιστοιχισμένες, {e}: {n:,} (floor/εκλογή {100 * F / n:.0f}%)")
    try:
        import nikh_polls as P
        mu, _ = P.estimate(0)
        print(f"  Σήμερα, μέσος όρος δημοσκοπήσεων {mu:.2f}% = {mu / 100 * june_valid:,.0f} ψήφοι (έγκυρα Ιουνίου 2023): "
              f"floor/δημοσκοπήσεις {100 * F / cov / (mu / 100 * june_valid):.0f}%")
    except Exception as ex:  # polls file missing or changed: the floor itself stands
        print(f"  (δημοσκοπήσεις μη διαθέσιμες: {ex})")

    reg_of = {ep: name for name, eps in REGIONS for ep in eps}
    by = defaultdict(lambda: [0.0, 0, 0])  # floor votes, June matched votes, June matched valid
    for (code, ep), (s, v) in fl.items():
        r = by[reg_of.get(ep, "άγνωστη")]
        r[0] += v
        r[1] += rows[(code, ep)]["2023/june"][1]
        r[2] += rows[(code, ep)]["2023/june"][0]
    print("\nΑνά περιφέρεια (αντιστοιχισμένες κοινότητες)")
    print(f"  {'περιφέρεια':<32}{'floor':>9}{'% έγκυρων':>11}{'Ιούν. 2023':>12}{'floor/Ιούν.':>13}")
    for name, (f, j, valid) in sorted(by.items(), key=lambda x: -x[1][0]):
        print(f"  {name:<32}{f:>9,.0f}{100 * f / valid:>10.2f}%{j:>12,}{100 * f / j:>12.0f}%")

    # how many communities carry the floor
    ranked = sorted(fl.values(), key=lambda x: -x[1])
    acc = 0
    for i, (_, v) in enumerate(ranked, 1):
        acc += v
        if acc >= 0.5 * F:
            print(f"\nΤο 50% του floor βρίσκεται στις {i:,} κοινότητες ({100 * i / len(ranked):.0f}% των κοινοτήτων).")
            break

    # turnout: the three elections had different turnouts, so a floor in shares mixes electorates
    print("\nΣυμμετοχή (αντιστοιχισμένες κοινότητες, έγκυρα / εγγεγραμμένοι)")
    for e in ELECTIONS:
        reg, val, n = (sum(d[e][i] for d in rows.values()) for i in (2, 0, 1))
        print(f"  {e:<10} συμμετοχή {100 * val / reg:.1f}%, ΝΙΚΗ {n:,} ψήφοι = {100 * n / val:.2f}% των έγκυρων = "
              f"{100 * n / reg:.2f}% των εγγεγραμμένων; 3% των έγκυρων = {.03 * val:,.0f}")
    which, which_v = defaultdict(int), defaultdict(float)
    for k, d in rows.items():
        e = min(ELECTIONS, key=lambda e: d[e][1] / d[e][0])  # ties go to the first election
        which[e] += 1
        which_v[e] += fl[k][1]
    print("  Ποια εκλογή δίνει το ελάχιστο ποσοστό: " + ", ".join(
        f"{e} {which[e]:,} κοινότητες ({100 * which_v[e] / F:.0f}% του floor)" for e in ELECTIONS))

    nat = ELECTIONS[:2]
    var = {"ποσοστό, τρεις εκλογές (όπως πάνω)": F,
           "ποσοστό, μόνο οι εθνικές (Μάιος, Ιούνιος 2023)":
               sum(min(d[e][1] / d[e][0] for e in nat) * d["2023/june"][0] for d in rows.values()),
           "απόλυτες ψήφοι, τρεις εκλογές": sum(min(d[e][1] for e in ELECTIONS) for d in rows.values()),
           "απόλυτες ψήφοι, μόνο οι εθνικές": sum(min(d[e][1] for e in nat) for d in rows.values())}
    # self-checks: a min over fewer elections is at least the min over all; absolute floor <= every election's votes
    assert var["ποσοστό, μόνο οι εθνικές (Μάιος, Ιούνιος 2023)"] >= F - 1e-6
    assert var["απόλυτες ψήφοι, μόνο οι εθνικές"] >= var["απόλυτες ψήφοι, τρεις εκλογές"]
    assert all(var["απόλυτες ψήφοι, τρεις εκλογές"] <= sum(d[e][1] for d in rows.values()) for e in ELECTIONS)
    print("\nΕκδοχές του floor (απόλυτες ψήφοι: όσοι ψήφισαν ΝΙΚΗ σε κάθε εκλογή, χωρίς παρονομαστή συμμετοχής)")
    for name, v in var.items():
        print(f"  {name:<48}{v:>9,.0f} ψήφοι = {100 * v / m_valid:.2f}% των έγκυρων Ιουνίου 2023, {100 * v / cov / thr:.0f}% του ορίου")

    # differential turnout, June 2023 -> Euro 2024: does NIKH's share rise where turnout fell more?
    pts = []
    for d in rows.values():
        (vj, nj, rj), (ve, ne, re_) = d["2023/june"], d["2024/euro"]
        pts.append((100 * (ve / re_ - vj / rj), 100 * (ne / ve - nj / vj), vj))

    def wslope(ps):
        sw = sum(w for *_, w in ps)
        mx, my = sum(x * w for x, _, w in ps) / sw, sum(y * w for _, y, w in ps) / sw
        sxx = sum(w * (x - mx) ** 2 for x, _, w in ps)
        return sum(w * (x - mx) * (y - my) for x, y, w in ps) / sxx, mx, my

    assert abs(wslope([(1, 2, 1), (2, 4, 1), (3, 6, 2)])[0] - 2) < 1e-9  # y = 2x gives slope 2
    b, mx, my = wslope(pts)
    rng = random.Random(2026)
    boot = sorted(wslope([pts[rng.randrange(len(pts))] for _ in pts])[0] for _ in range(1000))
    print("\nΙούνιος 2023 → Ευρωεκλογές 2024, ανά κοινότητα (στάθμιση με τα έγκυρα Ιουνίου): μεταβολή ποσοστού ΝΙΚΗΣ (μονάδες) "
          "ως προς μεταβολή συμμετοχής (μονάδες)")
    print(f"  μέση μεταβολή συμμετοχής {mx:+.1f}, μέση μεταβολή ποσοστού ΝΙΚΗΣ {my:+.2f}")
    print(f"  κλίση {b:+.4f} μονάδες ποσοστού ανά μονάδα συμμετοχής (95% bootstrap 1000, σπόρος 2026: "
          f"{boot[24]:+.4f} έως {boot[974]:+.4f})")
    for lo, hi in ((-99, -15), (-15, -10), (-10, -5), (-5, 99)):
        g = [(x, y, w) for x, y, w in pts if lo <= x < hi]
        if g:
            sw = sum(w for *_, w in g)
            print(f"  μεταβολή συμμετοχής {lo:>+4} έως {hi:>+3}: {len(g):>5,} κοινότητες, μέση μεταβολή ποσοστού ΝΙΚΗΣ "
                  f"{sum(y * w for _, y, w in g) / sw:+.2f}")
