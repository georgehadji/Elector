"""Does the 2021 census population add anything to what explains NIKH's (party 131) vote per ELSTAT community?

Source: ELSTAT, Απογραφή Πληθυσμού-Κατοικιών 2021, "Αποτελέσματα Μόνιμου Πληθυσμού κατά δημοτική κοινότητα, 21.04.2023"
(MON_PLI_DHM_KOIN_2021.xlsx, https://www.statistics.gr/2021-census-res-pop-results, downloaded 2026-11-22). Columns: community code
(8 digits, the same codes as data/koinotites_2021.json), running number, name, permanent population. Written to
data/pop_koinotites_2021.csv. ELSTAT publishes age, education and employment only for the country and the regions, so
population is the only census variable available per community.
- rho = registered voters (June 2023) / permanent population (2021). Registered includes emigrants and absent owners, so a
  high rho marks places with many non-resident voters (depopulated villages). rho is clipped to [0.3, 10].
- WLS (weights = June 2023 valid votes) of NIKH's June share on 2019 shares, Macedonia/Thrace, turnout, log10 registered,
  with and without log10 population and log10 rho. Then quartile bands of rho.

Run build.py <election> all first (area_match), then (the xlsx path is only needed to (re)build the csv):
  python -I -X utf8 analysis/nikh_census.py data/stavroi.sqlite [MON_PLI_DHM_KOIN_2021.xlsx]
"""
import csv
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import REGIONS

NIKH = 131
CSV = Path(__file__).resolve().parent.parent / "data" / "pop_koinotites_2021.csv"
X2019 = {2: "ΝΔ", 4: "ΣΥΡΙΖΑ", 106: "ΚΙΝΑΛ", 3: "ΚΚΕ", 108: "Ελλ. Λύση", 122: "ΜέΡΑ25", 41: "Χρυσή Αυγή", 15: "Ένωση Κεντρώων"}
NORTH = {ep for name, eps in REGIONS if "Μακεδονία" in name for ep in eps}


def read_xlsx(path):
    """[(code, name, population)] for the 8-digit community rows of the ELSTAT sheet (stdlib only)."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(path)
    ss = ["".join(t.text or "" for t in si.iter(ns + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(ns + "si")]
    out = []
    for r in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(ns + "row"):
        v = []
        for c in r.findall(ns + "c"):
            x = c.find(ns + "v")
            v.append("" if x is None else ss[int(x.text)] if c.get("t") == "s" else x.text)
        code = v[0].strip() if v else ""
        if len(v) >= 4 and len(code) == 8 and code.isdigit() and v[3].strip():  # one community has an empty population cell
            out.append((code, v[2].strip(), int(float(v[3]))))
    return out


if len(sys.argv) > 2:
    rows = read_xlsx(sys.argv[2])
    assert len(rows) > 6000 and sum(p for _, _, p in rows) > 10_000_000, len(rows)  # country total is 10.48 million
    with open(CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "population"])
        w.writerows(rows)
with open(CSV, encoding="utf-8") as f:
    pop = {r["code"]: int(r["population"]) for r in csv.DictReader(f)}


def wls(y, cols, w):
    """beta, se, r2 for y on [1, *cols], weights w. The SE is the plain WLS one and ignores spatial correlation."""
    X = np.column_stack([np.ones(len(y)), *cols])
    sw = np.sqrt(w)
    beta = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]
    res = y - X @ beta
    r2 = 1 - np.sum(w * res ** 2) / np.sum(w * (y - np.average(y, weights=w)) ** 2)
    se = np.sqrt(np.diag(np.sum(w * res ** 2) / (len(y) - X.shape[1]) * np.linalg.inv((X * w[:, None]).T @ X)))
    return beta, se, r2


assert np.allclose(wls(np.array([1., 3, 5, 7]), [np.array([0., 1, 2, 3])], np.ones(4))[0], [1, 2])  # exact line

c = sqlite3.connect(sys.argv[1])


def load(e):
    """{community: [registered, valid, ep, {party: votes}]}"""
    out = {k: [r, v, ep, {}] for k, r, v, ep in c.execute(
        "SELECT a.comm_code, SUM(s.registered), SUM(s.valid), MIN(s.ep_id) FROM station s JOIN area_match a "
        "ON a.election=s.election AND a.tm_id=s.tm_id WHERE s.election=? GROUP BY 1", (e,))}
    for k, p, v in c.execute(
            "SELECT a.comm_code, pv.party_id, SUM(pv.votes) FROM party_votes pv JOIN area_match a ON a.election=pv.election "
            f"AND a.tm_id=pv.tm_id WHERE pv.election=? AND pv.party_id IN ({','.join(map(str, [NIKH, *X2019]))}) GROUP BY 1, 2", (e,)):
        out[k][3][p] = v
    return out


D = {e: load(e) for e in ("2019", "2023/june", "2024/euro")}
codes = [k for k in D["2023/june"] if k in pop and pop[k] > 0 and all(k in D[e] and D[e][k][1] >= 50 for e in D)]
print(f"{len(codes)} κοινότητες με ≥50 έγκυρα σε Ιούνιο 2023, Ευρωεκλογές 2024 και 2019, και πληθυσμό απογραφής 2021")
J, E = D["2023/june"], D["2024/euro"]
w = np.array([J[k][1] for k in codes], float)
reg = np.array([J[k][0] for k in codes], float)
y = np.array([100 * J[k][3].get(NIKH, 0) / J[k][1] for k in codes])
P = np.array([pop[k] for k in codes], float)
rho = np.clip(reg / P, 0.3, 10)
print(f"εγγεγραμμένοι / μόνιμος πληθυσμός (rho): διάμεσος {np.median(reg / P):.2f}, 10%-90%: "
      f"{np.quantile(reg / P, .1):.2f}-{np.quantile(reg / P, .9):.2f}, όλη η χώρα {reg.sum() / P.sum():.2f}")

xs = [np.array([100 * D["2019"][k][3].get(p, 0) / D["2019"][k][1] for k in codes]) for p in X2019]
north = np.array([float(J[k][2] in NORTH) for k in codes])
turn = np.array([100 * J[k][1] / J[k][0] for k in codes])
base = [*xs, north, turn, np.log10(np.maximum(reg, 1))]
bnames = [*X2019.values(), "Μακεδονία/Θράκη", "συμμετοχή Ιουν.", "log10 εγγεγραμμένων"]
census = [np.log10(P), np.log10(rho)]
cnames = ["log10 πληθυσμού 2021", "log10 εγγεγρ./πληθυσμό"]
print("\nΠαλινδρόμηση (WLS): ποσοστό ΝΙΚΗΣ Ιουνίου 2023 ανά κοινότητα")
for label, cols in (("μόνο μέγεθος και rho", [np.log10(np.maximum(reg, 1)), *census]),
                    ("μοντέλο nikh_drivers.py (χωρίς απογραφή)", base), ("το ίδιο + απογραφή", base + census)):
    print(f"  {label}: R² = {wls(y, cols, w)[2]:.3f}")
beta, se, r2 = wls(y, base + census, w)
for n, b, s in list(zip([*bnames, *cnames], beta[1:], se[1:], strict=True))[-5:]:
    print(f"    {n:<26}{b:+8.3f}  (±{s:.3f})")

print("\nΖώνες rho (τεταρτημόρια κοινοτήτων· ποσοστά σταθμισμένα με έγκυρα Ιουνίου)")
q = np.quantile(rho, [.25, .5, .75])
nj = np.array([J[k][3].get(NIKH, 0) for k in codes], float)
ne = np.array([E[k][3].get(NIKH, 0) for k in codes], float)
ve = np.array([E[k][1] for k in codes], float)
print(f"  {'rho':<14}{'κοιν.':>6}{'ψήφοι ΝΙΚΗΣ':>12}{'ΝΙΚΗ Ιούν.':>11}{'Ευρ.':>7}{'κράτησε':>9}{'συμμετοχή':>10}{'πληθ. διάμ.':>12}")
for lo, hi in ((0, q[0]), (q[0], q[1]), (q[1], q[2]), (q[2], np.inf)):
    m = (rho >= lo) & (rho < hi)
    print(f"  {lo:>5.2f}-{min(hi, 10):<6.2f}{m.sum():>6}{nj[m].sum():>12,.0f}{100 * nj[m].sum() / w[m].sum():>10.2f}%"
          f"{100 * ne[m].sum() / ve[m].sum():>6.2f}%{100 * ne[m].sum() / nj[m].sum():>8.0f}%{np.average(turn[m], weights=w[m]):>9.0f}%"
          f"{np.median(P[m]):>12,.0f}")
