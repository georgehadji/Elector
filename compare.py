"""Nationwide comparison map: every main party's share per local community in all four
elections (2019, May 2023, June 2023, Euro 2024) and the change between any two of them.

Reuses the community matching build.py already did: reads the data embedded in the
per-constituency pages out/{election}_{ep}.html and merges them into one page.
Run build.py for all four elections first, then:
  python -I -X utf8 compare.py      # -> out/compare.html
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ELECTIONS = {"2019": "2019", "2023-may": "Μάιος 2023", "2023-june": "Ιούνιος 2023", "2024-euro": "Ευρωεκλογές 2024"}
MIN_SHARE = 1.0  # % of valid votes on the map, in at least one election, for a party to be listed
SHORT = {"2": "ΝΔ", "4": "ΣΥΡΙΖΑ", "106": "ΠΑΣΟΚ-ΚΙΝΑΛ", "3": "ΚΚΕ", "108": "Ελληνική Λύση", "122": "ΜέΡΑ25",
         "123": "Πλεύση Ελευθερίας", "131": "ΝΙΚΗ", "157": "Σπαρτιάτες", "41": "Χρυσή Αυγή", "158": "Φωνή Λογικής",
         "15": "Ένωση Κεντρώων", "28": "Οικολόγοι Πράσινοι", "100": "Λαϊκή Ενότητα", "113": "Ελλήνων Συνέλευσις"}

geoms, props = {}, {}  # geometry hash -> geometry / {n, u, ep, e: {election: [valid, {pid: votes}]}}
parties = {}  # pid -> {name, color}; later elections overwrite, so names are the latest
for e in ELECTIONS:
    pages = sorted(p for p in (ROOT / "out").glob(f"{e}_*.html") if re.fullmatch(rf"{e}_\d+\.html", p.name))
    assert len(pages) == 59, (e, len(pages))
    for page in pages:
        D = json.loads(re.search(r"const D = (.*?);\n", page.read_text(encoding="utf-8"), re.DOTALL).group(1))
        parties.update(D["parties"])
        for f in D["geo"]["features"]:
            p = f["properties"]
            g = json.dumps(f["geometry"], separators=(",", ":"))
            k = hashlib.sha1(g.encode()).hexdigest()[:12]  # same community polygon across elections
            geoms.setdefault(k, f["geometry"])
            a = props.setdefault(k, {"n": p["name"], "u": p["unit"], "ep": D["ep_name"], "e": {}})
            a["e"][e] = [p["valid"], p["pv"]]

# Parties above MIN_SHARE in some election, ordered by their best share.
valid = {e: sum(a["e"][e][0] for a in props.values() if e in a["e"]) for e in ELECTIONS}
best = {}
for pid in parties:
    for e in ELECTIONS:
        v = sum(a["e"][e][1].get(pid, 0) for a in props.values() if e in a["e"])
        best[pid] = max(best.get(pid, 0), 100 * v / valid[e])
order = sorted((pid for pid in parties if best[pid] >= MIN_SHARE), key=lambda pid: -best[pid])
assert "2" in order and "131" in order, order

# Compact rows: per area and election [valid, votes of order[0], votes of order[1], ...]; null = party absent.
ran = {e: {pid for a in props.values() if e in a["e"] for pid in a["e"][e][1]} for e in ELECTIONS}
features = []
for k, a in props.items():
    rows = {e: [v] + [pv.get(pid, 0) if pid in ran[e] else None for pid in order] for e, (v, pv) in a["e"].items()}
    features.append({"type": "Feature", "geometry": geoms[k], "properties": {"n": a["n"], "u": a["u"], "ep": a["ep"], "e": rows}})

totals = {e: [valid[e]] + [sum(f["properties"]["e"][e][i + 1] or 0 for f in features if e in f["properties"]["e"])
                           if pid in ran[e] else None for i, pid in enumerate(order)] for e in ELECTIONS}
for i, pid in enumerate(order):
    print(f"{SHORT.get(pid, parties[pid]['name'])}: " + ", ".join(
        f"{e} {100 * totals[e][i + 1] / valid[e]:.2f}%" if totals[e][i + 1] is not None else f"{e} —" for e in ELECTIONS))

data = {"elections": ELECTIONS, "totals": totals,
        "parties": [{"id": pid, "name": SHORT.get(pid, parties[pid]["name"]), "color": parties[pid]["color"]} for pid in order],
        "geo": {"type": "FeatureCollection", "features": features}}
template = (ROOT / "compare_template.html").read_text(encoding="utf-8")
out = ROOT / "out" / "compare.html"
out.write_text(template.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))),
               encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(features)} areas, {len(order)} parties)")
