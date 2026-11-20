"""Nationwide map of polling venues: leading party, and each political bloc's share and leading party.

Usage: python -I -X utf8 analysis/venue_map.py [--geocode]   (after analysis/venue_parties.py)
Reads analysis/venue_parties/venues.csv and venue_parties_long.csv; writes analysis/venue_parties/venue_map.html.

Venue position, best first: the geocode cache (data/venues_geo.json, via venues.csv); the ELSTAT 2021
settlement point named by a village venue (stations_map.settlement, offline); otherwise the centre of the
venue's ELSTAT community, shown as approximate (urban venues without a geocode pile up there, so they
are spread on a small spiral).

--geocode asks Nominatim (stations_map.geocode: 1 request/s, kept only inside the municipal unit) for every venue
that would otherwise sit on a community centre. Results go to analysis/venue_parties/venues_geo_extra.json, not to
data/venues_geo.json (the repo's cache); a rerun resumes from it, and without --geocode the page uses it as it is.
"""
import csv
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
from venue_parties import BLOCS, short

import stations_map
from config import DB, ELECTION_NAMES, HERE
from matching import boundaries, centroid, match_units
from stations_map import settlement, venue_parts
from web import common_css, fill

SRC = Path(__file__).resolve().parent / "venue_parties"
TEMPLATE = Path(__file__).resolve().parent / "venue_map_template.html"
GEO = SRC / "venues_geo_extra.json"
MIN_SHARE = 0.5  # % of valid votes; smaller parties outside every bloc are left out of the page


def read(name):
    with open(SRC / name, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def main():
    elections = list(ELECTION_NAMES.values())
    meta, per = {}, defaultdict(dict)  # id -> venue fields; id -> {election index: [valid, stations, votes]}
    for r in read("venues.csv"):
        i = int(r["id"])
        meta.setdefault(i, r)
        per[i][elections.index(r["election"])] = [int(r["valid"]), int(r["τμήματα"]), []]
    in_bloc = {p for ps in BLOCS.values() for p in ps}
    for r in read("venue_parties_long.csv"):
        slot = per[int(r["id"])][elections.index(r["election"])]
        pid, n = int(r["party_id"]), int(r["votes"])
        if pid in in_bloc or 100 * n >= MIN_SHARE * slot[0]:
            slot[2] += [pid, n]

    units, comm_by_code, _ = boundaries()
    unit_of = {}
    by_ep = defaultdict(set)
    for m in meta.values():
        by_ep[m["περιφέρεια"]].add(m["δημ. ενότητα"])
    for ep, dens in by_ep.items():
        unit_of.update({(ep, d): u for d, u in match_units(dens, units).items()})

    stations_map.CACHE = GEO  # geocode() saves its cache there after every venue
    geo = json.loads(GEO.read_text(encoding="utf-8")) if GEO.exists() else {}
    fetch, errors = "--geocode" in sys.argv, 0
    placed, spiral = {}, defaultdict(int)  # spiral: venues already put on one community centre
    how = defaultdict(int)
    for i, m in sorted(meta.items()):
        if m["lat"]:
            placed[i] = (float(m["lat"]), float(m["lon"]), 0)
            how["geocode"] += 1
            continue
        unit = unit_of.get((m["περιφέρεια"], m["δημ. ενότητα"]))
        _, street, town = venue_parts(m["κατάστημα"]) if m["κατάστημα"].strip() else ("", "", "")
        village = street.split(",")[0] if street and not any(c.isdigit() for c in street) else ""
        hit = None
        if unit:
            hit = (settlement(village, unit) if village else None) or (settlement(town, unit) if not street and town else None)
        if hit:
            placed[i] = (hit[1], hit[0], 1)
            how["settlement"] += 1
            continue
        text = m["κατάστημα"]
        if fetch and unit and text.strip() and text not in geo:
            try:
                stations_map.geocode(text, unit, m["δημ. ενότητα"], geo)
                errors = 0
            except OSError as e:  # timeouts, 429/403: skip this venue (not cached, so a rerun retries it)
                errors += 1
                print(f"nominatim error ({errors}): {e}", flush=True)
                if errors >= 5:
                    sys.exit("5 Nominatim errors in a row: stopping; rerun later to resume")
            if len(geo) % 50 == 0:
                print(f"geocoded {len(geo)} venues", flush=True)
        if geo.get(text):
            placed[i] = (geo[text]["lat"], geo[text]["lon"], 0)
            how["nominatim"] += 1
            continue
        code = m["κοινότητα κωδ."]
        geom = comm_by_code[code]["geometry"] if code in comm_by_code else unit["geometry"] if unit else None
        if not geom:
            how["none"] += 1
            continue
        lon, lat = centroid(geom)
        k = spiral[code or m["δημ. ενότητα"]]
        spiral[code or m["δημ. ενότητα"]] += 1
        r, a = 0.0012 * math.sqrt(k), k * 2.39996  # golden-angle spiral, ~130 m between rings
        placed[i] = (lat + r * math.sin(a), lon + r * math.cos(a) / math.cos(math.radians(lat)), 2)
        how["community centre"] += 1

    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    names, colors = {}, {}
    for e in ELECTION_NAMES:  # a later election's name and colour win
        for pid, name, color in db.execute("SELECT party_id, name, color FROM party WHERE election=?", (e,)):
            names[pid] = name
            if color and color.strip():
                colors[pid] = "#" + color.strip()[2:]
    used = {p for v in per.values() for s in v.values() for p in s[2][::2]}
    eps = sorted(by_ep)
    data = {
        "mode": "party",  # common.js legend wording: "Καμία ψήφος"
        "elections": elections,
        "parties": {p: [short(p, names), colors.get(p, "#8a8a85")] for p in used},
        "blocs": BLOCS,
        "eps": eps,
        "venues": [[round(lat, 5), round(lon, 5), q, eps.index(meta[i]["περιφέρεια"]), meta[i]["δημ. ενότητα"],
                    meta[i]["κοινότητα"], meta[i]["κατάστημα"], [per[i].get(k) for k in range(len(elections))]]
                   for i, (lat, lon, q) in sorted(placed.items())],
    }
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*COMMON_CSS*/", common_css())
    page = fill(page.replace("/*COMMON_JS*/", (HERE / "common.js").read_text(encoding="utf-8")), skip="#map", compact=True)
    out = SRC / "venue_map.html"
    out.write_text(page.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))),
                   encoding="utf-8")
    print(f"venues placed: {dict(how)}\nwrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
