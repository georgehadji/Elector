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
# Constituency names as the ministry site spells them, missing accents. Display only; matching uses norm().
EP_NAME_FIX = {"Αρτας": "Άρτας", "Ευβοιας": "Εύβοιας", "Βόρειου Τομέα": "Βορείου Τομέα", "Νότιου Τομέα": "Νοτίου Τομέα"}


def ep_label(name):
    for a, b in EP_NAME_FIX.items():
        name = name.replace(a, b)
    return re.sub(r"(?<=[Α-Ω\d])['’]", "΄", name)  # ordinal keraia: Α΄ Αθηνών, Β1΄, not an apostrophe

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

    ep_name = ep_label((q("SELECT name FROM ep WHERE election=? AND ep_id=?", ep) or [[str(ep)]])[0][0])
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


PARTY_SHORT = {"ΝΕΑ ΔΗΜΟΚΡΑΤΙΑ": "ΝΔ", "ΣΥΝΑΣΠΙΣΜΟΣ ΡΙΖΟΣΠΑΣΤΙΚΗΣ ΑΡΙΣΤΕΡΑΣ": "ΣΥΡΙΖΑ", "ΠΑΣΟΚ-Κίνημα Αλλαγής": "ΠΑΣΟΚ",
               "ΚΟΜΜΟΥΝΙΣΤΙΚΟ ΚΟΜΜΑ ΕΛΛΑΔΑΣ": "ΚΚΕ", "ΕΛΛΗΝΙΚΗ ΛΥΣΗ - ΚΥΡΙΑΚΟΣ ΒΕΛΟΠΟΥΛΟΣ": "Ελληνική Λύση"}
ELECTION_NAMES = {"2019": "2019", "2023/may": "Μάιος 2023", "2023/june": "Ιούνιος 2023", "2024/euro": "Ευρωεκλογές 2024"}
# A ballpoint cross, the mark a voter puts next to a candidate: the one decorative element of the site.
CROSS_SVG = ('<svg class="x" viewBox="0 0 40 40" aria-hidden="true"><path d="M7 8 C15 15 24 25 33 33"/>'
             '<path d="M32 7 C25 14 15 24 8 34"/></svg>')
INDEX_CSS = """
:root{color-scheme:light;--paper:#f6f7f9;--ink:#13233d;--ink-2:#55627a;--line:#dde2ea;--pen:#256abf;--wash:#eaf1fb}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--paper:#171c24;--ink:#e8edf5;--ink-2:#9aa6b8;--line:#2b3442;--pen:#6da7ec;--wash:#1f2a3a}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 "Fira Sans",system-ui,sans-serif}
main{max-width:1080px;margin:0 auto;padding:40px 24px 64px}
a{color:var(--pen)}
:focus-visible{outline:2px solid var(--pen);outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
h1{font:400 clamp(44px,9vw,84px)/1 "GFS Didot",Georgia,serif;letter-spacing:-.01em;margin:0;display:flex;align-items:center;gap:.18em}
h1 .x{width:.72em;height:.72em;flex:none}
h1 .x path{stroke-width:4.4}
.x path{fill:none;stroke:var(--pen);stroke-width:3.2;stroke-linecap:round}
h1 .x path{stroke-dasharray:40;stroke-dashoffset:40;animation:draw .35s ease-out forwards}
h1 .x path+path{animation-delay:.3s}
@keyframes draw{to{stroke-dashoffset:0}}
@media (prefers-reduced-motion:reduce){h1 .x path{animation:none;stroke-dashoffset:0}}
.lede{max-width:34em;margin:16px 0 28px;color:var(--ink-2);font-size:18px}
#f{width:100%;max-width:560px;font:inherit;font-size:19px;color:var(--ink);background:transparent;border:0;
   border-bottom:2px solid var(--ink);padding:10px 2px;border-radius:0}
#f::placeholder{color:var(--ink-2)}
#f:focus-visible{outline:none;border-bottom-color:var(--pen)}
#n{margin:10px 0 0;min-height:1.55em;color:var(--ink-2);font-size:14px}
.eps{list-style:none;margin:28px 0 0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));column-gap:36px}
.eps li{border-top:1px solid var(--line);padding:14px 0 16px}
.eps h2{font:400 23px/1.2 "GFS Didot",Georgia,serif;margin:0 0 6px}
.eps h2 a{color:inherit;text-decoration:none}
.eps h2 a:hover{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:4px}
.top{display:flex;gap:8px;align-items:baseline;margin:0 0 10px;font-size:14px;color:var(--ink-2);line-height:1.4}
.top .x{width:14px;height:14px;flex:none;align-self:center}
.top b{color:var(--ink);font-weight:600}
.jump{display:flex;flex-wrap:wrap;gap:4px 20px;margin:6px 0 0;font-size:14px}
.jump a{color:var(--ink-2);text-underline-offset:3px}
.el{display:flex;flex-wrap:wrap;align-items:center;gap:4px 14px;margin:0}
.el a{display:inline-flex;align-items:center;min-height:32px;color:var(--ink-2);font-size:14px;white-space:nowrap;
      text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
.el a:hover{color:var(--pen);text-decoration-color:var(--pen)}
.el a.now{padding:0 12px;border:1px solid var(--pen);border-radius:16px;color:var(--pen);background:var(--wash);
          text-decoration:none;font-weight:600}
.el a.now:hover{background:var(--pen);color:var(--paper)}
.dhm{margin:0 0 8px;color:var(--ink-2);font-size:13px;line-height:1.45}
.more{margin-top:56px;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:8px 36px}
.more section{border-top:2px solid var(--ink);padding-top:12px}
.more h2{font:400 24px/1.2 "GFS Didot",Georgia,serif;margin:0 0 6px}
.more p{color:var(--ink-2);margin:0 0 10px;font-size:15px}
.more ul{margin:0;padding:0;list-style:none}
.more li{padding:3px 0}
.more li span{color:var(--ink-2);font-size:14px}
footer{margin-top:48px;color:var(--ink-2);font-size:14px;max-width:40em}
@media (max-width:599px){main{padding:24px 16px 48px}.lede{font-size:16px}#f{font-size:17px}.eps{margin-top:16px}}
@media (pointer:coarse){.jump a{display:inline-block;padding:12px 0}.eps h2 a{display:inline-block;padding:9px 0}.el a{min-height:44px}.el a.now{padding:0 16px}.more li a{display:inline-block;padding:10px 0}}
"""
INDEX_JS = """
document.getElementById("s").hidden = false;
const fold = s => s.normalize("NFD").replace(/\\p{M}/gu, "").toUpperCase();
const LATIN = [["TH","Θ"],["CH","Χ"],["PS","Ψ"],["KS","Ξ"],["OU","ΟΥ"],["A","Α"],["B","Β"],["V","Β"],["G","Γ"],["D","Δ"],["E","Ε"],
  ["Z","Ζ"],["H","Η"],["I","Ι"],["K","Κ"],["C","Κ"],["L","Λ"],["M","Μ"],["N","Ν"],["X","Ξ"],["O","Ο"],["P","Π"],["R","Ρ"],
  ["S","Σ"],["T","Τ"],["Y","Υ"],["F","Φ"],["W","Ω"],["U","ΟΥ"]];
const greek = s => LATIN.reduce((t, [a, b]) => t.replaceAll(a, b), s);  // Greeklish: "patra" finds Πάτρα
// Case endings off (ministry names are genitive: Πατρέων, Ρόδου), then vowels that sound alike merged.
const stem = w => { const m = w.match(/^(.{2,}?)(ΕΩΝ|ΙΩΝ|ΕΩΣ|ΟΥΣ|ΟΥ|ΩΝ|ΟΣ|ΗΣ|ΑΣ|ΕΣ|ΩΣ|ΑΙ|ΟΙ|ΕΙ|Α|Η|Ο|Ι|Ε|Σ|Υ|Ω)$/); return m ? m[1] : w; };
const phon = w => w.replace(/ΕΙ|ΟΙ|Η|Υ/g, "Ι").replace(/ΑΙ/g, "Ε").replace(/Ω/g, "Ο");
const key = w => phon(stem(w));
const f = document.getElementById("f"), n = document.getElementById("n"), items = [...document.querySelectorAll(".eps li")];
const words = new Map(items.map(li => [li, li.dataset.k.split(" ").map(w => [w, key(w)])]));
const own = li => words.get(li).slice(0, +li.dataset.n);  // the constituency's own name, ahead of its towns
// A query word hits a place word that starts with it as typed, or shares its stem. Short stems must match
// whole, so "Ρόδος" (ΡΟΔ) finds Ρόδου but not Ροδόπης.
const hits = (ws, q) => { const k = key(q); return ws.some(([w, wk]) => w.startsWith(q) || wk === k || (k.length >= 4 && wk.startsWith(k))); };
f.addEventListener("input", () => {
  const qs = greek(fold(f.value.trim())).split(/[^\\p{L}\\d]+/u).filter(Boolean);
  let shown = 0;
  for (const li of items) {
    const hit = qs.every(q => hits(words.get(li), q)); li.hidden = !hit; shown += hit;
    li.style.order = hit && qs.length && !qs.every(q => hits(own(li), q)) ? 1 : "";  // name matches first
  }
  n.textContent = !qs.length ? "" : !shown ? `Καμία περιφέρεια με «${f.value.trim()}». Δοκίμασε το όνομα του δήμου ή του νομού.`
    : shown === 1 ? "1 περιφέρεια. Enter για τον πιο πρόσφατο χάρτη." : `${shown} περιφέρειες`;
});
f.addEventListener("keydown", e => {
  const shown = items.filter(li => !li.hidden).sort((a, b) => (+a.style.order || 0) - (+b.style.order || 0));
  if (e.key === "Enter" && f.value.trim() && (shown.length === 1 || +shown[1].style.order > +shown[0].style.order)) location.href = shown[0].querySelector("a.now").href;
});
"""


def write_index(order, nikh, elected):
    """out/index.html: a searchable list of constituencies, each with one link per election."""
    def fold(s):
        return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()

    # Municipalities (δήμοι) and municipal units of each constituency: search aliases, so a voter can type a town.
    dhm, den = defaultdict(dict), defaultdict(set)
    if DB.exists():
        with sqlite3.connect(DB) as con:
            for e, ep, d, u in con.execute("SELECT DISTINCT election, ep_id, dhm_descr, den_descr FROM station WHERE kind = 'Κ'"):
                dhm[e, ep][d] = None
                den[e, ep].add(u)
    top = {}
    if DB.exists():
        with sqlite3.connect(DB) as con:
            for ep, cand, party, votes in con.execute(
                    "SELECT e.name, c.name, p.name, MAX(t.votes) FROM ep_total t JOIN ep e USING(election, ep_id) "
                    "JOIN candidate c USING(election, ep_id, party_id, cand_id) JOIN party p USING(election, party_id) "
                    "WHERE t.election = '2023/may' AND t.cand_id > 0 GROUP BY t.ep_id"):
                top[ep_label(ep)] = (cand, PARTY_SHORT.get(party, party), votes)
    eps, tm = {}, []
    for f, m in order:
        if "_tm_" in f:
            tm.append((f, m))  # station maps exist for a few constituencies only: listed apart, not on the cards
        else:
            eps.setdefault(m["ep_name"], []).append((f, m))
    rank = list(ELECTION_NAMES)
    rows = []
    for name in sorted(eps, key=fold):
        links = sorted(eps[name], key=lambda fm: rank.index(fm[1]["election"]) if fm[1]["election"] in rank else -1)
        latest = links[-1][1]
        # The newest election is the default map; the others are quieter. The name in each link is for screen readers.
        chips = "".join(
            f'<a{" class=now" if i == 0 else ""} href="{urllib.parse.quote(f)}">'
            f'{ELECTION_NAMES.get(m["election"], m["election"])}<span class="sr">, {html.escape(name)}</span></a>'
            for i, (f, m) in enumerate(reversed(links)))
        towns = list(dhm[latest["election"], latest["ep"]])
        places = {w for _, m in links for p in (*dhm[m["election"], m["ep"]], *den[m["election"], m["ep"]])
                  for w in re.split(r"\W+", fold(p or ""))}
        own = [w for w in dict.fromkeys(re.split(r"\W+", fold(name))) if len(w) > 1]
        k = " ".join(dict.fromkeys((*own, *sorted(places))))
        # Attica's sectors are not places people know by name: list their municipalities.
        note = (f'<p class="dhm">Δήμοι {html.escape(", ".join(towns))}</p>'
                if re.search(r"Αθηνών|Πειραιώς|Αττικής", name) and len(towns) > 1 else "")
        t = top.get(name)
        # The cross marks the candidate with the most crosses: the one mark on the page that carries data.
        lead = (f'<p class="top">{CROSS_SVG}<span>Πρώτος σε σταυρούς τον Μάιο 2023: <b>{html.escape(t[0])}</b> '
                f'({html.escape(t[1])}), {f"{t[2]:,}".replace(",", ".")} σταυροί</span></p>' if t else "")
        rows.append(f'<li id="ep-{latest["ep"]}" data-k="{html.escape(k)}" data-n="{len(own)}">'
                    f'<h2><a href="#ep-{latest["ep"]}">{html.escape(name)}</a></h2>{lead}{note}<p class="el">{chips}</p></li>')
    nikh_rows = "".join(
        f'<li><a href="{urllib.parse.quote(f)}">{html.escape(m["ep_name"])}</a> <span>'
        f'{ELECTION_NAMES.get(m["election"], m["election"])}'
        f'{" · " + html.escape(elected[m["ep"]]) if m["election"] == "2023/june" and m["ep"] in elected else ""}</span></li>'
        for f, m in nikh)
    nikh_rows += "".join(f'<li><a href="{urllib.parse.quote(f)}">{html.escape(m["ep_name"])}</a> <span>{html.escape(m["label"])}</span></li>'
                         for f, m in tm if "_tm_131-" not in f)
    coverage = "".join(
        f'<li><a href="{q.name}">{ {"june": "Ιούνιος", "may": "Μάιος", "euro": "Ευρωεκλογές", "": "Βουλευτικές"}[q.stem[11:]]} {q.stem[6:10]}</a></li>'
        for q in sorted((HERE / "out").glob("index_*.html")))
    artifacts = "".join(f'<li><a href="{u}">{html.escape(n)}</a></li>' for n, u in PARTY_ARTIFACTS)
    (HERE / "out" / "index.html").write_text(f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Χάρτες σταυρών</title>
<meta name="description" content="Χάρτες αποτελεσμάτων των ελληνικών εκλογών ανά κοινότητα και εκλογικό τμήμα.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fira+Sans:wght@400;600&family=GFS+Didot&display=swap">
<style>{INDEX_CSS}</style></head><body><main>
<header>
<h1>{CROSS_SVG}Χάρτες σταυρών</h1>
<p class="lede">Πού ψήφισε κάθε κόμμα και κάθε υποψήφιος, ανά κοινότητα και ανά εκλογικό τμήμα, σε όλες τις εκλογικές περιφέρειες.</p>
<div id="s" hidden><label class="sr" for="f">Αναζήτηση περιφέρειας</label>
<input id="f" type="search" placeholder="Δήμος ή νομός, π.χ. Πάτρα, Αργολίδα" autocomplete="off">
<p id="n" aria-live="polite"></p></div>
<nav class="jump" aria-label="Άλλες ενότητες"><a href="#cov">Κάλυψη ανά νομό</a><a href="#tm">Ανά εκλογικό κατάστημα</a><a href="#party">Χάρτες ανά κόμμα</a></nav>
</header>
<ul class="eps">{"".join(rows)}</ul>
<div class="more">
<section id="cov"><h2>Κάλυψη ανά νομό</h2><p>Πόσοι σταυροί και ψήφοι φαίνονται στους χάρτες κάθε εκλογής.</p><ul>{coverage}</ul></section>
<section id="tm"><h2>Ανά εκλογικό κατάστημα</h2><p>ΝΙΚΗ: οι 9 περιφέρειες όπου εξέλεξε βουλευτή τον Ιούνιο του 2023.
<a href="NIKH_eklegmenoi_2023.html">Αναφορά Μαΐου–Ιουνίου</a>, <a href="../exports/NIKH_2023_ana_dhm_enotita.csv">CSV ανά δημοτική ενότητα</a>,
<a href="nikh_2023-2024.html">χάρτης όλης της χώρας: ποσοστά και μεταβολές 2019–2024</a>.</p><ul>{nikh_rows}</ul></section>
<section id="party"><h2>Χάρτες ανά κόμμα</h2><p>Στατικοί χάρτες στο claude.ai, ανοίγουν μόνο για όσους έχουν πρόσβαση.</p><ul>{artifacts}</ul></section>
</div>
<footer>Ανεπίσημα αποτελέσματα του Υπουργείου Εσωτερικών, ενωμένα με τα όρια κοινοτήτων της ΕΛΣΤΑΤ 2021.
Οι ψήφοι ετεροδημοτών και ειδικών τμημάτων δεν έχουν θέση στον χάρτη.</footer>
</main><script>{INDEX_JS}</script></body></html>""", encoding="utf-8")


def register(file, election, ep, ep_name, label):
    """Record a map in out/maps.json, rewrite out/index.html, and return links to the
    constituency's other maps (area map first) for the page's view switcher."""
    path = HERE / "out" / "maps.json"
    maps = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    maps[file] = {"election": election, "ep": ep, "ep_name": ep_label(ep_name), "label": label}
    for m in maps.values():  # entries written before a name fix
        m["ep_name"] = ep_label(m["ep_name"])
    path.write_text(json.dumps(maps, ensure_ascii=False, indent=1), encoding="utf-8")
    order = sorted(maps.items(), key=lambda kv: (kv[1]["election"], kv[1]["ep_name"], "_tm_" in kv[0], kv[1]["label"]))
    sys.path.insert(0, str(HERE))  # python -I drops the script dir
    from nikh_report import ELECTED  # lazy: nikh_report imports this module
    nikh = sorted((kv for kv in order if "_tm_131-" in kv[0]), key=lambda kv: (kv[1]["election"] != "2023/june", kv[1]["ep_name"]))
    write_index(order, nikh, ELECTED)
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
.n{{text-align:right}} p{{color:var(--ink-2)}} .wrap{{overflow-x:auto}}
@media (max-width:599px){{main{{padding:12px}} th,td{{padding:6px 4px}} th{{font-size:11px}} td{{font-size:13px}}}}
@media (pointer:coarse){{td a{{display:inline-block;padding:13px 0}}}}</style></head><body><main>
<h1 style="font-size:20px">Χάρτες σταυρών · {election}</h1>
<p>Ε.Δ.: εκλογικά διαμερίσματα · Περιοχές: κοινότητες στον χάρτη · Έδρα: διαμερίσματα που μπήκαν στην κοινότητα-έδρα
χωρίς αντιστοίχιση ονόματος · Κάλυψη: σταυροί στον χάρτη ως ποσοστό του συνόλου.</p>
<div class="wrap"><table><thead><tr><th>Περιφέρεια</th><th class="n">Ε.Δ.</th><th class="n">Περιοχές</th><th class="n">Χωρίς χάρτη</th>
<th class="n">Έδρα</th><th class="n">Κάλυψη</th></tr></thead><tbody>{tr}</tbody></table></div></main></body></html>""",
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
