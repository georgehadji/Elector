"""Nationwide map of NIKH (party 131) share per local community, May 2023 / June 2023 / Euro 2024.

Also the "space" around NIKH (BLOCS): 2019 Ελλ. Λύση + Χρυσή Αυγή + Ένωση Κεντρώων vs
June 2023 ΝΙΚΗ + Ελλ. Λύση + Σπαρτιάτες / Euro 2024 ΝΙΚΗ + Ελλ. Λύση + Φωνή Λογικής, for the 2019 change views (NIKH did not run in 2019).

Reuses the community matching build.py already did: reads the data embedded in the
per-constituency pages out/{election}_{ep}.html and merges them into one page.
Run build.py for the three elections first, then:
  python -I -X utf8 analysis/nikh_map.py      # -> out/nikh_2023-2024.html
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NIKH = "131"
ELECTIONS = {"2023-may": "Μάιος 2023", "2023-june": "Ιούνιος 2023", "2024-euro": "Ευρωεκλογές 2024"}
# key -> (election pages, party ids summed, label)
BLOCS = {"b2019": ("2019", ["108", "41", "15"], "Χώρος 2019 (Ελλ. Λύση, ΧΑ, Ένωση Κεντρ.)"),
         "b2023-june": ("2023-june", ["131", "108", "157"], "Χώρος Ιούν. 2023 (ΝΙΚΗ, Ελλ. Λύση, Σπαρτιάτες)"),
         # Σπαρτιάτες did not run in the Euro election; Φωνή Λογικής took that slot
         "b2024-euro": ("2024-euro", ["131", "108", "158"], "Χώρος Ευρωεκλ. 2024 (ΝΙΚΗ, Ελλ. Λύση, Φωνή Λογικής)")}

geoms, props = {}, {}  # geometry hash -> geometry / {name, unit, ep, per-election values}
totals = {e: {"valid": 0, "votes": 0, "areas": 0} for e in [*ELECTIONS, *BLOCS]}
reads = {e: [(e, [NIKH])] for e in ELECTIONS}  # pages -> [(property key, party ids)]
for k, (e, ids, _) in BLOCS.items():
    reads.setdefault(e, []).append((k, ids))
for e, keys in reads.items():
    pages = sorted(p for p in (ROOT / "out").glob(f"{e}_*.html") if re.fullmatch(rf"{e}_\d+\.html", p.name))
    assert len(pages) == 59, (e, len(pages))
    for page in pages:
        m = re.search(r"const D = (.*?);\n", page.read_text(encoding="utf-8"), re.DOTALL)
        D = json.loads(m.group(1))
        for f in D["geo"]["features"]:
            p = f["properties"]
            g = json.dumps(f["geometry"], separators=(",", ":"))
            k = hashlib.sha1(g.encode()).hexdigest()[:12]  # same community polygon across elections
            geoms.setdefault(k, f["geometry"])
            a = props.setdefault(k, {"n": p["name"], "u": p["unit"], "ep": D["ep_name"]})
            for key, ids in keys:
                v = sum(p["pv"].get(i, 0) for i in ids)
                a[key] = [v, p["valid"]]
                totals[key]["valid"] += p["valid"]
                totals[key]["votes"] += v
                totals[key]["areas"] += 1

features = [{"type": "Feature", "geometry": geoms[k], "properties": props[k]} for k in geoms]
for e, t in totals.items():
    print(f"{e}: {t['areas']} areas, votes {t['votes']:,} / {t['valid']:,} valid = {100 * t['votes'] / t['valid']:.2f}%")

data = {"elections": ELECTIONS, "blocs": {k: v[2] for k, v in BLOCS.items()}, "totals": totals, "geo": {"type": "FeatureCollection", "features": features}}
template = (ROOT / "analysis" / "nikh_map_template.html").read_text(encoding="utf-8")
out = ROOT / "out" / "nikh_2023-2024.html"
out.write_text(template.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))),
               encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(features)} areas)")
