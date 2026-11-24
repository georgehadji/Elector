"""Nationwide map of NIKH (party 131, or --party=ID) share per local community, May 2023 / June 2023 / Euro 2024.

Also the "space" around NIKH (BLOCS): 2019 Ελλ. Λύση + Χρυσή Αυγή + Ένωση Κεντρώων vs
June 2023 ΝΙΚΗ + Ελλ. Λύση + Σπαρτιάτες / Euro 2024 ΝΙΚΗ + Ελλ. Λύση + Φωνή Λογικής, for the 2019 change views (NIKH did not run in 2019).

The BLOCS views and the links to the NIKH pages are NIKH-only: for another party they are left out.

Reads the community matches build.py stored in the area_match table.
Run build.py <election> all for all four elections first, then:
  python -I -X utf8 analysis/nikh_map.py [--party=ID] [--out=PATH]      # -> out/nikh_2023-2024.html
  (another party: --out=PATH outside out/, which is published; --rival is not used)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
import party  # noqa: E402
from build import communities  # noqa: E402
from config import ELECTION_NAMES, HERE, slug  # noqa: E402
from web import INDEX_DARK, INDEX_LIGHT, fill, secure  # noqa: E402

# NIKH first ran in 2023; 2019 appears only through BLOCS.
ELECTIONS = {slug(k): name for k, name in ELECTION_NAMES.items() if k != "2019"}
# key -> (election pages, party ids summed, label)
BLOCS = {"b2019": ("2019", [108, 41, 15], "Χώρος 2019 (Ελλ. Λύση, ΧΑ, Ένωση Κεντρ.)"),
         # Σπαρτιάτες did not run in May 2023
         "b2023-may": ("2023-may", [131, 108], "Χώρος Μαΐου 2023 (ΝΙΚΗ, Ελλ. Λύση)"),
         "b2023-june": ("2023-june", [131, 108, 157], "Χώρος Ιούν. 2023 (ΝΙΚΗ, Ελλ. Λύση, Σπαρτιάτες)"),
         # Σπαρτιάτες did not run in the Euro election; Φωνή Λογικής took that slot
         "b2024-euro": ("2024-euro", [131, 108, 158], "Χώρος Ευρωεκλ. 2024 (ΝΙΚΗ, Ελλ. Λύση, Φωνή Λογικής)")}

if not party.IS_NIKH:
    BLOCS = {}  # hand-picked NIKH space
out = party.page_path("nikh_2023-2024.html")  # fails early for another party without --out

totals = {e: {"valid": 0, "votes": 0, "areas": 0} for e in [*ELECTIONS, *BLOCS]}
reads = {e: [(e, [party.ID])] for e in ELECTIONS}  # election -> [(property key, party ids summed)]
for k, (e, ids, _) in BLOCS.items():
    reads.setdefault(e, []).append((k, ids))
features = []
for code, c in communities(ELECTION_NAMES).items():
    props = {"n": c["n"], "u": c["u"], "ep": c["ep"]}
    for e, keys in reads.items():
        if e not in c["e"]:
            continue
        valid, pv = c["e"][e]
        for key, ids in keys:
            v = sum(pv.get(i, 0) for i in ids)
            props[key] = [v, valid]
            totals[key]["valid"] += valid
            totals[key]["votes"] += v
            totals[key]["areas"] += 1
    features.append({"type": "Feature", "geometry": c["geometry"], "properties": props})

for e, t in totals.items():
    print(f"{e}: {t['areas']} areas, votes {t['votes']:,} / {t['valid']:,} valid = {100 * t['votes'] / t['valid']:.2f}%")

data = {"elections": ELECTIONS, "blocs": {k: v[2] for k, v in BLOCS.items()}, "totals": totals, "geo": {"type": "FeatureCollection", "features": features}}
template = fill((HERE / "analysis" / "nikh_map_template.html").read_text(encoding="utf-8"),
                INDEX_LIGHT | {"panel": "#ffffffee", "on": "#1d1d1b", "on-ink": "#fff"},
                INDEX_DARK | {"panel": "#1d2430ee", "on": "#e8edf5", "on-ink": "#171c24"},
                skip="#map", compact=True)
if not party.IS_NIKH:
    template = re.sub(r'DELTAS\["d-bloc[^\]]*\] = \[.*?\];[^\n]*\n', "", template, flags=re.S)  # bloc change views
    template = re.sub(r'<p class="rel">.*?</p>\n', "", template).replace("ΝΙΚΗ ανά", f"{party.NAME} ανά").replace("<h1>ΝΙΚΗ:", f"<h1>{party.NAME}:")
out.write_text(secure(template.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))),
               encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(features)} areas)")
