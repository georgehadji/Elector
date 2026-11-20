"""Nationwide comparison map: every main party's share per local community in all four
elections (2019, May 2023, June 2023, Euro 2024) and the change between any two of them.

Reads the community matches build.py stored in the area_match table.
Run build.py <election> all for every election first, then:
  python -I -X utf8 compare.py      # -> out/compare.html
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
from build import communities, parties  # noqa: E402
from config import ELECTION_NAMES, HERE, OUT, PARTY_SHORT, slug  # noqa: E402
from web import INDEX_DARK, INDEX_LIGHT, fill, greece_figure, meta, secure  # noqa: E402

ELECTIONS = {slug(k): name for k, name in ELECTION_NAMES.items()}  # file-name form of the keys
MIN_SHARE = 1.0  # % of valid votes on the map, in at least one election, for a party to be listed

props = communities(ELECTION_NAMES)
parties = parties(ELECTION_NAMES)

# Parties above MIN_SHARE in some election, ordered by their best share.
valid = {e: sum(a["e"][e][0] for a in props.values() if e in a["e"]) for e in ELECTIONS}
best = {}
for pid in parties:
    for e in ELECTIONS:
        v = sum(a["e"][e][1].get(pid, 0) for a in props.values() if e in a["e"])
        best[pid] = max(best.get(pid, 0), 100 * v / valid[e])
order = sorted((pid for pid in parties if best[pid] >= MIN_SHARE), key=lambda pid: -best[pid])
assert 2 in order and 131 in order, order

# Compact rows: per area and election [valid, votes of order[0], votes of order[1], ...]; null = party absent.
ran = {e: {pid for a in props.values() if e in a["e"] for pid in a["e"][e][1]} for e in ELECTIONS}
features = []
for k, a in props.items():
    rows = {e: [v] + [pv.get(pid, 0) if pid in ran[e] else None for pid in order] for e, (v, pv) in a["e"].items()}
    features.append({"type": "Feature", "geometry": a["geometry"], "properties": {"n": a["n"], "u": a["u"], "ep": a["ep"], "e": rows}})

totals = {e: [valid[e]] + [sum(f["properties"]["e"][e][i + 1] or 0 for f in features if e in f["properties"]["e"])
                           if pid in ran[e] else None for i, pid in enumerate(order)] for e in ELECTIONS}
for i, pid in enumerate(order):
    print(f"{PARTY_SHORT.get(pid, parties[pid]['name'])}: " + ", ".join(
        f"{e} {100 * totals[e][i + 1] / valid[e]:.2f}%" if totals[e][i + 1] is not None else f"{e} —" for e in ELECTIONS))

data = {"elections": ELECTIONS, "totals": totals,
        "parties": [{"id": str(pid), "name": PARTY_SHORT.get(pid, parties[pid]["name"]), "color": parties[pid]["color"]} for pid in order],
        "geo": {"type": "FeatureCollection", "features": features}}
template = fill((HERE / "compare_template.html").read_text(encoding="utf-8"),
                INDEX_LIGHT | {"panel": "#ffffffee", "field": "#fff", "shadow": "rgba(0,0,0,.2)"},
                INDEX_DARK | {"panel": "#1d2430ee", "field": "#1d2430", "shadow": "rgba(0,0,0,.5)"},
                current="compare", skip="#map", compact=True)
template = template.replace("<!--META-->", meta("Σύγκριση εκλογών ανά κοινότητα",
    "Χάρτης όλης της χώρας: ποσοστό κάθε κόμματος ανά κοινότητα και μεταβολή ανάμεσα σε οποιεσδήποτε δύο εκλογές, 2019–2024."))
out = OUT / "compare.html"
out.write_text(secure(template.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))),
               encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(features)} areas, {len(order)} parties)")

# Static map for the index: the party that came first in each community, June 2023.
WON = "2023-june"
won = {}
for a in props.values():
    if WON in a["e"] and a["e"][WON][1]:
        votes = a["e"][WON][1]
        won[id(a)] = max(votes, key=votes.get)
tally = {}
for pid in won.values():
    tally[pid] = tally.get(pid, 0) + 1
shown = [pid for pid, n in sorted(tally.items(), key=lambda kv: -kv[1]) if n >= 0.02 * len(won)]
OTHER = "#9a9a94"
areas = [(a["geometry"], parties[won[id(a)]]["color"] if won[id(a)] in shown else OTHER) for a in props.values() if id(a) in won]
key = [(PARTY_SHORT.get(pid, parties[pid]["name"]), parties[pid]["color"]) for pid in shown] + [("Άλλο", OTHER)]
fig = OUT / "greece_map.html"
fig.write_text(greece_figure(areas, key, f"Πρώτο κόμμα ανά κοινότητα, {ELECTION_NAMES['2023/june']}"), encoding="utf-8")
print(f"wrote {fig} ({fig.stat().st_size / 1e3:.0f} KB)")
