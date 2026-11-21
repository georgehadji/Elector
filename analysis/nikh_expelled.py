"""Personal vote of the two MPs NIKH (party 131) expelled in 2025, and whether NIKH depends on it.

Παπαδόπουλος (Β' Θεσσαλονίκης) and Βρεττός (Β3' Νότιου Τομέα Αθηνών) were on the ballot with crosses in May 2023 only.
June 2023 was a closed list and neither ran in the Euro 2024 election, so the later change of NIKH in the districts
where their cross rate was highest shows how much of the party vote followed the person.
Cross rate = his crosses / NIKH votes. A voter could mark up to 3 (Β' Θεσ.) or 4 (Β3') candidates, so his crosses
are an upper bound on voters who chose him, not voters who came for him.

  python -I -X utf8 analysis/nikh_expelled.py data/stavroi.sqlite
"""
import sqlite3
import sys

import numpy as np

NIKH = 131
M, J, U = "2023/may", "2023/june", "2024/euro"
c = sqlite3.connect(sys.argv[1])


def districts(e, ep, level):
    """{key: (valid, NIKH votes)} for regular stations; level is the SQL key (unit, or unit and district)."""
    return {k[:-2]: k[-2:] for k in c.execute(
        f"SELECT {level}, SUM(s.valid), SUM(p.votes) FROM station s JOIN party_votes p ON p.election=s.election "
        f"AND p.tm_id=s.tm_id AND p.party_id=? WHERE s.election=? AND s.ep_id=? AND s.kind='Κ' GROUP BY {level}",
        (NIKH, e, ep))}


def crosses(ep, cid, level):
    return {k[:-1]: k[-1] for k in c.execute(
        f"SELECT {level}, SUM(p.votes) FROM station s JOIN cand_votes p ON p.election=s.election AND p.tm_id=s.tm_id "
        f"AND p.party_id=? AND p.cand_id=? WHERE s.election=? AND s.ep_id=? AND s.kind='Κ' GROUP BY {level}",
        (NIKH, cid, M, ep))}


def wcorr(a, b, w):
    ma, mb = np.average(a, weights=w), np.average(b, weights=w)
    return np.average((a - ma) * (b - mb), weights=w) / np.sqrt(
        np.average((a - ma) ** 2, weights=w) * np.average((b - mb) ** 2, weights=w))


for ep, cid in ((7, 8), (62, 2)):
    name = c.execute("SELECT name FROM candidate WHERE election=? AND ep_id=? AND party_id=? AND cand_id=?",
                     (M, ep, NIKH, cid)).fetchone()[0]
    ep_name = c.execute("SELECT name FROM ep WHERE election=? AND ep_id=?", (M, ep)).fetchone()[0]
    unit = {e: districts(e, ep, "s.den_descr") for e in (M, J, U)}
    x = crosses(ep, cid, "s.den_descr")
    tot = {e: [sum(v[i] for v in unit[e].values()) for i in (0, 1)] for e in (M, J, U)}
    mine = sum(x.values())
    print(f"\n{name}, {ep_name}: {mine:,} σταυροί τον Μάιο 2023 = {100 * mine / tot[M][1]:.0f}% των ψήφων της ΝΙΚΗΣ")
    print("  ΝΙΚΗ στην περιφέρεια: " + ", ".join(f"{e} {100 * tot[e][1] / tot[e][0]:.2f}% ({tot[e][1]:,})" for e in (M, J, U)))
    print(f"  {'δημοτική ενότητα':<24}{'σταυροί':>8}{'ανά ψήφο':>10}{'Μάιος':>8}{'Ιούνιος':>9}{'Ευρ. 24':>9}")
    for k in sorted(x, key=lambda k: -x[k])[:8]:
        print(f"  {k[0][:23]:<24}{x[k]:>8,}{x[k] / unit[M][k][1]:>10.2f}" +
              "".join(f"{100 * unit[e][k][1] / unit[e][k][0]:>{n}.1f}" for e, n in ((M, 8), (J, 9), (U, 9))))

    d = {e: districts(e, ep, "s.den_descr, s.ekd_descr") for e in (M, J, U)}
    dx = crosses(ep, cid, "s.den_descr, s.ekd_descr")
    ks = [k for k in d[M] if k in d[J] and k in d[U] and d[M][k][0] >= 200 and d[M][k][1] >= 10]
    w = np.array([d[M][k][0] for k in ks], float)
    rate = np.array([dx.get(k, 0) / d[M][k][1] for k in ks])
    pm, pj, pu = (np.array([100 * d[e][k][1] / d[e][k][0] for k in ks]) for e in (M, J, U))
    print(f"  {len(ks)} εκλογικά διαμερίσματα. Συσχέτιση του ποσοστού σταυρών του με: ΝΙΚΗ Μαΐου {wcorr(rate, pm, w):+.2f}, "
          f"μεταβολή Μάιος→Ιούνιος {wcorr(rate, pj - pm, w):+.2f}, Ιούνιος→Ευρωεκλογές {wcorr(rate, pu - pj, w):+.2f}")
    top = rate >= np.quantile(rate, 0.75)
    for label, m in (("25% με τους περισσότερους σταυρούς του", top), ("υπόλοιπα", ~top)):
        print(f"    {label:<40} {np.average(rate[m], weights=w[m]):.2f} ανά ψήφο· ΝΙΚΗ "
              f"{np.average(pm[m], weights=w[m]):.2f}% → {np.average(pj[m], weights=w[m]):.2f}% → {np.average(pu[m], weights=w[m]):.2f}%")
