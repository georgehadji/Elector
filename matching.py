"""Name matching: ministry electoral districts (genitive, capitals) to ELSTAT 2021 communities.

The ministry writes "ΠΙΚΕΡΝΙΟΥ", ELSTAT "Πικέρνης": names are compared by word stems (norm -> stems),
with phonetic and one-letter fallbacks in find(). match_areas() places every electoral district
(Ε.Δ.) of a constituency in one community, through the community name or one of its settlements.
"""
import csv
import difflib
import functools
import json
import re
import unicodedata
from collections import defaultdict

from config import HERE

# Constituency names as the ministry site spells them, missing accents. Display only; matching uses norm().
EP_NAME_FIX = {"Αρτας": "Άρτας", "Ευβοιας": "Εύβοιας", "Βόρειου Τομέα": "Βορείου Τομέα", "Νότιου Τομέα": "Νοτίου Τομέα"}


def ep_label(name):
    for a, b in EP_NAME_FIX.items():
        name = name.replace(a, b)
    return re.sub(r"(?<=[Α-Ω\d])['’]", "΄", name)  # ordinal keraia: Α΄ Αθηνών, Β1΄, not an apostrophe

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


def _round(coords, digits=5):
    """Coordinates to `digits` decimals (5 = about 1 m): a third of the page size, no visible change."""
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], digits), round(coords[1], digits)]
    return [_round(c, digits) for c in coords]


@functools.cache
def boundaries():
    """ELSTAT 2021 municipal units, communities by KAL2022 code and settlements [(community code, name)].
    Loaded once per process; geometries rounded to 5 decimals."""
    def load(name):
        feats = json.loads((HERE / "data" / name).read_text(encoding="utf-8"))["features"]
        for f in feats:
            f["geometry"]["coordinates"] = _round(f["geometry"]["coordinates"])
        return feats
    units = load("dhm_enotites_2021.json")
    comm_by_code = {c["properties"]["KAL2022"]: c for c in load("koinotites_2021.json")}
    with open(HERE / "data" / "oikismoi_2021.csv", encoding="utf-8") as f:
        settlements = [(r["KALCODE"][:8], r["OIKISMOS"]) for r in csv.DictReader(f)]
    return units, comm_by_code, settlements


def match_areas(keys, parent):
    """keys: (den, ekd) pairs of one constituency; parent: (den, ekd) of a parenthesised settlement ->
    the Ε.Δ. before it. Returns ({(den, ekd): community code}, seat fallbacks); unmatched keys are absent."""
    units, comm_by_code, settlements = boundaries()
    unit_match = match_units({den for den, _ in keys}, units)
    inside_of, pool_of = {}, {}  # per municipal unit code

    def inside(ucode):
        if ucode not in inside_of:
            inside_of[ucode] = [c for code, c in comm_by_code.items() if code.startswith(ucode)]
        return inside_of[ucode]

    def pool(ucode):
        if ucode not in pool_of:
            pool_of[ucode] = [(k, code) for code, name in settlements if code.startswith(ucode)
                              for k in aliases(name) if code in comm_by_code]
        return pool_of[ucode]

    hit_of, seat_fallbacks = {}, 0
    # Parent Ε.Δ. first, so a parenthesised settlement can fall back on the parent's community.
    for den, ekd in sorted(keys, key=lambda k: (k[1].startswith("("), k)):
        hit = None
        unit = unit_match.get(den)
        if unit:
            ucode = unit["properties"]["CODE"]
            comm_index = [(k, c["properties"]["KAL2022"]) for c in inside(ucode) for k in aliases(label(c))]
            hit = find(ekd, comm_index)
            if hit is None:
                hit = find(ekd, pool(ucode))
                p = hit_of.get((den, parent.get((den, ekd))))
                if hit is None and p:  # same-name settlements in several communities (two Καστράκιον)
                    hit = find(ekd, [(k, code) for k, code in pool(ucode) if code == p])
            # Merged Ε.Δ. "Ε.Δ. ΣΙΒΙΣΤΑΣ-ΧΡΥΣΟΒΩΝ": the first name is the community seat.
            # Not settlements in parentheses: "(ΑΙ-ΓΙΑΝΝΗΣ)" is one name, and "ΑΙ" alone matches anything.
            if hit is None and "-" in ekd and ekd.startswith("Ε.Δ."):
                hit = find(ekd.split("-")[0], comm_index)
            renamed = re.search(r"\((.+)\)", ekd)
            if hit is None and renamed and not ekd.startswith("("):  # "Ε.Δ. ΦΙΛΙΠΠΟΥΠΟΛΗΣ (ΤΕΤΡΑΛΟΦΟΥ)": today's name
                hit = find(renamed.group(1), comm_index)
            if hit is None:  # loose spelling tests only after every strict one, so they never pre-empt an exact settlement
                hit = find(ekd, comm_index, loose=True) or find(ekd, pool(ucode), loose=True)
            if hit is None and hit_of.get((den, parent.get((den, ekd)))):
                # shortcut: a settlement ELSTAT does not list (Λαγκαδάκι) goes to its parent Ε.Δ.'s community.
                hit = hit_of[(den, parent[(den, ekd)])]
                seat_fallbacks += 1
                print(f"  assumed in parent community: {ekd} -> {label(comm_by_code[hit])}")
            if hit is None and len(inside(ucode)) == 1:
                hit = inside(ucode)[0]["properties"]["KAL2022"]  # single-community unit (e.g. Athens)
            if hit is None:
                # shortcut: a suburb missing from ELSTAT's lists is assumed to lie in the unit's
                # seat community (true for Alexandroupoli's suburbs); shown as "includes" on the map.
                seat = [c for c in inside(ucode) if stems(label(c)) == stems(den)]
                hit = seat[0]["properties"]["KAL2022"] if len(seat) == 1 else None
                if hit:
                    seat_fallbacks += 1
                    print(f"  assumed in seat community: {ekd} -> {label(seat[0])}")
        if hit is not None:
            hit_of[(den, ekd)] = hit
    return hit_of, seat_fallbacks
