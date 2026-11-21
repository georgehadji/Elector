"""NIKH (party 131) against its neighbours, June 2023 -> Euro 2024, and inside the big cities.

- Heirs of Σπαρτιάτες (157; did not run in 2024): for each party, WLS per ELSTAT community of its Euro 2024 share on
  its own June 2023 share and the Σπαρτιάτες June share. The second coefficient is points gained per point of
  Σπαρτιάτες: an ecological estimate of who took their voters, not a measured flow.
- Trade-offs: weighted correlation of NIKH's change with the change of Ελλ. Λύση and Φωνή Λογικής.
- Big cities: NIKH June 2023 share per electoral district (εκλογικό διαμέρισμα) in the largest municipal units.

  python -I -X utf8 analysis/nikh_competition.py data/stavroi.sqlite
"""
import math
import sqlite3
import sys

import numpy as np

NIKH, SPART = 131, 157
PARTIES = {131: "ΝΙΚΗ", 108: "Ελλ. Λύση", 158: "Φωνή Λογικής", 163: "Πατριώτες", 2: "ΝΔ", 123: "Πλεύση", 3: "ΚΚΕ"}
c = sqlite3.connect(sys.argv[1])


def load(e):
    """{community: [valid, {party: votes}]}"""
    out = {}
    for code, val in c.execute("SELECT a.comm_code, SUM(s.valid) FROM station s JOIN area_match a "
                               "ON a.election=s.election AND a.tm_id=s.tm_id WHERE s.election=? GROUP BY 1", (e,)):
        out[code] = [val, {}]
    for code, pid, v in c.execute("SELECT a.comm_code, pv.party_id, SUM(pv.votes) FROM party_votes pv JOIN area_match a "
                                  "ON a.election=pv.election AND a.tm_id=pv.tm_id WHERE pv.election=? GROUP BY 1, 2", (e,)):
        out[code][1][pid] = v
    return out


J, E = load("2023/june"), load("2024/euro")
codes = [k for k in J if k in E and J[k][0] >= 50 and E[k][0] >= 50]
w = np.array([J[k][0] for k in codes], float)


def sh(d, p):
    return np.array([100 * d[k][1].get(p, 0) / d[k][0] for k in codes])


def wcorr(a, b):
    ma, mb = np.average(a, weights=w), np.average(b, weights=w)
    return np.average((a - ma) * (b - mb), weights=w) / math.sqrt(np.average((a - ma) ** 2, weights=w) *
                                                                   np.average((b - mb) ** 2, weights=w))


spart = sh(J, SPART)
print(f"{len(codes)} κοινότητες. Σπαρτιάτες Ιούνιος 2023: {sum(J[k][1].get(SPART, 0) for k in codes):,} ψήφοι")
print("\nΚληρονόμοι Σπαρτιατών: μονάδες στις Ευρωεκλογές ανά μονάδα Σπαρτιατών Ιουνίου (με σταθερό το δικό τους ποσοστό Ιουνίου)")
sw = np.sqrt(w)
for p, name in PARTIES.items():
    X = np.column_stack([np.ones(len(codes)), sh(J, p), spart])
    beta, *_ = np.linalg.lstsq(X * sw[:, None], sh(E, p) * sw, rcond=None)
    print(f"  {name:<14} {beta[2]:+.2f}   (διατήρηση δικού ποσοστού {beta[1]:.2f})")

d = {p: sh(E, p) - sh(J, p) for p in PARTIES}
print("\nΣυσχέτιση της μεταβολής της ΝΙΚΗΣ (Ιούν. → Ευρ.) με τη μεταβολή άλλων:")
for p, name in PARTIES.items():
    if p != NIKH:
        print(f"  {name:<14} {wcorr(d[NIKH], d[p]):+.2f}")
print(f"  ποσοστό Σπαρτιατών Ιουνίου  {wcorr(d[NIKH], spart):+.2f}")

print("\nΜέσα στις μεγάλες πόλεις: ΝΙΚΗ Ιουνίου 2023 ανά εκλογικό διαμέρισμα (≥1.500 έγκυρα), 4 υψηλότερα και 4 χαμηλότερα")
ep_name = dict(c.execute("SELECT ep_id, name FROM ep WHERE election='2023/june'"))
valid = {(ep, den, ekd): v for ep, den, ekd, v in c.execute(
    "SELECT ep_id, den_descr, ekd_descr, SUM(valid) FROM station WHERE election='2023/june' AND kind='Κ' GROUP BY 1, 2, 3")}
units = {}  # {(ep, unit): [(district, valid, NIKH votes, Ελλ. Λύση + Σπαρτιάτες votes)]}
for ep, den, ekd, n, pool in c.execute(
        "SELECT s.ep_id, s.den_descr, s.ekd_descr, SUM(CASE WHEN pv.party_id=131 THEN pv.votes ELSE 0 END), "
        "SUM(CASE WHEN pv.party_id IN (108, 157) THEN pv.votes ELSE 0 END) FROM station s JOIN party_votes pv "
        "ON pv.election=s.election AND pv.tm_id=s.tm_id WHERE s.election='2023/june' AND s.kind='Κ' GROUP BY 1, 2, 3"):
    units.setdefault((ep, den), []).append((ekd, valid[ep, den, ekd], n, pool))
for ep, den in sorted(units, key=lambda k: -sum(x[1] for x in units[k]))[:8]:
    eks = sorted((x for x in units[ep, den] if x[1] >= 1500), key=lambda x: -x[2] / x[1])
    tv, tn = sum(x[1] for x in units[ep, den]), sum(x[2] for x in units[ep, den])
    print(f"  {den} ({ep_name[ep]}): {100 * tn / tv:.1f}% συνολικά, {len(eks)} διαμερίσματα")
    for ekd, v, n, pool in (eks[:4] + eks[-4:] if len(eks) >= 8 else eks):
        print(f"      {ekd[:40]:<41}{100 * n / v:4.1f}%  ({n:,} ψήφοι, Ελλ. Λύση+Σπαρτ. {100 * pool / v:.0f}%)")
