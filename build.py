"""Build an HTML map of preference votes per electoral district (Ε.Δ.) for one constituency.

Usage: python build.py 2023/may 45   ->   out/2023-may_45.html

Reads data/stavroi.sqlite (filled by fetch.py) and the ELSTAT 2021 boundaries in data/.
Each Ε.Δ. is matched to an ELSTAT local community inside its municipal unit: by community
name, or through a settlement of that community (ELSTAT settlements list). Names are compared
by word stems, because the ministry uses the genitive ("ΠΙΚΕΡΝΙΟΥ") and ELSTAT the nominative
("Πικέρνης"). Urban municipal units with a single community (e.g. Athens) show as one area.
"""
import csv
import difflib
import html
import json
import re
import sqlite3
import sys
import unicodedata
import urllib.parse
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "data" / "stavroi.sqlite"
# Stripped in this order; "ΙΕΡΑΣ ΠΟΛΗΣ" is Missolonghi's honorific, absent from ELSTAT's community name.
PREFIXES = ("ΨΕΥΔΟΔΗΜΟΤΙΚΗ ΚΟΙΝΟΤΗΤΑ", "ΔΗΜΟΤΙΚΗ ΚΟΙΝΟΤΗΤΑ", "ΤΟΠΙΚΗ ΚΟΙΝΟΤΗΤΑ", "ΔΗΜΟΤΙΚΗ ΕΝΟΤΗΤΑ", "ΕΔ",
            "ΙΕΡΑΣ ΠΟΛΗΣ")


def norm(s):
    # The ministry writes a capital alpha with tonos as a right quote ("’ργους" = "Άργους").
    s = unicodedata.normalize("NFD", re.sub(r"’(?=\w)", "Α", s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").upper()
    s = re.sub(r"ΚΩΝ/Ν", "ΚΩΝΣΤΑΝΤΙΝ", s)  # "ΑΓΙΟΥ ΚΩΝ/ΝΟΥ"
    s = re.sub(r"\(.*?\)", lambda m: m.group(0)[1:-1] if s.strip().startswith("(") else " ", s)
    s = re.sub(r"[^\w ]", " ", s.replace("Ε.Δ.", "ΕΔ"))
    s = re.sub(r"^\d+\s*", "", re.sub(r"\s+", " ", s).strip())
    for p in PREFIXES:
        if s.startswith(p + " "):
            s = s[len(p) + 1:]
    return s.strip()


def phonetic(w):
    """Spelling-insensitive form: Η/Υ/ΕΙ/ΟΙ -> Ι, Ω -> Ο, ΑΙ -> Ε, double consonants single
    (ΒΛΙΣΙΔΙΑΣ ~ Βλησιδιά, ΧΩΤΟΥΣΑΣ ~ Χωτούσσα)."""
    # ΑΙ before ΕΙ: "ΚΟΨΑΙΙΚΑ" -> ΚΟΨΕΙΚΑ -> ΚΟΨΙΚΑ, as the ministry's "ΚΟΨΕΙΚΑ".
    w = w.replace("ΟΥ", "U").replace("ΑΙ", "Ε").replace("ΕΙ", "Ι").replace("ΟΙ", "Ι")
    w = w.translate(str.maketrans("ΗΥΩ", "ΙΙΟ")).replace("U", "ΟΥ")
    return re.sub(r"([^ΑΕΗΙΟΥΩ])\1", r"\1", w)


def stems(s):
    """Word stems without Greek case endings: ΠΙΚΕΡΝΙΟΥ and ΠΙΚΕΡΝΗΣ both give ('ΠΙΚΕΡΝ',)."""
    out = []
    for w in norm(s).split():
        w = phonetic(w)
        st = re.sub(r"[ΑΕΗΙΟΥΩ]*[ΣΝ]?$", "", w)
        out.append(st if len(st) >= 3 else w[:3])  # short words: ΝΕΟΥ and ΝΕΟΣ both give ΝΕΟ
    return tuple(out)


def one_edit(x, y):
    """At most one letter inserted, deleted or replaced."""
    if abs(len(x) - len(y)) > 1:
        return False
    if len(x) > len(y):
        x, y = y, x
    i = next((k for k in range(len(x)) if x[k] != y[k]), len(x))
    return x[i + (len(x) == len(y)):] == y[i + 1:]


def aliases(label):
    """'Ωριάς ή Ωργιάς' -> both names; 'Πικέρνης,ο' -> 'Πικέρνης'."""
    label = label.split(",")[0]
    return [p for p in re.split(r"\s+ή\s+", label) if p.strip()]


def find(name, index, loose=False):
    """index: [(alias, code)]. Tries exact name, then exact stems, then a unique stem prefix;
    a level with several different codes is ambiguous and falls through to None."""
    key = stems(name)

    def word_prefix(a):  # abbreviations and spelling drift: "Ν ΧΙΛΗΣ" ~ "Νέας Χηλής"
        s = stems(a)
        return len(s) == len(key) and all(x.startswith(y) or y.startswith(x) for x, y in zip(s, key)
                                          if min(len(x), len(y)) >= 1)

    # Loose tests, tried last and logged for review.
    def compound(a):  # "ΕΞΩΧΩΡΑΣ" ~ "Έξω Χώρας"
        return "".join(stems(a)) == "".join(key)

    def qualified(a):  # the ministry adds a qualifier: "ΚΑΜΠΟΥ ΒΟΙΩΝ" ~ "Κάμπου"
        s = stems(a)
        return len(s) < len(key) and key[:len(s)] == s

    def typo(a):  # one letter apart (ΟΥ counts as one) in stems of 5+: "ΒΑΣΙΛΙΚΑΔΩΝ" ~ "Βασιλικιάδων", "ΖΟΥΡΟΥΔΙΟΥ" ~ "Ζουριδίου"
        u = lambda w: w.replace("ΟΥ", "U")
        s = stems(a)
        return len(s) == len(key) and all(
            x == y or (min(len(u(x)), len(u(y))) >= 5 and one_edit(u(x), u(y))) for x, y in zip(s, key))

    def first_word(a):  # each side qualifies the same name: "ΚΑΣΤΑΝΕΑΣ ΒΟΙΩΝ" ~ "Καστανέας Επιδαύρου Λιμηράς"
        s = stems(a)
        return (len(s) > 1 and len(key) > 1 and s[0] == key[0] and len(s[0]) >= 5
                and not s[0].startswith(("ΑΓΙ", "ΜΕΓΑΛ")))  # "Αγίου ...", "Μεγάλου ..." name nothing alone

    tests = (lambda a: norm(a) == norm(name),
             lambda a: stems(a) == key,
             word_prefix,
             lambda a: stems(a)[-len(key):] == key,  # "ΨΑΘΑΔΩΝ" ~ "Νέοι Ψαθάδες"
             lambda a: stems(a)[:len(key)] == key) + ((compound, qualified, typo, first_word) if loose else ())
    for test in tests:
        hits = {}
        for a, code in index:
            if test(a):
                r = difflib.SequenceMatcher(None, norm(a), norm(name)).ratio()
                hits[code] = max(r, hits.get(code, 0))
        best = sorted(hits.values(), reverse=True)
        # Several communities: keep the closest spelling only if it is clearly closer.
        hit = max(hits, key=hits.get) if len(best) == 1 or (best and best[0] - best[1] >= 0.1) else None
        if hit and test in (compound, qualified, typo, first_word):
            print(f"  {test.__name__} match: {name} -> {[a for a, c in index if c == hit and test(a)][0]}")
        if hits:
            return hit
    return None


def centroid(geom):
    ring = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]
    return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)


def match_units(den_names, units):
    """Map each ministry municipal-unit name to one ELSTAT unit; same-name ties go to the
    candidate nearest the centre of the unambiguous matches."""
    by_key = defaultdict(list)
    for u in units:
        by_key[stems(u["properties"]["NAME_GR"])].append(u)
    out, ambiguous = {}, []
    for d in den_names:
        hits = by_key.get(stems(d), [])
        if len(hits) == 1:
            out[d] = hits[0]
        elif hits:
            ambiguous.append((d, hits))
    if out:
        # Same regional unit (first 2 code digits) as the unambiguous matches wins: Grevena's
        # Χασίων (15...) over Trikala's (26...), which lies nearer the Grevena centroid.
        region = max({u["properties"]["CODE"][:2] for u in out.values()},
                     key=[u["properties"]["CODE"][:2] for u in out.values()].count)
        for i, (d, hits) in enumerate(ambiguous):
            same = [u for u in hits if u["properties"]["CODE"].startswith(region)]
            ambiguous[i] = (d, same or hits)
        cs = [centroid(u["geometry"]) for u in out.values()]
        cx, cy = sum(c[0] for c in cs) / len(cs), sum(c[1] for c in cs) / len(cs)
        for d, hits in ambiguous:
            out[d] = min(hits, key=lambda u: (centroid(u["geometry"])[0] - cx) ** 2 + (centroid(u["geometry"])[1] - cy) ** 2)
    return out


def label(c):
    # Accented classes: ELSTAT writes some labels in capitals without accents.
    name = re.sub(r"^(Ψευδοδημοτικ[ηή]|Δημοτικ[ηή]|Τοπικ[ηή]) Κοιν[οό]τητα\s+", "", c["properties"]["LAU_LABEL3"], flags=re.I)
    return name


def main(election, ep):
    db = sqlite3.connect(DB)
    q = lambda sql, *a: db.execute(sql, (election, *a)).fetchall()

    parties = {pid: (name, "#" + color[2:] if color else "#888") for pid, name, color in
               q("SELECT party_id, name, color FROM party WHERE election=?")}
    cands = q("SELECT c.party_id, c.cand_id, c.name, COALESCE(t.votes,0) FROM candidate c "
              "LEFT JOIN ep_total t USING(election, ep_id, party_id, cand_id) "
              "WHERE c.election=? AND c.ep_id=? ORDER BY c.party_id, t.votes DESC", ep)
    # The source writes a capital alpha with tonos as a right quote ("’ννα" = "Άννα").
    cands = [(pid, cid, re.sub(r"’(?=\w)", "Ά", name), total) for pid, cid, name, total in cands]
    # No published preference votes (June 2023 results site): map party votes / valid instead.
    # (Party leaders still get a constituency total there, so test the per-station data.)
    party_mode = not q("SELECT 1 FROM cand_votes WHERE election=? AND tm_id BETWEEN ? AND ? AND votes > 0 LIMIT 1",
                       ep * 10000, ep * 10000 + 9999)
    if party_mode and not q("SELECT 1 FROM station WHERE election=? AND ep_id=? LIMIT 1", ep):
        sys.exit(f"no stations for {election} EP {ep}: run fetch.py first")

    # Only ordinary stations of this constituency located in it can be placed on the map.
    stations = q("SELECT tm_id, den_descr, ekd_descr, registered, valid FROM station "
                 "WHERE election=? AND ep_id=? AND ep_geo=? AND kind='Κ' ORDER BY tm_id", ep, ep)
    area_of = {tm: (den, ekd) for tm, den, ekd, *_ in stations}
    # A settlement in parentheses follows its own Ε.Δ. in station order: "Ε.Δ. ΒΑΛΑΩΡΑΣ", "(ΚΑΣΤΡΑΚΙΟΥ)".
    parent, last = {}, {}
    for tm, den, ekd, *_ in stations:
        if ekd.startswith("("):
            parent.setdefault((den, ekd), last.get(den))
        else:
            last[den] = ekd
    areas = defaultdict(lambda: {"reg": 0, "valid": 0, "pv": defaultdict(int), "cv": defaultdict(int), "tm": 0})
    for tm, den, ekd, reg, valid in stations:
        a = areas[(den, ekd)]
        a["reg"] += reg or 0
        a["valid"] += valid or 0
        a["tm"] += 1
    lo, hi = ep * 10000, ep * 10000 + 9999  # station ids of this constituency's directory
    for tm, pid, v in q("SELECT tm_id, party_id, votes FROM party_votes WHERE election=? AND tm_id BETWEEN ? AND ?", lo, hi):
        if tm in area_of:
            areas[area_of[tm]]["pv"][pid] += v
    for tm, pid, cid, v in q("SELECT tm_id, party_id, cand_id, votes FROM cand_votes "
                             "WHERE election=? AND tm_id BETWEEN ? AND ?", lo, hi):
        if tm in area_of:
            areas[area_of[tm]]["cv"][f"{pid}:{cid}"] += v

    units = json.loads((HERE / "data" / "dhm_enotites_2021.json").read_text(encoding="utf-8"))["features"]
    comms = json.loads((HERE / "data" / "koinotites_2021.json").read_text(encoding="utf-8"))["features"]
    comm_by_code = {c["properties"]["KAL2022"]: c for c in comms}
    with open(HERE / "data" / "oikismoi_2021.csv", encoding="utf-8") as f:
        settlements = [(r["KALCODE"][:8], r["OIKISMOS"]) for r in csv.DictReader(f)]
    unit_match = match_units({den for den, _ in areas}, units)

    by_code, unmatched, seat_fallbacks, hit_of = {}, [], 0, {}
    # Parent Ε.Δ. first, so a parenthesised settlement can fall back on the parent's community.
    for (den, ekd), a in sorted(areas.items(), key=lambda kv: (kv[0][1].startswith("("), kv[0])):
        hit = None
        unit = unit_match.get(den)
        if unit:
            ucode = unit["properties"]["CODE"]
            inside = [c for c in comms if c["properties"]["KAL2022"].startswith(ucode)]
            comm_index = [(k, c["properties"]["KAL2022"]) for c in inside for k in aliases(label(c))]
            hit = find(ekd, comm_index)
            if hit is None:
                pool = [(k, code) for code, name in settlements if code.startswith(ucode)
                        for k in aliases(name) if code in comm_by_code]
                hit = find(ekd, pool)
                p = hit_of.get((den, parent.get((den, ekd))))
                if hit is None and p:  # same-name settlements in several communities (two Καστράκιον)
                    hit = find(ekd, [(k, code) for k, code in pool if code == p])
            # Merged Ε.Δ. "Ε.Δ. ΣΙΒΙΣΤΑΣ-ΧΡΥΣΟΒΩΝ": the first name is the community seat.
            # Not settlements in parentheses: "(ΑΙ-ΓΙΑΝΝΗΣ)" is one name, and "ΑΙ" alone matches anything.
            if hit is None and "-" in ekd and ekd.startswith("Ε.Δ."):
                hit = find(ekd.split("-")[0], comm_index)
            renamed = re.search(r"\((.+)\)", ekd)
            if hit is None and renamed and not ekd.startswith("("):  # "Ε.Δ. ΦΙΛΙΠΠΟΥΠΟΛΗΣ (ΤΕΤΡΑΛΟΦΟΥ)": today's name
                hit = find(renamed.group(1), comm_index)
            if hit is None:  # loose spelling tests only after every strict one, so they never pre-empt an exact settlement
                pool = [(k, code) for code, name in settlements if code.startswith(ucode)
                        for k in aliases(name) if code in comm_by_code]
                hit = find(ekd, comm_index, loose=True) or find(ekd, pool, loose=True)
            if hit is None and hit_of.get((den, parent.get((den, ekd)))):
                # shortcut: a settlement ELSTAT does not list (Λαγκαδάκι) goes to its parent Ε.Δ.'s community.
                hit = hit_of[(den, parent[(den, ekd)])]
                seat_fallbacks += 1
                print(f"  assumed in parent community: {ekd} -> {label(comm_by_code[hit])}")
            if hit is None and len(inside) == 1:
                hit = inside[0]["properties"]["KAL2022"]  # single-community unit (e.g. Athens)
            if hit is None:
                # shortcut: a suburb missing from ELSTAT's lists is assumed to lie in the unit's
                # seat community (true for Alexandroupoli's suburbs); shown as "includes" on the map.
                seat = [c for c in inside if stems(label(c)) == stems(den)]
                hit = seat[0]["properties"]["KAL2022"] if len(seat) == 1 else None
                if hit:
                    seat_fallbacks += 1
                    print(f"  assumed in seat community: {ekd} -> {label(seat[0])}")
        if hit is None:
            unmatched.append({"name": norm(ekd).title() or den, "unit": den, **a})
            continue
        hit_of[(den, ekd)] = hit
        # Several Ε.Δ. can fall in one community (settlements, urban units): sum them.
        if hit not in by_code:
            c = comm_by_code[hit]
            by_code[hit] = {"type": "Feature", "geometry": c["geometry"], "properties": {
                "name": den if label(c).isupper() else label(c), "unit": den, "reg": 0, "valid": 0, "tm": 0, "incl": [],
                "pv": defaultdict(int), "cv": defaultdict(int)}}
        p = by_code[hit]["properties"]
        p["incl"].append(norm(ekd).title())
        for fld in ("reg", "valid", "tm"):
            p[fld] += a[fld]
        for fld in ("pv", "cv"):
            for k, v in a[fld].items():
                p[fld][k] += v
    features = list(by_code.values())

    # Self-check: votes on the map never exceed the official constituency totals.
    mapped = defaultdict(int)
    for f in features:
        for k, v in f["properties"]["cv"].items():
            mapped[k] += v
    cand_list = []
    if party_mode:  # one pseudo-candidate per party, "pid:0"; the template divides by valid votes
        for f in features:
            for pid, v in f["properties"]["pv"].items():
                mapped[f"{pid}:0"] += v
        for pid, total in q("SELECT p.party_id, SUM(p.votes) FROM party_votes p JOIN station s USING(election, tm_id) "
                            "WHERE p.election=? AND s.ep_id=? GROUP BY 1 HAVING SUM(p.votes) > 0", ep):
            k = f"{pid}:0"
            assert mapped[k] <= total, (parties[pid][0], mapped[k], total)
            cand_list.append({"k": k, "party": pid, "name": parties[pid][0], "total": total, "mapped": mapped[k],
                              "partial": False})
        cands = []
    for pid, cid, name, total in cands:
        k = f"{pid}:{cid}"
        assert mapped[k] <= total or total == 0, (name, mapped[k], total)
        # The ministry publishes most of a party leader's crosses only as a constituency total
        # (e.g. Mitsotakis, A' Thessaloniki 2023: 5,017 of 112,971 per station).
        partial = total > 0 and mapped[k] < 0.5 * total
        cand_list.append({"k": k, "party": pid, "name": name, "total": total, "mapped": mapped[k],
                          "partial": partial})
    full = [c for c in cand_list if not c["partial"]]
    coverage = sum(c["mapped"] for c in full) / (sum(c["total"] for c in full) or 1)
    partial_names = [c["name"] for c in cand_list if c["partial"]]
    print(f"areas: {len(areas)} Ε.Δ. -> {len(features)} map areas, {len(unmatched)} unmatched; "
          f"{'party' if party_mode else 'preference'} votes on map: {coverage:.1%}"
          + (f"; no per-station data: {', '.join(partial_names)}" if partial_names else ""))
    if unmatched:
        print("unmatched:", ", ".join(f'{u["name"]} ({u["unit"]})' for u in unmatched))

    ep_name = (q("SELECT name FROM ep WHERE election=? AND ep_id=?", ep) or [[str(ep)]])[0][0]
    data = {
        "election": election, "ep": ep, "ep_name": ep_name, "mode": "party" if party_mode else "cand",
        "parties": {pid: {"name": parties[pid][0], "color": parties[pid][1]} for pid in {c["party"] for c in cand_list}},
        "cands": cand_list, "unmatched": [{"name": u["name"], "unit": u["unit"]} for u in unmatched],
        "coverage": coverage, "geo": {"type": "FeatureCollection", "features": features},
    }
    out = HERE / "out" / f"{election.replace('/', '-')}_{ep}.html"
    out.parent.mkdir(exist_ok=True)
    data["links"] = register(out.name, election, ep, ep_name,
                             "Ανά περιοχή · κόμματα (% εγκύρων)" if party_mode else "Ανά περιοχή · όλοι οι υποψήφιοι")
    out.write_text(render_page("template.html", data), encoding="utf-8")
    print(f"wrote {out}")
    return {"ep": ep, "name": ep_name, "file": out.name, "areas": len(areas), "map_areas": len(features),
            "unmatched": len(unmatched), "seat": seat_fallbacks, "coverage": coverage}


def render_page(template, data):
    """Template with the shared UI (common.css/js) and the page data inlined: one self-contained file."""
    page = (HERE / template).read_text(encoding="utf-8")
    for placeholder, name in (("/*COMMON_CSS*/", "common.css"), ("/*COMMON_JS*/", "common.js")):
        page = page.replace(placeholder, (HERE / name).read_text(encoding="utf-8"))
    return page.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))  # last: data may contain anything


PARTY_ARTIFACTS = [  # published static map pages, one per party (June share + May top crosses)
    ("ΝΔ", "https://claude.ai/artifact/AA8ahMFs93axFWPMqjE89K"),
    ("ΣΥΡΙΖΑ", "https://claude.ai/artifact/6T4E54QLvdcgcEoarXMzQ3"),
    ("ΠΑΣΟΚ-ΚΙΝΑΛ", "https://claude.ai/artifact/H55tMGJdo7mGiVpks9veRT"),
    ("ΚΚΕ", "https://claude.ai/artifact/7QEvCY57DX38fXR3RKMcw3"),
    ("Σπαρτιάτες", "https://claude.ai/artifact/U9ZYzdXc5TAx3c4NZ5pWoE"),
    ("Ελληνική Λύση", "https://claude.ai/artifact/9FCakTKkFzEJp4jTPbaKkR"),
    ("ΝΙΚΗ", "https://claude.ai/artifact/DkDUaRmft4CLwX5uToXgSM"),
    ("Πλεύση Ελευθερίας", "https://claude.ai/artifact/9YkgFraGBABMQtheiVBUMQ"),
]


def register(file, election, ep, ep_name, label):
    """Record a map in out/maps.json, rewrite out/index.html, and return links to the
    constituency's other maps (area map first) for the page's view switcher."""
    path = HERE / "out" / "maps.json"
    maps = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    maps[file] = {"election": election, "ep": ep, "ep_name": ep_name, "label": label}
    path.write_text(json.dumps(maps, ensure_ascii=False, indent=1), encoding="utf-8")
    order = sorted(maps.items(), key=lambda kv: (kv[1]["election"], kv[1]["ep_name"], "_tm_" in kv[0], kv[1]["label"]))
    sys.path.insert(0, str(HERE))  # python -I drops the script dir
    from nikh_report import ELECTED  # lazy: nikh_report imports this module
    nikh = sorted((kv for kv in order if "_tm_131-" in kv[0]), key=lambda kv: (kv[1]["election"] != "2023/june", kv[1]["ep_name"]))
    items = ['</ul><h2>Στατικοί χάρτες ανά κόμμα: βουλευτικές 2019 και 2023, ευρωεκλογές 2024</h2>'
             '<p>Ιδιωτικά artifacts στο claude.ai: ανοίγουν μόνο για όσους έχουν πρόσβαση.</p><ul>']
    items += [f'<li><a href="{u}">{html.escape(n)}</a></li>' for n, u in PARTY_ARTIFACTS]
    items += ['</ul><h2>ΝΙΚΗ: οι 9 περιφέρειες με εκλεγμένο βουλευτή (Ιούνιος 2023)</h2>'
             '<p>Ποσοστό ΝΙΚΗ ανά εκλογικό κατάστημα. <a href="NIKH_eklegmenoi_2023.html">Αναφορά Μαΐου–Ιουνίου</a> · '
             '<a href="../exports/NIKH_2023_ana_dhm_enotita.csv">CSV ανά δημοτική ενότητα</a></p><ul>']
    for f, m in nikh:
        mp = f' · {ELECTED[m["ep"]]}' if m["election"] == "2023/june" and m["ep"] in ELECTED else ""
        items.append(f'<li><a href="{urllib.parse.quote(f)}">{html.escape(m["ep_name"])}{html.escape(mp)}</a>'
                     f' <span style="color:var(--ink-2)">{"Ιούνιος" if m["election"] == "2023/june" else "Μάιος"} 2023 · {html.escape(m["label"])}</span></li>')
    last = None
    for f, m in (kv for kv in order if "_tm_131-" not in kv[0]):
        if (m["election"], m["ep_name"]) != last:
            last = (m["election"], m["ep_name"])
            items.append(f'</ul><h2>{html.escape(m["ep_name"])} · {m["election"]}</h2><ul>')
        items.append(f'<li><a href="{urllib.parse.quote(f)}">{html.escape(m["label"])}</a></li>')
    (HERE / "out" / "index.html").write_text(f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Χάρτες σταυρών</title><style>
:root{{color-scheme:light;--surface:#fcfcfb;--ink:#1d1d1b;--ink-2:#5c5b57;--line:#e4e3df;--link:#256abf}}
@media (prefers-color-scheme: dark){{:root{{color-scheme:dark;--surface:#1a1a19;--ink:#ecebe7;--ink-2:#a8a7a2;--line:#383835;--link:#6da7ec}}}}
body{{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--surface);color:var(--ink)}}
main{{max-width:760px;margin:0 auto;padding:16px}} h1{{font-size:21px}} h2{{font-size:16px;margin:20px 0 4px}}
p{{color:var(--ink-2)}} a{{color:var(--link)}} ul{{margin:0;padding-left:20px}} li{{padding:6px 0}}</style></head><body><main>
<h1>Χάρτες σταυρών</h1>
<p>Ανά περιοχή: όλοι οι υποψήφιοι ανά κοινότητα. Ανά τμήμα: ένας υποψήφιος ή κόμμα ανά εκλογικό κατάστημα
(πιο λεπτομερές στις πόλεις).</p>
<p>Κάλυψη ανά νομό (πόσοι σταυροί φαίνονται στον χάρτη): {" · ".join(
    f'<a href="{q.name}">{ {"june": "Ιούνιος", "may": "Μάιος", "euro": "Ευρωεκλογές", "": "Βουλευτικές"}[q.stem[11:]]} {q.stem[6:10]}</a>'
    for q in sorted((HERE / "out").glob("index_*.html")))}</p>
<ul>{"".join(items)}</ul></main></body></html>""", encoding="utf-8")
    return [{"href": f, "label": m["label"]} for f, m in order if m["ep"] == ep and m["election"] == election and f != file]


def build_all(election):
    """Build every fetched constituency and an index page listing them with match quality."""
    eps = [r[0] for r in sqlite3.connect(DB).execute(
        "SELECT ep_id FROM ep WHERE election=? ORDER BY name", (election,))]
    rows = []
    for ep in eps:
        print(f"--- EP {ep}")
        try:
            rows.append(main(election, ep))
        except (SystemExit, Exception) as e:  # one bad constituency must not stop the rest
            print(f"FAILED EP {ep}: {e!r}")
            rows.append({"ep": ep, "name": str(ep), "file": None, "error": repr(e)})
    tr = "".join(
        f'<tr><td><a href="{r["file"]}">{r["name"]}</a></td><td class="n">{r["areas"]}</td>'
        f'<td class="n">{r["map_areas"]}</td><td class="n">{r["unmatched"]}</td><td class="n">{r["seat"]}</td>'
        f'<td class="n">{r["coverage"]:.1%}</td></tr>' if r.get("file") else
        f'<tr><td>{r["name"]}</td><td colspan="5">σφάλμα: {r["error"]}</td></tr>' for r in rows)
    (HERE / "out" / f"index_{election.replace('/', '-')}.html").write_text(f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Χάρτες σταυρών</title><style>
:root{{--surface:#fcfcfb;--ink:#1d1d1b;--ink-2:#5c5b57;--line:#e4e3df}}
@media (prefers-color-scheme: dark){{:root{{--surface:#1a1a19;--ink:#ecebe7;--ink-2:#a8a7a2;--line:#383835}}}}
body{{margin:0;font:14px/1.45 system-ui,sans-serif;background:var(--surface);color:var(--ink)}}
main{{max-width:900px;margin:0 auto;padding:16px}} a{{color:inherit}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}} th{{color:var(--ink-2);font-size:12px}}
.n{{text-align:right}} p{{color:var(--ink-2)}}</style></head><body><main>
<h1 style="font-size:20px">Χάρτες σταυρών · {election}</h1>
<p>Ε.Δ.: εκλογικά διαμερίσματα · Περιοχές: κοινότητες στον χάρτη · Έδρα: διαμερίσματα που μπήκαν στην κοινότητα-έδρα
χωρίς αντιστοίχιση ονόματος · Κάλυψη: σταυροί στον χάρτη ως ποσοστό του συνόλου.</p>
<table><thead><tr><th>Περιφέρεια</th><th class="n">Ε.Δ.</th><th class="n">Περιοχές</th><th class="n">Χωρίς χάρτη</th>
<th class="n">Έδρα</th><th class="n">Κάλυψη</th></tr></thead><tbody>{tr}</tbody></table></main></body></html>""",
                                                                                          encoding="utf-8")
    ok = [r for r in rows if r.get("file")]
    print(f"\n{len(ok)}/{len(rows)} built; unmatched Ε.Δ.: {sum(r['unmatched'] for r in ok)}, "
          f"seat fallbacks: {sum(r['seat'] for r in ok)}, lowest coverage: "
          + ", ".join(f"{r['name']} {r['coverage']:.1%}" for r in sorted(ok, key=lambda r: r["coverage"])[:5]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    assert stems("Ε.Δ. ΠΙΚΕΡΝΙΟΥ") == stems("Πικέρνης,ο".split(",")[0]) == ("ΠΙΚΕΡΝ",)
    assert stems("1 Ε.Δ. ΑΘΗΝΑΙΩΝ") == ("ΑΘΙΝ",)
    assert stems("’ργους") == stems("Άργους")
    assert stems("(ΚΟΨΕΙΚΑ)") == stems("Κοψαίικα")
    assert stems("Ε.Δ. ΙΕΡΑΣ ΠΟΛΗΣ ΜΕΣΟΛΟΓΓΙΟΥ") == stems("Μεσολογγίου")
    assert stems("Ε.Δ. ΝΕΟΥ ΜΥΛΟΤΟΠΟΥ") == stems("Νέος Μυλότοπος") and stems("ΚΩΝ/ΝΟΥ") == stems("Κωνσταντίνου")
    assert one_edit("ΞΑΘΑΤ", "ΞΑΝΘΑΤ") and one_edit("ΚΑΛΟΓΡΕΑΝ", "ΚΑΛΟΓΡΙΑΝ") and not one_edit("ΚΑΛΟΓΡ", "ΚΑΛΑΓΡΙ")
    assert stems("Ε.Δ. ΧΩΤΟΥΣΑΣ") == stems("Χωτούσσα") and stems("Ε.Δ. ΒΛΙΣΙΔΙΑΣ") == stems("Βλησιδιά") and stems("(ΚΑΛΟΝΕΡΙ)") == stems("Καλονέριον")
    if sys.argv[2] == "all":
        build_all(sys.argv[1])
    else:
        main(sys.argv[1], int(sys.argv[2]))
