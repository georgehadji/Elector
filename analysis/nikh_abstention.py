"""Abstention and NIKH (party 131), base -> target election (default June 2023 -> Euro 2024), per ELSTAT community and municipal unit.

Valid votes fell about a quarter between the two elections. How much of NIKH's loss is that fall?
- Per community (>= 50 valid votes in both, matched by area_match): WLS (weights = June registered) of the change in
  a party's votes per registered voter on the change in valid votes per registered voter (registered: June, for both).
  Slope b = party votes lost per valid vote lost. If abstention hit everyone alike, b would equal the party's June share.
  b / share > 1 means the party's votes fall faster than turnout does. Ecological: it describes places, not voters.
- Same per region (config.REGIONS), compared with the PyEI abstention flow in NIKH.md section 7.
- Per municipal unit (δημοτική ενότητα): estimated NIKH votes lost to abstention = national b x valid votes lost there,
  ranked, and split by the targeting tiers of nikh_pareto.py (A = first 20% of the electorate by peak votes per 100
  registered, B = next 30%, C = last 50%).
Registered includes emigrants and the dead: only relative figures mean anything. Unofficial results.
Any other party: --party=ID (and --rival=ID for the control column, default 108; see party.py). The comparison with the
PyEI constants of NIKH.md section 7 (per-region table) runs only on party.REFERENCE (NIKH, June 2023 -> Euro 2024).
Other elections: --base=KEY --target=KEY (config.ELECTIONS keys, older first; see party.py). May 2023 adds a third
election to the municipal-unit peak only on the default pair, or when it is not the base or target.

Run build.py <election> all first (area_match), then:
  python -I -X utf8 analysis/nikh_abstention.py data/stavroi.sqlite [--party=ID] [--rival=ID] [--base=KEY] [--target=KEY]
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import NIKH, REGIONS
sys.path.insert(0, str(Path(__file__).resolve().parent))
import party

J, E, M = party.BASE, party.TARGET, "2023/may"
D = party.DEFAULT_PAIR
# labels: the default pair keeps its genitive wording, other pairs name the chosen elections
BN, TN = party.BASE_NAME, party.TARGET_NAME
AB = party.ABBR[J]
PB, PE = ("Ιουνίου", "Ευρωεκλογών") if D else (f"({BN})", f"({TN})")
ELS = [J, E] + ([M] if D or M not in (J, E) else [])  # M: peak votes per unit; shortcut: May also joins 2019 -> June
PARTY, NAME = party.ID, party.NAME
PARTIES = {PARTY: NAME, NIKH: "ΝΙΚΗ", 2: "ΝΔ", 4: "ΣΥΡΙΖΑ", 106: "ΠΑΣΟΚ", 108: "Ελλ. Λύση", 157: "Σπαρτιάτες"}
PARTIES.setdefault(party.RIVAL, party.RIVAL_NAME)  # the studied party first, then the comparison parties
PYEI_ABST = {"Αττική": 3, "Θεσσαλία": 10, "Δυτική Ελλάδα": 7, "Κρήτη": 8, "Πελοπόννησος": 12, "Δυτική Μακεδονία": 13,
             "Ήπειρος": 8, "Κεντρική Μακεδονία": 25, "Στερεά Ελλάδα": 11, "Βόρειο Αιγαίο": 8, "Νότιο Αιγαίο": 13,
             "Ανατολική Μακεδονία και Θράκη": 5, "Ιόνια Νησιά": 23}  # % of June NIKH voters, NIKH.md section 7 (very wide intervals)


def wls(y, cols, w):
    """beta, se, r2 for y on [1, *cols], weights w. shortcut: plain WLS SE ignore spatial correlation."""
    X = np.column_stack([np.ones(len(y)), *cols])
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    res = y - X @ beta
    r2 = 1 - np.sum(w * res ** 2) / np.sum(w * (y - np.average(y, weights=w)) ** 2)
    se = np.sqrt(np.diag(np.sum(w * res ** 2) / (len(y) - X.shape[1]) * np.linalg.inv((X * w[:, None]).T @ X)))
    return beta, se, r2


# self-check: exact line recovered
_b, _, _r2 = wls(np.array([1., 3, 5, 7]), [np.array([0., 1, 2, 3])], np.ones(4))
assert np.allclose(_b, [1, 2]) and _r2 > 0.999

c = sqlite3.connect(sys.argv[1])
region = {ep: name for name, eps in REGIONS for ep in eps}


def load(e):
    """{community: [registered, valid, ep, {party: votes}]}"""
    out = {k: [r, v, ep, {}] for k, r, v, ep in c.execute(
        "SELECT a.comm_code, SUM(s.registered), SUM(s.valid), MIN(s.ep_id) FROM station s JOIN area_match a "
        "ON a.election=s.election AND a.tm_id=s.tm_id WHERE s.election=? GROUP BY 1", (e,))}
    for k, p, v in c.execute(
            "SELECT a.comm_code, pv.party_id, SUM(pv.votes) FROM party_votes pv JOIN area_match a ON a.election=pv.election "
            f"AND a.tm_id=pv.tm_id WHERE pv.election=? AND pv.party_id IN ({','.join(map(str, PARTIES))}) GROUP BY 1, 2", (e,)):
        out[k][3][p] = v
    return out


dj, de = load(J), load(E)
codes = [k for k in dj if k in de and dj[k][0] > 0 and dj[k][1] >= 50 and de[k][1] >= 50 and dj[k][2] in region]
R = np.array([dj[k][0] for k in codes], float)
VJ, VE = (np.array([d[k][1] for k in codes], float) for d in (dj, de))
EP = np.array([dj[k][2] for k in codes])
dv = (VE - VJ) / R


def pvotes(d, p):
    return np.array([d[k][3].get(p, 0) for k in codes], float)


print(f"{len(codes)} κοινότητες. Εγγεγραμμένοι {PB} {R.sum():,.0f}, έγκυρα {PB} {VJ.sum():,.0f} → {PE} {VE.sum():,.0f} "
      f"({100 * (VE.sum() / VJ.sum() - 1):+.0f}%), συμμετοχή {100 * VJ.sum() / R.sum():.0f}% → {100 * VE.sum() / R.sum():.0f}% (σχετική)")
nj, ne = pvotes(dj, PARTY), pvotes(de, PARTY)
if nj.sum() == 0:
    raise SystemExit(f"{NAME}: καμία ψήφος ({BN}) στις κοινότητες που αντιστοιχίστηκαν")
print(f"{NAME}: {nj.sum():,.0f} → {ne.sum():,.0f} ({100 * (ne.sum() / nj.sum() - 1):+.0f}%)")

print("\nΜεταβολή ψήφων κόμματος ανά εγγεγραμμένο στη μεταβολή έγκυρων ανά εγγεγραμμένο (WLS, κοινότητες)")
print(f"  {'':<12}{'% ' + AB:>8}{'σταθερά':>10}{'κλίση b':>16}{'b / ποσοστό':>13}{'R²':>6}")
B = {}
for p, name in PARTIES.items():
    pj, pe = pvotes(dj, p), pvotes(de, p)
    beta, se, r2 = wls((pe - pj) / R, [dv], R)
    sh = pj.sum() / VJ.sum()
    B[p] = beta[1]
    print(f"  {name:<12}{100 * sh:>7.2f}%{beta[0]:>+10.4f}{beta[1]:>+9.3f} ±{se[1]:.3f}{beta[1] / sh:>13.2f}{r2:>6.2f}")

nd = 100 * pvotes(dj, 2) / VJ
el = 100 * pvotes(dj, party.RIVAL) / VJ
north = np.array([float("Μακεδονία" in region[ep] or "Θράκη" in region[ep]) for ep in EP])
beta, se, r2 = wls((ne - nj) / R, [dv, nd, el, north], R)
print(f"\n{NAME} με ελέγχους (ποσοστά {PB} ΝΔ, {PARTIES[party.RIVAL]}, Μακεδονία/Θράκη): b = {beta[1]:+.3f} ±{se[1]:.3f}, R² = {r2:.2f}")

# check: each election's own registered voters instead of June's for both (the roll changed between them)
RE = np.array([de[k][0] for k in codes], float)
beta, se, r2 = wls(ne / RE - nj / R, [VE / RE - VJ / R], R)
print(f"Έλεγχος, εγγεγραμμένοι κάθε εκλογής χωριστά ({PE.strip('()')} {RE.sum():,.0f}, {100 * (RE.sum() / R.sum() - 1):+.1f}%): "
      f"b = {beta[1]:+.3f} ±{se[1]:.3f}, R² = {r2:.2f}")

b_nat = B[PARTY]
lost = VJ.sum() - VE.sum()
print(f"\nΕθνικά: b × πτώση έγκυρων = {b_nat:.3f} × {lost:,.0f} = {b_nat * lost:,.0f} ψήφοι {party.GEN}, "
      f"{100 * b_nat * lost / nj.sum():.0f}% των ψήφων {'της Ιουνίου' if D else PB}. Πραγματική καθαρή απώλεια: {nj.sum() - ne.sum():,.0f} ({100 * (1 - ne.sum() / nj.sum()):.0f}%).")

print(f"\nΑνά περιφέρεια: b {party.GEN} και εκτίμηση απώλειας λόγω αποχής"
      + (" σε σύγκριση με το PyEI (NIKH.md ενότητα 7)" if party.REFERENCE else ""))
print(f"  {'':<32}{'κοιν.':>6}{'b':>16}{'απώλεια':>9}{'% ' + AB:>8}{'καθαρή':>8}" + (f"{'PyEI':>6}" if party.REFERENCE else ""))
for name, eps in REGIONS:
    m = np.isin(EP, eps)
    if m.sum() < 5:
        continue
    beta, se, _ = wls(((ne - nj) / R)[m], [dv[m]], R[m])
    est = beta[1] * (VJ[m].sum() - VE[m].sum())
    print(f"  {name:<32}{m.sum():>6}{beta[1]:>+9.3f} ±{se[1]:.3f}{est:>9,.0f}{100 * est / nj[m].sum():>7.0f}%"
          f"{100 * (1 - ne[m].sum() / nj[m].sum()):>7.0f}%" + (f"{PYEI_ABST.get(name, 0):>5}%" if party.REFERENCE else ""))

# municipal units: stations directly (no area_match needed), tiers as in nikh_pareto.py
ep_name = dict(c.execute("SELECT ep_id, name FROM ep WHERE election=?", (J,)))
U = {}
for e in ELS:
    for ep, den, r, v, n in c.execute(
            "SELECT s.ep_id, s.den_descr, SUM(s.registered), SUM(s.valid), SUM((SELECT votes FROM party_votes p WHERE "
            "p.election=s.election AND p.tm_id=s.tm_id AND p.party_id=?)) FROM station s WHERE s.election=? "
            "AND s.den_descr IS NOT NULL GROUP BY 1, 2", (PARTY, e)):
        U.setdefault((ep, den), {})[e] = (r or 0, v or 0, n or 0)
units = [{"k": k, "reg": u[J][0], "vj": u[J][1], "ve": u[E][1] if E in u else 0, "peak": max(x[2] for x in u.values()),
          "nj": u[J][2]} for k, u in U.items() if J in u and u[J][0] > 0]
# a unit whose name is spelled differently in the Euro 2024 data has no Euro votes here: leave it out, not "100% fewer"
bad = [u for u in units if u["ve"] < 0.5 * u["vj"]]
units = [u for u in units if u not in bad]
print(f"\nΕνότητες χωρίς αντιστοίχιση {'στις Ευρωεκλογές' if D else f'στην εκλογή {PE}'} (άλλη γραφή ονόματος, έξω από την κατάταξη): "
      f"{', '.join(u['k'][1] for u in bad)}")
units.sort(key=lambda u: -u["peak"] / u["reg"])
REG = sum(u["reg"] for u in units)
acc = 0
for u in units:
    acc += u["reg"]
    u["tier"] = "A" if acc <= 0.2 * REG else "B" if acc <= 0.5 * REG else "C"
    u["est"] = max(0.0, b_nat * (u["vj"] - u["ve"]))
TOT = sum(u["est"] for u in units)
print(f"\nΕκτιμώμενες ψήφοι {party.GEN} που χάθηκαν λόγω αποχής ανά ζώνη στόχευσης (σύνολο {TOT:,.0f}):")
for t in "ABC":
    us = [u for u in units if u["tier"] == t]
    est = sum(u["est"] for u in us)
    print(f"  Ζώνη {t}: {len(us):>4} ενότητες, {est:>8,.0f} ({100 * est / (TOT or 1):.0f}%), {10000 * est / sum(u['reg'] for u in us):.0f} ανά 10.000 εγγ.")

print(f"\nΟι 25 ενότητες με τους περισσότερους εκτιμώμενους ψηφοφόρους {party.GEN} που έμειναν σπίτι:")
for u in sorted(units, key=lambda u: -u["est"])[:25]:
    print(f"  {u['k'][1][:26]:<27}{ep_name[u['k'][0]][:26]:<27}εκτ. {u['est']:>6,.0f}  ({100 * u['est'] / max(u['nj'], 1):3.0f}% των ψήφων {AB.replace("ούν", "ουν")})  "
          f"πτώση έγκυρων {100 * (1 - u['ve'] / u['vj']):3.0f}%  ζώνη {u['tier']}")
