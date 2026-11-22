"""Does the 2021 census population add anything to what explains NIKH's (party 131) vote per ELSTAT community?

Source: ELSTAT, Απογραφή Πληθυσμού-Κατοικιών 2021, "Αποτελέσματα Μόνιμου Πληθυσμού κατά δημοτική κοινότητα, 21.04.2023"
(MON_PLI_DHM_KOIN_2021.xlsx, https://www.statistics.gr/2021-census-res-pop-results, downloaded 2026-11-22). Columns: community code
(8 digits, the same codes as data/koinotites_2021.json), running number, name, permanent population. Written to
data/pop_koinotites_2021.csv.
- rho = registered voters (June 2023) / permanent population (2021). Registered includes emigrants and absent owners, so a
  high rho marks places with many non-resident voters (depopulated villages). rho is clipped to [0.3, 10].
- WLS (weights = June 2023 valid votes) of NIKH's June share on 2019 shares, Macedonia/Thrace, turnout, log10 registered,
  with and without log10 population and log10 rho. Then quartile bands of rho.

- Second part: ELSTAT 2021 census tables per community (Δημοτικές Κοινότητες), https://www.statistics.gr/el/statistics/pop
  -> "Δημογραφικά χαρακτηριστικά" Γ03 (age groups by marital status), "Οικονομικά χαρακτηριστικά" Γ03 (education level
  by activity) and Γ04 (employed by sector, unemployed), downloaded 2026-11-22, written to data/census_koinotites_2021.csv.
  ELSTAT perturbs small counts for confidentiality, so totals differ from the population file by a few persons.
  The same WLS with 7 census variables, standard errors also clustered by municipality, and NIKH's share by quarter of
  the valid votes along each variable.
- Third part: Γ06 (citizenship: Greece / other), Γ05 (place of birth, the community rows of the settlement table) from
  "Δημογραφικά χαρακτηριστικά" and Γ15 (family nuclei by size) from "Κατοικίες, νοικοκυριά, οικογενειακοί πυρήνες"
  (publication SAM05), downloaded 2026-11-22, added to the same csv. ELSTAT gives household size only per municipality,
  so family nuclei stand in for it. Five more variables on top of the model with the first seven.
- Fourth part: from the same SAM05 publication Γ13 (households by number of cars), Γ11 (occupied dwellings by tenure)
  and Γ01 (dwellings: occupied, empty, holiday and secondary homes), the community rows, downloaded 2026-11-22.
  Four more variables on top of the model with the first twelve.

Run build.py <election> all first (area_match), then (the xlsx paths are only needed to (re)build the two csv):
  python -I -X utf8 analysis/nikh_census.py data/stavroi.sqlite [MON_PLI_DHM_KOIN_2021.xlsx [age.xlsx education.xlsx sectors.xlsx
      citizenship.xlsx birthplace.xlsx nuclei.xlsx
      cars.xlsx tenure.xlsx dwellings.xlsx]]
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

# --- age, education, marital status, employment per community (ELSTAT 2021 census tables, see the docstring) ---
CENSUS = CSV.with_name("census_koinotites_2021.csv")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EDU = dict(zip("EFGHIJK", ["edu_tertiary", "edu_postsecondary", "edu_lykeio", "edu_lower_secondary", "edu_primary", "edu_none",
                           "edu_unclassified"], strict=True))
WORK = dict(zip("EFGHIJK", ["active", "employed", "sector_primary", "sector_secondary", "sector_tertiary", "unemployed",
                            "inactive"], strict=True))
MORE = ({"F": "citizen_foreign"}, {"F": "born_same_muni", "I": "born_other_unit", "J": "born_abroad"},
        {"D": "nuclei", "G": "nuclei_4plus"},  # Γ06, Γ05, Γ15
        {"D": "households", "E": "hh_no_car", "H": "hh_2_cars", "I": "hh_3plus_cars"},  # Γ13
        {"D": "dwellings_occupied", "F": "dwellings_rented"},  # Γ11
        {"E": "dwellings", "J": "dwellings_holiday", "K": "dwellings_secondary"})  # Γ01


def cells(path):
    """Rows of sheet1 as {column letter: text} (stdlib only)."""
    z = zipfile.ZipFile(path)
    ss = ["".join(t.text or "" for t in si.iter(NS + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si")]
    for r in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(NS + "row"):
        out = {}
        for cl in r.findall(NS + "c"):
            x = cl.find(NS + "v")
            out["".join(ch for ch in cl.get("r") if ch.isalpha())] = "" if x is None else ss[int(x.text)] if cl.get("t") == "s" else x.text
        yield out


def build_census(age, edu, sector, *more):
    """{community code: {column: count}} from the sheets. Level 7 = community; its code is the last 8 digits."""
    out = {}
    for v in cells(age):  # one total row per community (name in C), then one row per age group (label in C)
        if v.get("A") == "7":
            row = out.setdefault(v["B"][3:], {})
            if v["C"][0].isdigit():
                row["age_" + v["C"].strip()] = int(float(v["D"]))
            else:
                row["pop"], row["married"] = int(float(v["D"])), int(float(v["F"]))
    for path, cols in ((edu, EDU), (sector, WORK), *zip(more, MORE, strict=False)):
        for v in cells(path):
            if v.get("A") == "7":
                out[v["B"][3:]].update({name: int(float(v.get(c_) or 0)) for c_, name in cols.items()})
    return out


if len(sys.argv) > 5:
    cen = build_census(*sys.argv[3:12])
    assert len(cen) > 6000 and 10_400_000 < sum(r["pop"] for r in cen.values()) < 10_500_000, len(cen)
    with open(CENSUS, "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["code", *next(iter(cen.values()))])
        wr.writeheader()
        wr.writerows({"code": k, **r} for k, r in sorted(cen.items()))
with open(CENSUS, encoding="utf-8") as f:
    cen = {r["code"]: {k: int(v) for k, v in r.items() if k != "code"} for r in csv.DictReader(f)}


def cluster_se(yv, cols, wt, groups):
    """SE of the WLS coefficients, robust to correlation inside groups (sandwich estimator)."""
    X = np.column_stack([np.ones(len(yv)), *cols])
    bread = np.linalg.inv((X * wt[:, None]).T @ X)
    res = yv - X @ (bread @ (X * wt[:, None]).T @ yv)
    score = {}
    for g, row in zip(groups, X * (wt * res)[:, None], strict=True):
        score[g] = score.get(g, 0) + row
    return np.sqrt(np.diag(bread @ sum(np.outer(s, s) for s in score.values()) @ bread))


# self-check: every row its own group, residuals all of size 1 -> the plain SE x sqrt((n - k) / n)
_x, _y = np.array([0., 1, 2, 3]), np.array([1., -1, -1, 1])
assert np.allclose(cluster_se(_y, [_x], np.ones(4), range(4))[1], wls(_y, [_x], np.ones(4))[1][1] * np.sqrt(2 / 4))

keep = np.array([k in cen and cen[k]["employed"] > 0 for k in codes])
print(f"\nΑπογραφή 2021, πίνακες Γ03 (ηλικία, οικογενειακή κατάσταση), Γ03 (εκπαίδευση), Γ04 (απασχόληση): {keep.sum()} κοινότητες"
      f" (έξω {(~keep).sum()}: χωρίς στοιχεία ή χωρίς απασχολούμενους)")
C = [cen[k] for k, f in zip(codes, keep, strict=True) if f]
age_lo = {a: int("".join(ch for ch in a[4:6] if ch.isdigit())) for a in C[0] if a.startswith("age_")}
print("  ομάδες ηλικιών: " + ", ".join(a[4:] for a in age_lo))


def col(f):
    return np.array([f(r) for r in C], float)


people = col(lambda r: max(r["pop"], 1))
classified = col(lambda r: max(r["pop"] - r["edu_unclassified"], 1))
adults = col(lambda r: max(r["pop"] - sum(r[a] for a, lo in age_lo.items() if lo < 15), 1))
V = {"60+ (% πληθυσμού)": 100 * col(lambda r: sum(r[a] for a, lo in age_lo.items() if lo >= 60)) / people,
     "15-29 (% πληθυσμού)": 100 * col(lambda r: sum(r[a] for a, lo in age_lo.items() if 15 <= lo < 30)) / people,
     "έγγαμοι (% των 15+)": 100 * col(lambda r: r["married"]) / adults,
     "ανώτατη εκπαίδευση (%)": 100 * col(lambda r: r["edu_tertiary"]) / classified,
     "έως δημοτικό (%)": 100 * col(lambda r: r["edu_primary"] + r["edu_none"]) / classified,
     "πρωτογενής τομέας (% απασχ.)": 100 * col(lambda r: r["sector_primary"]) / col(lambda r: r["employed"]),
     "ανεργία (% ενεργών)": 100 * col(lambda r: r["unemployed"]) / col(lambda r: max(r["active"], 1))}
V = {name: np.minimum(x, 100) for name, x in V.items()}  # ELSTAT's perturbation gives > 100% in a few tiny communities
yk, wk = y[keep], w[keep]
basek = [b[keep] for b in base]
muni = [k[:4] for k, f in zip(codes, keep, strict=True) if f]  # first 4 digits = municipality (δήμος)
njk, nek, vek = nj[keep], ne[keep], ve[keep]


def report(V, basecols, base_label, alone_label):
    """R², coefficients (plain and clustered SE) and NIKH's share by quarter of the valid votes, for the variables V."""
    print("Παλινδρόμηση (WLS, βάρος τα έγκυρα Ιουνίου): ποσοστό ΝΙΚΗΣ Ιουνίου 2023 ανά κοινότητα")
    for label, cols in ((alone_label, list(V.values())), (base_label, basecols), ("το ίδιο + αυτές", basecols + list(V.values()))):
        print(f"  {label}: R² = {wls(yk, cols, wk)[2]:.3f}")
    for label, cols in ((alone_label, list(V.values())), (f"με {base_label}", basecols + list(V.values()))):
        beta, se, _ = wls(yk, cols, wk)
        rse = cluster_se(yk, cols, wk, muni)
        print(f"  Συντελεστές, {label} (μονάδες ποσοστού ΝΙΚΗΣ ανά +1 μονάδα· σφάλμα απλό → ανά δήμο· επίδραση +1 τυπικής απόκλισης):")
        for (name, x), b, sx, rs in zip(V.items(), beta[-len(V):], se[-len(V):], rse[-len(V):], strict=True):
            sd = np.sqrt(np.average((x - np.average(x, weights=wk)) ** 2, weights=wk))
            print(f"    {name:<34}{b:+8.3f}  ±{sx:.3f} → ±{rs:.3f}   +1 τ.α. ({sd:4.1f}) = {b * sd:+.2f}{'  *' if abs(b) > 2 * rs else ''}")
    print("  (* = ο συντελεστής ξεπερνά τα 2 σφάλματα ανά δήμο)")
    print("\nΠοσοστό ΝΙΚΗΣ ανά τέταρτο των έγκυρων ψήφων (κοινότητες ταξινομημένες κατά τη μεταβλητή· Ιούνιος 2023 / Ευρωεκλογές 2024)")
    for name, x in V.items():
        order = np.argsort(x)
        parts = np.split(order, np.searchsorted(np.cumsum(wk[order]), np.array([.25, .5, .75]) * wk.sum()))
        print(f"  {name:<34}" + "   ".join(f"{x[q_].min():4.0f}-{x[q_].max():<3.0f}: {100 * njk[q_].sum() / wk[q_].sum():.2f}/{100 * nek[q_].sum() / vek[q_].sum():.2f}"
                                             for q_ in parts))


report(V, basek, "μοντέλο nikh_drivers.py", "μόνο απογραφή (7 μεταβλητές)")

if "born_abroad" in C[0]:
    print("\nΑπογραφή 2021, πίνακες Γ06 (ιθαγένεια), Γ05 (τόπος γέννησης), Γ15 (οικογενειακοί πυρήνες)")
    V2 = {"ξένη ιθαγένεια (% πληθ.)": 100 * col(lambda r: r["citizen_foreign"]) / people,
          # born abroad minus foreign citizens: mostly repatriated Greeks (former USSR, Germany); floor 0, the two tables are perturbed separately
          "γενν. εξωτερικό, Έλληνες (%)": 100 * col(lambda r: max(r["born_abroad"] - r["citizen_foreign"], 0)) / people,
          "γενν. στον ίδιο δήμο (%)": 100 * col(lambda r: r["born_same_muni"]) / people,
          "γενν. σε άλλη Π.Ε. (%)": 100 * col(lambda r: r["born_other_unit"]) / people,
          "πυρήνες 4+ μελών (% πυρήνων)": 100 * col(lambda r: r["nuclei_4plus"]) / col(lambda r: max(r["nuclei"], 1))}
    V2 = {name: np.minimum(x, 100) for name, x in V2.items()}
    report(V2, basek + list(V.values()), "μοντέλο nikh_drivers.py + 7 μεταβλητές απογραφής", "μόνο αυτές οι 5")

if "hh_no_car" in C[0]:
    print("\nΑπογραφή 2021, πίνακες Γ13 (αυτοκίνητα), Γ11 (κυριότητα κατοικίας), Γ01 (κατοικίες)")
    hh = col(lambda r: max(r["households"], 1))
    V3 = {"νοικοκυριά χωρίς αυτοκίνητο (%)": 100 * col(lambda r: r["hh_no_car"]) / hh,
          "νοικοκυριά με 2+ αυτοκίνητα (%)": 100 * col(lambda r: r["hh_2_cars"] + r["hh_3plus_cars"]) / hh,
          "ενοικιαζόμενες (% κατοικούμενων)": 100 * col(lambda r: r["dwellings_rented"]) / col(lambda r: max(r["dwellings_occupied"], 1)),
          "εξοχικές και δευτερεύουσες (% κατοικιών)": 100 * col(lambda r: r["dwellings_holiday"] + r["dwellings_secondary"])
          / col(lambda r: max(r["dwellings"], 1))}
    report({name: np.minimum(x, 100) for name, x in V3.items()}, basek + list(V.values()) + list(V2.values()),
           "μοντέλο nikh_drivers.py + 12 μεταβλητές απογραφής", "μόνο αυτές οι 4")
