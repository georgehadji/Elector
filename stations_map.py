"""Point map per polling station, placed at the polling venue: a candidate's preference votes,
or (candidate id 0) a party's share of valid votes.

Usage: python stations_map.py 2023/may 6 2 11 <venues.xls>
       python stations_map.py 2023/may 31 131 0 <venues.xls> Πατρέων
       (election, constituency, party id, candidate id or 0, ministry venue spreadsheet,
        optional municipality as in the results, e.g. Πατρέων)

Venues come from the Ministry of Interior spreadsheet "Εκλογικά τμήματα με κατάστημα ψηφοφορίας"
(ypes.gr, eklogika-tmimata). Addresses are geocoded once with OpenStreetMap Nominatim (1 request
per second, results cached in data/venues_geo.json) and kept only when they fall inside the
station's ELSTAT municipal unit.
"""
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import sqlite3
from collections import defaultdict
from pathlib import Path

import xlrd

sys.path.insert(0, str(Path(__file__).parent))  # run with python -I, which drops the script dir
from build import DB, HERE, match_units, norm, register, render_page, stems

CACHE = HERE / "data" / "venues_geo.json"
UA = "stavroi-map/0.1 (polling venue geocoding; low volume)"


def inside(lon, lat, geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        ring, hit = poly[0], False
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                hit = not hit
        if hit:
            return True
    return False


def nominatim(params):
    time.sleep(1.1)  # Nominatim usage policy: at most one request per second
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {**params, "format": "jsonv2", "countrycodes": "gr", "limit": 5})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
        return json.load(r)


def edge_km(lon, lat, geom):
    """Distance in km from a point to the nearest edge of a (multi)polygon."""
    import math
    kx = 111.32 * math.cos(math.radians(lat))
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    best = float("inf")
    for poly in polys:
        ring = poly[0]
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            ax, ay, bx, by = (x1 - lon) * kx, (y1 - lat) * 110.57, (x2 - lon) * kx, (y2 - lat) * 110.57
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy or 1)))
            best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


ABBREV = {"ΣΤΡ.": "ΣΤΡΑΤΗΓΟΥ", "ΣΤΡΑΤ.": "ΣΤΡΑΤΗΓΟΥ", "ΚΩΝ/ΝΟΥ": "ΚΩΝΣΤΑΝΤΙΝΟΥ", "ΕΘΝ.": "ΕΘΝΙΚΗΣ",
          "ΠΑΛ.": "ΠΑΛΑΙΩΝ", "ΑΓ.": "ΑΓΙΩΝ", "ΚΑΡ.": "ΚΑΡΟΛΟΥ", "ΓΡ.": "ΓΡΗΓΟΡΙΟΥ"}


def clean_street(street):
    """'ΣΤΡ. ΓΕΝΝΑΔΙΟΥ  53 (x) & Y' -> ('ΣΤΡΑΤΗΓΟΥ ΓΕΝΝΑΔΙΟΥ 53', 'ΣΤΡΑΤΗΓΟΥ ΓΕΝΝΑΔΙΟΥ')."""
    s = re.sub(r"\(.*?\)", " ", street)
    s = re.sub(r"\.(?=\w)", ". ", s)                           # 'Κ.Παλαμά' -> 'Κ. Παλαμά'
    s = re.split(r"&| ΚΑΙ |,", s.replace("-", " - "), flags=re.I)[0]
    s = re.sub(r"(?<=\d)\s*-.*$", "", s)                     # '59-ΠΑΠΑΗΛΙΑΚΗ' -> '59'
    s = re.sub(r"\s+-\s+.*$", "", s)                          # 'ΠΑΠΑΓΟΥ - ΚΑΛΛΙΔΟΥ' -> 'ΠΑΠΑΓΟΥ'
    words = [ABBREV.get(w, w) for w in s.split()]
    words = [w for w in words if not re.fullmatch(r"[Α-Ω]{1,2}\.([Α-Ω]\.)?", w)]  # drop initials
    full = " ".join(words)
    return full, re.sub(r"\s*\d+[Α-Ω]?$", "", full).strip()


# The venue spreadsheet names the Athens B sectors differently from the results site.
XLS_EP = {"Β1' Βόρειου Τομέα Αθηνών": "Β1' Αθηνών (Βόρειος Τομέας)",
          "Β2' Δυτικού Τομέα Αθηνών": "Β2' Αθηνών (Δυτικός Τομέας)",
          "Β3' Νότιου Τομέα Αθηνών": "Β3' Αθηνών (Νότιος Τομέας)"}


def venue_parts(venue):
    """'NAME  STREET  TOWN' -> (name, street, town). Names may hold a double space themselves
    ('4ο  ΔΗΜΟΤΙΚΟ ...') and a lone house number may sit in its own part ('ΔΑΒΑΚΗ  40')."""
    parts = []
    for p in (p.strip() for p in venue.split("  ")):
        if not p:
            continue
        if parts and re.fullmatch(r"\d+[Α-Ω]?", p):
            parts[-1] += " " + p
        else:
            parts.append(p)
    if len(parts) >= 3:
        return " ".join(parts[:-2]), parts[-2], parts[-1]
    return parts[0], "", parts[-1]


SETTLEMENTS = []


def settlement(name, unit):
    """(lon, lat) of the ELSTAT 2021 settlement with this name inside the unit, if exactly one."""
    if not SETTLEMENTS:
        with open(HERE / "data" / "oikismoi_2021.csv", encoding="utf-8") as f:
            SETTLEMENTS.extend((stems(r["OIKISMOS"].split(",")[0]), float(r["lon"]), float(r["lat"]))
                               for r in csv.DictReader(f))
    key = stems(name)
    hits = {(lon, lat) for k, lon, lat in SETTLEMENTS
            if k == key and (inside(lon, lat, unit["geometry"]) or edge_km(lon, lat, unit["geometry"]) < 0.3)}
    return hits.pop() if len(hits) == 1 else None


def geocode(venue, unit, unit_name, cache):
    """Address, then venue name, then street without number. A hit inside the unit wins;
    otherwise the first hit within 0.3 km of its edge (ELSTAT edges are simplified and
    long streets cross unit borders)."""
    if cache.get(venue):
        return cache[venue]
    name, street, town = venue_parts(venue)
    full, bare = clean_street(street)
    # Village venues give the village as "street" ("Θεριανό") or only a town ("Κρήνη"):
    # an ELSTAT settlement point in the unit beats any street search for those.
    village = street.split(",")[0] if street and not re.search(r"\d", street) else ""
    tries = [("street", {"street": full, "city": town}), ("name", {"q": f"{name}, {town}"}),
             ("name", {"q": name}), ("settlement", village),
             ("street-no-number", {"street": bare, "city": town}),
             ("street-no-number", {"street": bare, "city": unit_name}),
             ("settlement", "" if street else town),  # never a city centroid for a street address
             ("street-surname", {"q": f"{bare.split()[-1] if bare else ''}, {unit_name}"})]
    near = None
    for how, p in tries:
        if how == "settlement":
            hit = settlement(p, unit) if p else None
            if hit:
                cache[venue] = {"lat": hit[1], "lon": hit[0], "how": how}
                break
            continue
        if not all(p.values()):
            continue
        for hit in nominatim(p):
            if how == "street-surname" and hit.get("category") != "highway":
                continue  # a lone surname must resolve to a road, not to a place of that name
            lon, lat = float(hit["lon"]), float(hit["lat"])
            if inside(lon, lat, unit["geometry"]):
                cache[venue] = {"lat": lat, "lon": lon, "how": how}
                break
            if near is None and edge_km(lon, lat, unit["geometry"]) < 0.3:
                near = {"lat": lat, "lon": lon, "how": how + "-border"}
        if cache.get(venue):
            break
    cache[venue] = cache.get(venue) or near
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    return cache[venue]


def main(election, ep, party, cand, xls, dhm=None):
    """cand 0 = party mode (party votes over valid votes); dhm limits the map to one municipality."""
    db = sqlite3.connect(DB, timeout=60)
    ep_name = db.execute("SELECT name FROM ep WHERE election=? AND ep_id=?", (election, ep)).fetchone()[0]
    pname = db.execute("SELECT name FROM party WHERE election=? AND party_id=?", (election, party)).fetchone()[0]
    scope = f"Δήμος {dhm} · {ep_name}" if dhm else ep_name
    if cand:
        cname = db.execute("SELECT name FROM candidate WHERE election=? AND ep_id=? AND party_id=? AND cand_id=?",
                           (election, ep, party, cand)).fetchone()[0]
        labels = {"title": f"{cname} · {pname}", "num": "Σταυροί", "den": f"Ψήφοι {pname}",
                  "share": "% ψήφων κόμματος", "of": f"των ψηφοφόρων {pname}", "rank": "Θέση", "ord": "ος",
                  "scope": scope}
    else:
        labels = {"title": pname, "num": f"Ψήφοι {pname}", "den": "Έγκυρα", "share": "% εγκύρων",
                  "of": "των εγκύρων", "rank": "Θέση κόμματος", "ord": "ο", "scope": scope}

    sheet = xlrd.open_workbook(xls).sheet_by_index(0)
    venue_of = {int(r[2]): r[10].strip() for r in (sheet.row_values(i) for i in range(1, sheet.nrows))
                if norm(r[1]) == norm(XLS_EP.get(ep_name, ep_name))}

    # Each row: tm_id, den, ekd, registered, valid, denominator, numerator, rank, top candidate.
    where = "s.election=? AND s.ep_id=? AND s.ep_geo=? AND s.kind='Κ' AND (? IS NULL OR s.dhm_descr=?)"
    if cand:
        rows = db.execute(f"""
            WITH c AS (SELECT tm_id, cand_id, votes FROM cand_votes WHERE election=? AND party_id=?)
            SELECT s.tm_id, s.den_descr, s.ekd_descr, s.registered, s.valid,
              COALESCE((SELECT votes FROM party_votes p WHERE p.election=s.election AND p.tm_id=s.tm_id AND p.party_id=?), 0),
              COALESCE((SELECT votes FROM c WHERE c.tm_id=s.tm_id AND c.cand_id=?), 0),
              1 + (SELECT COUNT(*) FROM c WHERE c.tm_id=s.tm_id AND c.votes >
                   COALESCE((SELECT votes FROM c c2 WHERE c2.tm_id=s.tm_id AND c2.cand_id=?), 0)),
              NULL
            FROM station s WHERE {where} ORDER BY s.tm_id""",
                          (election, party, party, cand, cand, election, ep, ep, dhm, dhm)).fetchall()
    else:
        rows = db.execute(f"""
            WITH p AS (SELECT tm_id, party_id, votes FROM party_votes WHERE election=?)
            SELECT s.tm_id, s.den_descr, s.ekd_descr, s.registered, s.valid, s.valid,
              COALESCE((SELECT votes FROM p WHERE p.tm_id=s.tm_id AND p.party_id=?), 0),
              1 + (SELECT COUNT(*) FROM p WHERE p.tm_id=s.tm_id AND p.votes >
                   COALESCE((SELECT votes FROM p p2 WHERE p2.tm_id=s.tm_id AND p2.party_id=?), 0)),
              (SELECT c.name || ' (' || v.votes || ')' FROM cand_votes v JOIN candidate c
                 ON c.election=v.election AND c.ep_id=s.ep_id AND c.party_id=v.party_id AND c.cand_id=v.cand_id
               WHERE v.election=s.election AND v.tm_id=s.tm_id AND v.party_id=? AND v.votes > 0
               ORDER BY v.votes DESC LIMIT 1)
            FROM station s WHERE {where} ORDER BY s.tm_id""",
                          (election, party, party, party, election, ep, ep, dhm, dhm)).fetchall()
    assert rows, "no stations (check the municipality name)"
    seq = lambda tm: tm - ep * 10000
    assert all(seq(r[0]) in venue_of for r in rows), "station without venue in spreadsheet"

    units = json.loads((HERE / "data" / "dhm_enotites_2021.json").read_text(encoding="utf-8"))["features"]
    unit_of = match_units({r[1] for r in rows}, units)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    venues = defaultdict(lambda: {"st": []})
    for tm, den, ekd, reg, valid, pv, cv, rank, top in rows:
        v = venues[venue_of[seq(tm)]]
        v["den"] = den
        v["st"].append([seq(tm), ekd, pv, cv, rank] + ([top] if top else []))
    located, missing = [], []
    for i, (venue, v) in enumerate(venues.items(), 1):
        g = geocode(venue, unit_of[v["den"]], v["den"], cache)
        (located if g else missing).append(venue)
        if g:
            v.update(g)
        print(f"  {i}/{len(venues)} {'ok ' + g['how'] if g else 'NOT FOUND'}: {venue}", flush=True)

    data = {"ep_name": ep_name, "party": pname, "election": election, "mode": "cand" if cand else "party",
            "labels": labels,
            "venues": [{"venue": k, **v} for k, v in venues.items() if "lat" in v],
            "missing": [{"venue": k, **venues[k]} for k in missing]}
    out = HERE / "out" / f"{election.replace('/', '-')}_{ep}_tm_{party}-{cand}{'_' + dhm if dhm else ''}.html"
    data["links"] = register(out.name, election, ep, ep_name,
                             f"Ανά τμήμα · {labels['title']}" + (f" · Δήμος {dhm}" if dhm else ""))
    out.write_text(render_page("stations_template.html", data), encoding="utf-8")
    on_map = sum(s[3] for v in data["venues"] for s in v["st"])
    print(f"venues {len(venues)}, located {len(located)}, missing {len(missing)}; "
          f"votes on map {on_map} of {sum(r[6] for r in rows)}\nwrote {out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5],
         sys.argv[6] if len(sys.argv) > 6 else None)
