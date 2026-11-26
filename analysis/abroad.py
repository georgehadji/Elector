"""Voters abroad and postal votes -> out/abroad.html, and the same tables as text on stdout (analysis/abroad.txt).

Abroad (May and June 2023): the stations of the constituency of voters abroad (ep 57), each placed by country and city
in table abroad (fetch.py), grouped by continent, country and city and compared with the whole country.
Postal votes (Euro 2024): the ministry publishes them only as constituency totals, stored by fetch.py as one station of
kind Τ per constituency; compared with the ballot boxes of the same constituency. Abroad, every vote in 2024 was postal.
"Registered" abroad and for postal votes is the list of those who applied, so valid / registered is close to turnout.

  python -I -X utf8 analysis/abroad.py data/stavroi.sqlite > analysis/abroad.txt
"""
import html
import json
import math
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import DB, ELECTION_NAMES, NIKH, OUT, PARTY_COLOR, PARTY_SHORT  # noqa: E402
from web import FONTS, common_css, fill, footer, header, meta, secure  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from party import RIVAL  # noqa: E402  (Ελληνική Λύση: the party ΝΙΚΗ is set against)

ABROAD = 57  # constituency of voters abroad
ABROAD_ELECTIONS = ("2023/may", "2023/june")  # the ones with stations abroad and a country for each
EURO = "2024/euro"
PAGE = OUT / "abroad.html"
MIN_SHARE = 2.0  # parties shown: at least this % of the whole country's valid votes, and ΝΙΚΗ

GEO = Path(__file__).resolve().parent.parent / "data" / "abroad_geo.json"  # "city|country" -> [lat, lon], from Nominatim
UA = "stavroi-map/0.1 (city geocoding; low volume)"

db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else DB)


def plain(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").strip()


# Cities the name search misses or gets wrong (another Washington, the country instead of the city): their Wikidata item.
PINNED = {"Ουάσιγκτον|ΗΠΑ": "Q61", "Λουξεμβούργο|Λουξεμβούργο": "Q1842", "Λουντβικσχάφεν|Γερμανία": "Q2910",
          "Κοπενγχάγη|Δανία": "Q1748", "Λωζάννη|Ελβετία": "Q807", "Λισσαβώνα|Πορτογαλία": "Q597", "Τάμπας|ΗΠΑ": "Q49255",
          "Σεούλ|Κορέα": "Q8684", "Κωνσταντινούπουλη|Τουρκία": "Q406", "Σίδνεϋ|Αυστραλία": "Q3130"}


def wikidata(**params):
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    for _ in range(6):
        time.sleep(3)  # slow and steady: anonymous clients are rate-limited
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(int(e.headers.get("retry-after") or 30) + 5)
    raise RuntimeError(f"Wikidata keeps refusing: {params}")


def coords():
    """{(city, country): (lat, lon)} for every city with stations abroad, cached in GEO. A missing city is searched on
    Wikidata by its Greek name; the first hit with coordinates (P625) whose country (P17), by its Greek label or an alias,
    is the ministry's country is kept. (The first 8 cities came from Nominatim, which then refused further requests.)"""
    cache = json.loads(GEO.read_text(encoding="utf-8")) if GEO.exists() else {}
    names = {}  # country item -> its Greek label and aliases, folded

    def country_names(qid):
        if qid not in names:
            e = wikidata(action="wbgetentities", ids=qid, props="labels|aliases", languages="el")["entities"][qid]
            names[qid] = {plain(e.get("labels", {}).get("el", {}).get("value", ""))} | {plain(a["value"]) for a in e.get("aliases", {}).get("el", [])}
        return names[qid]
    for city, country in db.execute("SELECT DISTINCT city, country FROM abroad"):
        key = f"{city.strip()}|{country}"
        if cache.get(key):
            continue
        if key in PINNED:
            e = wikidata(action="wbgetentities", ids=PINNED[key], props="claims|labels", languages="el|en")["entities"][PINNED[key]]
            v = e["claims"]["P625"][0]["mainsnak"]["datavalue"]["value"]
            cache[key] = [round(v["latitude"], 4), round(v["longitude"], 4)]
            print(f"pinned {key} = {PINNED[key]} {e['labels'].get('el', e['labels'].get('en'))['value']}: {cache[key]}", file=sys.stderr)
            GEO.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
            continue
        found = wikidata(action="wbsearchentities", search=city.strip(), language="el", uselang="el", type="item", limit=10)["search"]
        ents = wikidata(action="wbgetentities", ids="|".join(h["id"] for h in found), props="claims")["entities"] if found else {}
        cache[key] = None
        for h in found:
            c = ents[h["id"]].get("claims", {})
            where = [x["mainsnak"]["datavalue"]["value"] for x in c.get("P625", []) if "datavalue" in x["mainsnak"]]
            lands = [x["mainsnak"]["datavalue"]["value"]["id"] for x in c.get("P17", []) if "datavalue" in x["mainsnak"]]
            if where and any(plain(country) in country_names(q) for q in lands):
                cache[key] = [round(where[0]["latitude"], 4), round(where[0]["longitude"], 4)]
                break
        print(f"geocoded {key}: {cache[key]}", file=sys.stderr)
        GEO.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    return {tuple(k.split("|")): v for k, v in cache.items() if v}


def groups(e, key, where):
    """{group: {"n": stations, "reg": registered, "valid": valid votes, "votes": {party: votes}}} over the stations of
    election e matching where, grouped by key (SQL over station s and abroad a)."""
    src = "FROM station s LEFT JOIN abroad a ON a.election=s.election AND a.tm_id=s.tm_id"
    out = {g: {"n": n, "reg": r or 0, "valid": v or 0, "votes": {}} for g, n, r, v in db.execute(
        f"SELECT {key}, COUNT(*), SUM(s.registered), SUM(s.valid) {src} WHERE s.election=? AND {where} GROUP BY 1", (e,))}
    for g, pid, v in db.execute(f"SELECT {key}, p.party_id, SUM(p.votes) {src} JOIN party_votes p ON p.election=s.election "
                                f"AND p.tm_id=s.tm_id WHERE s.election=? AND {where} GROUP BY 1, 2", (e,)):
        out[g]["votes"][pid] = v
    return out


def total(e, where="1"):
    return groups(e, "'all'", where)["all"]


def name(e, pid):
    return PARTY_SHORT.get(pid) or db.execute("SELECT name FROM party WHERE election=? AND party_id=?", (e, pid)).fetchone()[0]


def shown(e):
    """Parties with at least MIN_SHARE % of the whole country, by votes, and ΝΙΚΗ."""
    t = total(e)
    return [p for p, v in sorted(t["votes"].items(), key=lambda x: -x[1]) if 100 * v / t["valid"] >= MIN_SHARE or p == NIKH]


def share(g, pid):
    return 100 * g["votes"].get(pid, 0) / g["valid"] if g["valid"] else 0


def first(e, g):
    return name(e, max(g["votes"], key=g["votes"].get)) if g["votes"] else "-"


def thousands(n):
    return f"{n:,}".replace(",", ".")


def num(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def signed(x):
    x = round(x, 1)  # no "−0,0"
    return ("+" if x > 0 else "−" if x < 0 else "±") + num(abs(x))


def table(head, rows):
    """An HTML table: head is a list of (label, numeric); rows hold already escaped cells."""
    th = "".join(f'<th scope="col"{" class=n" if n else ""}>{html.escape(h)}</th>' for h, n in head)
    tr = "".join("<tr>" + "".join(f'<td{" class=n" if n else ""}>{c}</td>' for c, (_, n) in zip(r, head, strict=True)) + "</tr>"
                 for r in rows)
    return f'<div class="wrap"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def text_table(head, rows):
    """The same table as plain text, for stdout."""
    cells = [[h for h, _ in head]] + [[html.unescape(re.sub(r"<[^>]+>", "", c)) for c in r] for r in rows]
    w = [max(len(r[i]) for r in cells) for i in range(len(head))]
    return "\n".join("  ".join(c.rjust(w[i]) if head[i][1] else c.ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in cells)


SECTIONS = []  # html of the page, in order; the text goes to stdout as it is made

def view(fn, *args, **attrs):
    """Run one section builder and wrap what it added in a <section class="view">; the script on the page shows one view at a time
    (without script every view stays open). v/vl: the view and its label, e/el: the election inside it and its label."""
    start = len(SECTIONS)
    fn(*args)
    a = " ".join(f'data-{k}="{html.escape(x, quote=True)}"' for k, x in attrs.items())
    SECTIONS[start:] = [f'<section class="view" {a}>{"".join(SECTIONS[start:])}</section>']


def emit(title, intro, head, rows, fold=True, chart=""):  # fold: kept for the callers; every table opens on demand
    """One table: printed, and added to the page under its heading. A chart of the same numbers goes between the heading
    and the table, outside the fold, so every table has a picture that is always visible and clearly its own."""
    print(f"\n{title}\n" + text_table(head, rows))
    # the section's h2 already names the election: the h3 drops that tail, and the two long titles get short ones
    short = {"Εξωτερικό: Ευρωεκλογές 2024 (επιστολική) και Ιούνιος 2023 (κάλπη)": "Εξωτερικό: επιστολική 2024 και κάλπη 2023",
             "ΝΙΚΗ στην επιστολική ψήφο ανά περιφέρεια, Ευρωεκλογές 2024": "ΝΙΚΗ ανά περιφέρεια, επιστολική 2024"}
    h = f"<h3>{html.escape(short.get(title) or re.sub(r', (?:Μάιος|Ιούνιος) 2023$|, Ευρωεκλογές 2024$', '', title))}</h3>"
    intro = f"<p>{intro}</p>" if intro else ""
    SECTIONS.append(f"{h}{chart}<details><summary>Ο πίνακας με τους αριθμούς</summary>{intro}{table(head, rows)}</details>")


def area_rows(e, gs, parties):
    """Rows of a table of areas (continents, countries, cities), most valid votes first: stations, registered, valid,
    valid / registered, first party and the shares of the parties shown."""
    return [[html.escape(str(g)), str(d["n"]), thousands(d["reg"]), thousands(d["valid"]),
             num(100 * d["valid"] / d["reg"]) + "%" if d["reg"] else "-", html.escape(first(e, d))]
            + [num(share(d, p)) for p in parties] for g, d in sorted(gs.items(), key=lambda x: -x[1]["valid"])]


def abroad_section(e):
    parties = shown(e)
    ab, nat = total(e, f"s.ep_id={ABROAD}"), total(e)
    countries, cities = db.execute("SELECT COUNT(DISTINCT country), COUNT(DISTINCT city || country) FROM abroad WHERE election=?",
                                   (e,)).fetchone()
    title = ELECTION_NAMES[e]
    print(f"\n=== Εξωτερικό, {title} ===")
    lead = (f"{ab['n']} εκλογικά τμήματα σε {countries} χώρες και {cities} πόλεις. Εγγεγραμμένοι {thousands(ab['reg'])}, "
            f"έγκυρα {thousands(ab['valid'])} ({num(100 * ab['valid'] / ab['reg'])}% των εγγεγραμμένων), "
            f"δηλαδή {num(100 * ab['valid'] / nat['valid'], 2)}% των εγκύρων όλης της χώρας.")
    print(lead)
    SECTIONS.append(f'<h2 id="ab-{e.replace("/", "-")}">Εξωτερικό · {html.escape(title)}</h2><p>{lead}</p>')
    ps = [p for p in sorted(ab["votes"], key=lambda p: -ab["votes"][p]) if p in parties or 100 * ab["votes"][p] / ab["valid"] >= MIN_SHARE]
    rows = [[html.escape(name(e, p)), num(share(ab, p)), num(share(nat, p)), signed(share(ab, p) - share(nat, p))] for p in ps]
    gap = lambda p: share(ab, p) - share(nat, p)
    hi, lo = max(ps, key=gap), min(ps, key=gap)
    pts = [(name(e, p), share(nat, p), share(ab, p)) for p in ps]
    emit(f"Κόμματα: εξωτερικό και όλη η χώρα, {title}", "Ποσοστό επί των εγκύρων· διαφορά σε ποσοστιαίες μονάδες.",
         [("Κόμμα", False), ("Εξωτερικό %", True), ("Όλη η χώρα %", True), ("Διαφορά", True)], rows,
         chart=chart_dumbbell(
             f"Στο εξωτερικό: {name(e, hi)} {signed(gap(hi))}, {name(e, lo)} {signed(gap(lo))} μονάδες",
             f"{title}. Ποσοστό κάθε κόμματος επί των εγκύρων, σε όλη τη χώρα και στο εξωτερικό.", pts, "Όλη η χώρα", "Εξωτερικό",
             f"Κόμματα, όλη η χώρα και εξωτερικό, {title}: " + "; ".join(f"{n}: {num(x)}% και {num(y)}%" for n, x, y in pts), sep=" · "))
    head = [("Τμήματα", True), ("Εγγεγραμμένοι", True), ("Έγκυρα", True), ("Έγκυρα / εγγ.", True), ("Πρώτο", False)]
    head += [(name(e, p) + " %", True) for p in parties]
    where = f"s.ep_id={ABROAD}"
    top5 = ps[:5]  # the five largest abroad; more party colours would repeat (ΝΔ and Ελληνική Λύση are both blue)
    gc = groups(e, "a.continent", where)
    emit(f"Ανά ήπειρο, {title}", "", [("Ήπειρος", False)] + head, area_rows(e, gc, parties),
         chart=chart_stack(f"Τι ψήφισε κάθε ήπειρος, {title}", "Τα πέντε μεγαλύτερα κόμματα του εξωτερικού, ποσοστό επί των εγκύρων· δίπλα τα έγκυρα.", e, top5,
                           sorted(gc.items(), key=lambda x: -x[1]["valid"])))
    gn = groups(e, "a.country", where)
    emit(f"Ανά χώρα, {title}", "Με σειρά εγκύρων. Σε χώρες με λίγες εκατοντάδες ψήφους λίγες ψήφοι αλλάζουν πολύ τα ποσοστά.",
         [("Χώρα", False)] + head, area_rows(e, gn, parties), fold=True,
         chart=chart_stack(f"Τι ψήφισαν οι 12 χώρες με τα περισσότερα έγκυρα, {title}",
                           "Τα πέντε μεγαλύτερα κόμματα του εξωτερικού, ποσοστό επί των εγκύρων· δίπλα τα έγκυρα. Όλες οι χώρες στον πίνακα που ακολουθεί.",
                           e, top5,
                           sorted(gn.items(), key=lambda x: -x[1]["valid"])[:12]))
    gt = groups(e, "a.city || ' (' || a.country || ')'", where)
    big = sorted(gt.items(), key=lambda x: -x[1]["valid"])[:15]
    turnout = lambda d: num(100 * d["valid"] / d["reg"]) + "%" if d["reg"] else "-"
    emit(f"Ανά πόλη, {title}", "", [("Πόλη (χώρα)", False)] + head, area_rows(e, gt, parties), fold=True,
         chart=chart_bars(f"Οι 15 πόλεις με τα περισσότερα έγκυρα, {title}",
                          "Δίπλα τα έγκυρα και πόσοι από τους εγγεγραμμένους ψήφισαν έγκυρα.",
                          [(g, d["valid"], f"{thousands(d['valid'])} · {turnout(d)}") for g, d in big],
                          f"Έγκυρα ανά πόλη, {title}: " + "; ".join(f"{g} {thousands(d['valid'])}" for g, d in big)))


def postal_section():
    parties = shown(EURO)
    post, box, nat = total(EURO, "s.kind='Τ'"), total(EURO, "s.kind<>'Τ'"), total(EURO)
    dom = total(EURO, f"s.kind='Τ' AND s.ep_id<>{ABROAD}")
    title = ELECTION_NAMES[EURO]
    print(f"\n=== Επιστολική ψήφος, {title} ===")
    lead = (f"Εγγεγραμμένοι στην επιστολική ψήφο {thousands(post['reg'])}, έγκυρα {thousands(post['valid'])} "
            f"({num(100 * post['valid'] / post['reg'])}% των εγγεγραμμένων), δηλαδή {num(100 * post['valid'] / nat['valid'], 2)}% "
            f"των εγκύρων όλης της χώρας. Από αυτά {thousands(dom['valid'])} στην Ελλάδα και "
            f"{thousands(post['valid'] - dom['valid'])} στο εξωτερικό, όπου όλη η ψήφος ήταν επιστολική. "
            "Το ΥΠΕΣ δίνει τις επιστολικές μόνο ως σύνολο ανά περιφέρεια.")
    print(lead)
    SECTIONS.append(f'<h2 id="postal">Επιστολική ψήφος · {html.escape(title)}</h2><p>{lead}</p>')
    rows = [[html.escape(name(EURO, p)), num(share(post, p)), num(share(dom, p)), num(share(box, p)),
             signed(share(dom, p) - share(box, p))] for p in parties]
    gap = lambda p: share(dom, p) - share(box, p)
    hi, lo = max(parties, key=gap), min(parties, key=gap)
    pts = [(name(EURO, p), share(box, p), share(dom, p)) for p in parties]
    emit(f"Κόμματα: επιστολική και κάλπη, {title}",
         "«Επιστολική στην Ελλάδα»: χωρίς το εξωτερικό. Διαφορά: της επιστολικής στην Ελλάδα από την κάλπη, σε μονάδες.",
         [("Κόμμα", False), ("Επιστολική %", True), ("Επιστολική στην Ελλάδα %", True), ("Κάλπη %", True), ("Διαφορά", True)], rows,
         chart=chart_dumbbell(f"Επιστολική έναντι κάλπης: {name(EURO, hi)} {signed(gap(hi))}, {name(EURO, lo)} {signed(gap(lo))} μονάδες",
                              f"{title}, μόνο στην Ελλάδα. Ποσοστό κάθε κόμματος επί των εγκύρων.", pts, "Κάλπη", "Επιστολική στην Ελλάδα",
                              "Κόμματα, κάλπη και επιστολική στην Ελλάδα: " + "; ".join(f"{n}: {num(x)}% και {num(y)}%" for n, x, y in pts),
                              sep=" · "))
    june, ab = total("2023/june", f"s.ep_id={ABROAD}"), total(EURO, f"s.ep_id={ABROAD}")
    rows = [[html.escape(name(EURO, p)), num(share(ab, p)), num(share(june, p)) if p in june["votes"] else "-"] for p in parties]
    pts = [(name(EURO, p), share(june, p), share(ab, p)) for p in parties if p in june["votes"]]
    emit("Εξωτερικό: Ευρωεκλογές 2024 (επιστολική) και Ιούνιος 2023 (κάλπη)",
         f"Δύο διαφορετικές αναμετρήσεις, με {thousands(ab['valid'])} και {thousands(june['valid'])} έγκυρα. "
         "Για το 2024 το ΥΠΕΣ δεν δίνει κατανομή ανά χώρα.",
         [("Κόμμα", False), ("Εξωτερικό 2024 %", True), ("Εξωτερικό Ιούνιος 2023 %", True)], rows,
         chart=chart_dumbbell("Το εξωτερικό σε δύο αναμετρήσεις", "Ποσοστό επί των εγκύρων· κόμματα που κατέβηκαν και στις δύο.", pts,
                              "Ιούνιος 2023 (κάλπη)", "Ευρωεκλογές 2024 (επιστολική)",
                              "Εξωτερικό, Ιούνιος 2023 και Ευρωεκλογές 2024: " + "; ".join(f"{n}: {num(x)}% και {num(y)}%" for n, x, y in pts),
                              sep=" · "))
    names = dict(db.execute("SELECT ep_id, name FROM ep WHERE election=?", (EURO,)))
    pb, bb = groups(EURO, "s.ep_id", "s.kind='Τ'"), groups(EURO, "s.ep_id", "s.kind<>'Τ'")
    rows = [[html.escape(names[ep]), thousands(d["reg"]), thousands(d["valid"]), num(100 * d["valid"] / (d["valid"] + bb[ep]["valid"])) + "%"]
            + [f"{num(share(d, p))} ({signed(share(d, p) - share(bb[ep], p))})" for p in parties]
            for ep, d in sorted(pb.items(), key=lambda x: -x[1]["valid"]) if ep != ABROAD]
    ratio = {ep: 100 * d["valid"] / (d["valid"] + bb[ep]["valid"]) for ep, d in pb.items() if ep != ABROAD}
    order = sorted(ratio, key=lambda ep: -ratio[ep])
    emit(f"Ανά περιφέρεια, {title}",
         "Για κάθε κόμμα: ποσοστό στην επιστολική και, σε παρένθεση, η διαφορά από την κάλπη της ίδιας περιφέρειας, σε μονάδες.",
         [("Περιφέρεια", False), ("Εγγεγραμμένοι", True), ("Έγκυρα", True), ("% των εγκύρων", True)]
         + [(name(EURO, p) + " %", True) for p in parties], rows, fold=True,
         chart=chart_bars(f"Πού ψήφισαν περισσότερο επιστολικά: {names[order[0]]}, {num(ratio[order[0]])}% των εγκύρων",
                          f"Οι 15 περιφέρειες με το μεγαλύτερο μερίδιο επιστολικών στα έγκυρα· το μικρότερο: {html.escape(names[order[-1]])}, "
                          f"{num(ratio[order[-1]])}%.", [(names[ep], ratio[ep], num(ratio[ep]) + "%") for ep in order[:15]],
                          "Μερίδιο επιστολικών στα έγκυρα ανά περιφέρεια: " + "; ".join(f"{names[ep]} {num(ratio[ep])}%" for ep in order[:15])))


# Charts, drawn here as HTML and inline SVG (no script): one purple hue from the map ramp, two shades for a dumbbell.
# Each repeats a table of the page, which stays the accessible view of the same numbers.
def figure(title, note, body, label):
    return (f'<figure class="ch" role="img" aria-label="{html.escape(label, quote=True)}"><figcaption><b>{html.escape(title)}</b>'
            f'{f"<br>{note}" if note else ""}</figcaption>{body}</figure>')


def chart_bars(title, note, rows, label):
    """Ranked horizontal bars: rows = [(name, value, text beside the bar)], largest first."""
    top = max(v for _, v, _ in rows) or 1
    body = "".join(f'<div class="cr"><span class="cl">{html.escape(n)}</span><span class="cb"><i style="width:{100 * v / top:.1f}%">'
                   f'</i></span><span class="cv">{t}</span></div>' for n, v, t in rows)
    return figure(title, note, body, label)


def chart_dumbbell(title, note, rows, a, b, label, unit="%", sep=" → "):
    """One row per item, two dots on a shared 0..max axis: rows = [(name, value a, value b)]; a is the lighter dot."""
    top = math.ceil(max(max(x, y) for _, x, y in rows) * 1.05) or 1  # a round end, so the end label is exact
    pos = lambda v: f"{100 * v / top:.1f}%"
    key = f'<p class="ck"><span><i class="a"></i>{html.escape(a)}</span><span><i class="b"></i>{html.escape(b)}</span></p>'
    body = "".join(
        f'<div class="cr"><span class="cl">{html.escape(n)}</span><span class="cd"><i class="ln" style="left:{pos(min(x, y))};'
        f'width:{100 * abs(x - y) / top:.1f}%"></i><i class="a" style="left:{pos(x)}"></i><i class="b" style="left:{pos(y)}"></i></span>'
        f'<span class="cv">{num(x)}{sep}{num(y)}{unit}</span></div>' for n, x, y in rows)
    scale = f'<div class="cr cs"><span></span><span class="cd0"><span>0{unit}</span><span>{num(top, 0)}{unit}</span></span><span></span></div>'
    return figure(title, note, key + body + scale, label)


def chart_scatter(title, note, pts, xlab, ylab, label, marked=(), tip=("κάλπη", "επιστολική")):
    """Scatter of (name, x, y) in % with the line y = x; points in `marked` carry their name."""
    W, H, L, B, T, R = 360, 300, 38, 34, 10, 12  # size and margins
    top = max(max(x, y) for _, x, y in pts)
    top = int(top) + 1
    sx = lambda v: L + (W - L - R) * v / top
    sy = lambda v: H - B - (H - B - T) * v / top
    step = 1 if top <= 6 else 2
    grid = "".join(f'<line class="g" x1="{L}" x2="{W - R}" y1="{sy(v):.1f}" y2="{sy(v):.1f}"/><line class="g" y1="{T}" y2="{H - B}" '
                   f'x1="{sx(v):.1f}" x2="{sx(v):.1f}"/><text x="{L - 6}" y="{sy(v) + 4:.1f}" text-anchor="end">{v}</text>'
                   f'<text x="{sx(v):.1f}" y="{H - B + 15}" text-anchor="middle">{v}</text>' for v in range(0, top + 1, step))
    diag = f'<line class="d" x1="{sx(0)}" y1="{sy(0)}" x2="{sx(top):.1f}" y2="{sy(top):.1f}"/>'
    dots = "".join(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4.5"{" class=m" if n in marked else ""}><title>{html.escape(n)}: '
                   f'{num(y)}% {tip[1]}, {num(x)}% {tip[0]}</title></circle>' for n, x, y in pts)
    names = "".join(f'<text class="n" x="{sx(x) + (-7 if x > top * .7 else 7):.1f}" y="{sy(y) + 4:.1f}"'  # right part: name on the left
                    f'{" text-anchor=end" if x > top * .7 else ""}>{html.escape(n)}</text>' for n, x, y in pts if n in marked)
    axes = (f'<text x="{(L + W - R) / 2}" y="{H - 4}" text-anchor="middle">{html.escape(xlab)}</text>'
            f'<text transform="translate(11 {(T + H - B) / 2}) rotate(-90)" text-anchor="middle">{html.escape(ylab)}</text>'
            f'<text class="n" x="{sx(top * .62):.1f}" y="{sy(top * .62) - 8:.1f}" text-anchor="end">ίδιο ποσοστό</text>')
    return figure(title, note, f'<svg class="sc" viewBox="0 0 {W} {H}" aria-hidden="true">{grid}{diag}{dots}{names}{axes}</svg>', label)


def color(e, p):
    """Map colour of party p: config.PARTY_COLOR, else the ministry's (stored as 0xRRGGBB), else grey."""
    c = PARTY_COLOR.get(p)
    if not c:
        c = db.execute("SELECT color FROM party WHERE election=? AND party_id=?", (e, p)).fetchone()[0]
        c = "#" + c[2:] if c else "#888"
    return c


def chart_stack(title, note, e, parties, rows):
    """One 100% bar per area, the share of each party shown in its own colour and the rest as «Λοιπά»; rows = [(name, group)]."""
    key = "".join(f'<span><i style="background:{color(e, p)}"></i>{html.escape(name(e, p))}</span>' for p in parties)
    key = f'<p class="ck">{key}<span><i class="o"></i>Λοιπά</span></p>'
    body = ""
    for g, d in rows:
        seg = [(name(e, p), share(d, p), color(e, p)) for p in parties]
        rest = max(0, 100 - sum(s for _, s, _ in seg))
        bar = "".join(f'<i style="width:{s:.2f}%;background:{c}" title="{html.escape(n)}: {num(s)}%"></i>' for n, s, c in seg if s)
        body += (f'<div class="cr"><span class="cl">{html.escape(str(g))}</span><span class="cst">{bar}'
                 f'<i class="o" style="width:{rest:.2f}%" title="Λοιπά: {num(rest)}%"></i></span>'
                 f'<span class="cv">{thousands(d["valid"])}</span></div>')
    label = f"{title}: " + "; ".join(f"{g}: " + ", ".join(f"{name(e, p)} {num(share(d, p))}%" for p in parties) for g, d in rows)
    return figure(title, note, key + body, label)


def chart_strip(title, note, pts, label, refs, marked=(), dec=2):
    """One dot per item on a shared axis from 0, dots stacked where they would overlap; refs = [(value, text)] are dashed
    reference lines; items in `marked` carry their name."""
    W, L, R, B, r = 400, 14, 14, 30, 5
    T = 14 + 13 * len(refs)  # room for the reference labels above the tallest stack
    top = math.ceil(max(v for _, v in pts) * 4) / 4
    sx = lambda v: L + (W - L - R) * v / top
    step, height = 2 * r + 1, {}
    placed = []
    for n, v in sorted(pts, key=lambda q: q[1]):
        k = round(sx(v) / step)
        h = height.get(k, 0)
        height[k] = h + 1
        placed.append((n, v, k * step, h))
    H = T + B + max(height.values()) * step
    base = H - B
    ticks = "".join(f'<line class="g" x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{base}" y2="{base + 5}"/>'
                    f'<text x="{sx(t):.1f}" y="{base + 18}" text-anchor="middle">{num(t, 2)}</text>'
                    for t in [i / 4 for i in range(int(top * 4) + 1)])
    lines = "".join(f'<line class="d" x1="{sx(v):.1f}" x2="{sx(v):.1f}" y1="{14 + 13 * i}" y2="{base}"/>'
                    f'<text class="n" x="{sx(v) + (-4 if sx(v) > W / 2 else 4):.1f}" y="{12 + 13 * i}"{" text-anchor=end" if sx(v) > W / 2 else ""}>'
                    f'{html.escape(t)}</text>' for i, (v, t) in enumerate(refs))
    dots = "".join(f'<circle cx="{x}" cy="{base - r - 1 - h * step}" r="{r}"{" class=m" if n in marked else ""}>'
                   f'<title>{html.escape(n)}: {num(v, dec)}</title></circle>' for n, v, x, h in placed)
    side = lambda x: "end" if x > W * .8 else "start" if x < W * .2 else "middle"  # name above its dot, kept inside the box
    names = "".join(f'<text class="n" x="{x}" y="{base - 2 * r - 5 - h * step}" text-anchor="{side(x)}">{html.escape(n)}</text>'
                    for n, v, x, h in placed if n in marked)
    axis = f'<line class="g" x1="{L}" x2="{W - R}" y1="{base}" y2="{base}"/>'
    return figure(title, note, f'<svg class="sc st" viewBox="0 0 {W} {H}" aria-hidden="true">{axis}{ticks}{lines}{dots}{names}</svg>', label)


CHART_CSS = """
.ch{margin:1.2em 0 1.8em;max-width:760px} .ch figcaption{margin-bottom:.6em;color:var(--ink-2)} .ch figcaption b{color:var(--ink)}
.cr{display:grid;grid-template-columns:minmax(7em,11em) 1fr minmax(4.5em,auto);gap:.7em;align-items:center;min-height:30px}
.cl{font-size:16px;overflow-wrap:anywhere} .cv{font-size:15px;color:var(--ink-2);font-variant-numeric:tabular-nums;white-space:nowrap}
.cb{height:14px} .cb i{display:block;height:100%;min-width:2px;background:var(--s5);border-radius:0 4px 4px 0}
.cd{position:relative;height:1px;background:var(--line)} .cd i{position:absolute;top:50%;width:11px;height:11px;border-radius:50%;
  transform:translate(-50%,-50%);box-shadow:0 0 0 2px var(--surface)} .cd i.ln{height:3px;border-radius:0;transform:translateY(-50%);
  box-shadow:none;background:var(--s2)}
.ch i.a{background:var(--s2)} .ch i.b{background:var(--s6)}
.ck{display:flex;gap:1.2em;font-size:15px;margin:.2em 0 .5em} .ck i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}
.cs .cd0{display:flex;justify-content:space-between;font-size:15px;color:var(--ink-2)}
.cst{display:flex;height:16px} .cst i{display:block;height:100%;border-right:2px solid var(--surface)}
.cst i:first-child{border-radius:4px 0 0 4px} .cst i:last-child{border-right:0;border-radius:0 4px 4px 0}
.ch i.o{background:color-mix(in srgb,var(--ink-2) 30%,transparent)} .ck{flex-wrap:wrap;gap:.3em 1.2em}
.sc{width:100%;max-width:520px;height:auto} .sc.st{max-width:600px} .sc text{fill:var(--ink-2);font-size:13px} .sc text.n{fill:var(--ink)}
.sc .g{stroke:var(--line);stroke-width:1} .sc .d{stroke:var(--ink-2);stroke-dasharray:4 3}
.sc circle{fill:var(--s4);stroke:var(--surface);stroke-width:1.5} .sc circle.m{fill:var(--s6)}
"""


def rank(g, pid):
    """Place of party pid among the parties of group g, by votes (1 = first); "-" without votes."""
    mine = g["votes"].get(pid, 0)
    return 1 + sum(v > mine for v in g["votes"].values()) if mine else "-"


def nikh_section():
    """ΝΙΚΗ in detail: abroad by country and city in both 2023 elections, and the 2024 postal vote by constituency."""
    print("\n=== ΝΙΚΗ: αναλυτικά ===")
    may, june = ABROAD_ELECTIONS
    ab = {e: total(e, f"s.ep_id={ABROAD}") for e in ABROAD_ELECTIONS}
    nat = {e: total(e) for e in ABROAD_ELECTIONS}
    cn = {e: groups(e, "a.country", f"s.ep_id={ABROAD}") for e in ABROAD_ELECTIONS}
    ct = {e: groups(e, "a.city || ' (' || a.country || ')'", f"s.ep_id={ABROAD}") for e in ABROAD_ELECTIONS}
    top3 = sorted(cn[june].values(), key=lambda d: -d["votes"].get(NIKH, 0))[:3]
    lead = (f"Στο εξωτερικό η ΝΙΚΗ πήρε {ab[may]['votes'].get(NIKH, 0)} ψήφους τον Μάιο ({num(share(ab[may], NIKH))}%, "
            f"{rank(ab[may], NIKH)}ο κόμμα· σε όλη τη χώρα {num(share(nat[may], NIKH))}%, {rank(nat[may], NIKH)}ο) και "
            f"{ab[june]['votes'].get(NIKH, 0)} τον Ιούνιο ({num(share(ab[june], NIKH))}%, {rank(ab[june], NIKH)}ο κόμμα· σε όλη τη χώρα "
            f"{num(share(nat[june], NIKH))}%, {rank(nat[june], NIKH)}ο). Οι τρεις χώρες με τις περισσότερες ψήφους της τον Ιούνιο "
            f"έδωσαν το {num(100 * sum(d['votes'].get(NIKH, 0) for d in top3) / ab[june]['votes'][NIKH], 0)}% των ψήφων της στο εξωτερικό.")
    print(lead)
    SECTIONS.append(f'<h2 id="nikh">ΝΙΚΗ: αναλυτικά</h2><p>{lead}</p>')
    e24, ab24 = total(EURO), total(EURO, f"s.ep_id={ABROAD}")
    rows = [(ELECTION_NAMES[e], share(nat[e], NIKH), share(ab[e], NIKH)) for e in ABROAD_ELECTIONS]
    rows.append((ELECTION_NAMES[EURO], share(e24, NIKH), share(ab24, NIKH)))
    SECTIONS.append(chart_dumbbell(
        "Η ΝΙΚΗ πάει χειρότερα στο εξωτερικό απ' ό,τι σε όλη τη χώρα", "Ποσοστό επί των εγκύρων. Στις Ευρωεκλογές 2024 όλη η ψήφος του εξωτερικού ήταν επιστολική.", rows,
        "Όλη η χώρα", "Εξωτερικό", sep=" · ", label="Ποσοστό ΝΙΚΗΣ, όλη η χώρα και εξωτερικό: "
        + "; ".join(f"{n}: {num(x)}% και {num(y)}%" for n, x, y in rows)))
    country_charts = []  # the pictures of the «ΝΙΚΗ ανά χώρα» table: they sit under its heading
    jv = sorted(((g, d) for g, d in cn[june].items() if d["votes"].get(NIKH)), key=lambda x: -x[1]["votes"][NIKH])[:12]
    country_charts.append(chart_bars(
        "Ψήφοι της ΝΙΚΗΣ ανά χώρα, Ιούνιος 2023", "Οι 12 χώρες με τις περισσότερες ψήφους της· δίπλα το ποσοστό της εκεί.",
        [(g, d["votes"][NIKH], f"{d['votes'][NIKH]} · {num(share(d, NIKH))}%") for g, d in jv],
        "Ψήφοι ΝΙΚΗΣ ανά χώρα, Ιούνιος 2023: " + "; ".join(f"{g} {d['votes'][NIKH]}" for g, d in jv)))
    big = sorted((g for g, d in cn[june].items() if d["valid"] >= 500 and g in cn[may]), key=lambda g: -share(cn[june][g], NIKH))
    rows = [(g, share(cn[may][g], NIKH), share(cn[june][g], NIKH)) for g in big]
    country_charts.append(chart_dumbbell(
        "Από τον Μάιο στον Ιούνιο: η ΝΙΚΗ ανέβηκε σχεδόν παντού", "Χώρες με 500 έγκυρα και πάνω τον Ιούνιο.", rows,
        "Μάιος 2023", "Ιούνιος 2023", "Ποσοστό ΝΙΚΗΣ ανά χώρα, Μάιος και Ιούνιος 2023: "
        + "; ".join(f"{g}: {num(x)}% και {num(y)}%" for g, x, y in rows)))

    co = {e: groups(e, "a.continent", f"s.ep_id={ABROAD}") for e in ABROAD_ELECTIONS}
    rows = [(g, share(co[may][g], NIKH), share(co[june][g], NIKH)) for g in sorted(co[june], key=lambda g: -co[june][g]["valid"])
            if g in co[may]]
    print("ΝΙΚΗ ανά ήπειρο (Μάιος → Ιούνιος): " + "; ".join(f"{g} {num(x)} → {num(y)}% ({co[june][g]['votes'].get(NIKH, 0)} ψήφοι, "
                                                       f"{thousands(co[june][g]['valid'])} έγκυρα)" for g, x, y in rows))
    SECTIONS.append(chart_dumbbell(
        "Η ΝΙΚΗ ανά ήπειρο", "Ποσοστό επί των εγκύρων. Έγκυρα τον Ιούνιο: "
        + ", ".join(f"{html.escape(g)} {thousands(co[june][g]['valid'])}" for g, _, _ in rows) + "· έξω από την Ευρώπη λίγες ψήφοι "
        "αλλάζουν πολύ το ποσοστό.", rows, "Μάιος 2023", "Ιούνιος 2023",
        "Ποσοστό ΝΙΚΗΣ ανά ήπειρο, Μάιος και Ιούνιος 2023: " + "; ".join(f"{g}: {num(x)}% και {num(y)}%" for g, x, y in rows)))

    nv, vv = ab[june]["votes"][NIKH], ab[june]["valid"]
    top10 = sorted(cn[june].items(), key=lambda x: -x[1]["votes"].get(NIKH, 0))[:10]
    rows = [(g, 100 * d["valid"] / vv, 100 * d["votes"].get(NIKH, 0) / nv) for g, d in top10]
    over = max(rows, key=lambda r: r[2] - r[1])  # in points: a ratio would pick a country with a handful of votes
    print("Μερίδιο στα έγκυρα του εξωτερικού → μερίδιο στις ψήφους της ΝΙΚΗΣ εκεί, Ιούνιος 2023: "
          + "; ".join(f"{g} {num(x)} → {num(y)}%" for g, x, y in rows))
    country_charts.append(chart_dumbbell(
        f"{over[0]}: {num(over[1])}% των εγκύρων του εξωτερικού, {num(over[2])}% των ψήφων της ΝΙΚΗΣ",
        "Ιούνιος 2023, οι 10 χώρες με τις περισσότερες ψήφους της. Όπου το μερίδιο στις ψήφους της ΝΙΚΗΣ είναι μεγαλύτερο, η χώρα "
        "της δίνει περισσότερα απ' όσο της αναλογεί σε έγκυρα.", rows, "Μερίδιο στα έγκυρα του εξωτερικού", "Μερίδιο στις ψήφους της ΝΙΚΗΣ",
        "Μερίδιο κάθε χώρας στα έγκυρα του εξωτερικού και στις ψήφους της ΝΙΚΗΣ, Ιούνιος 2023: "
        + "; ".join(f"{g}: {num(x)}% και {num(y)}%" for g, x, y in rows), sep=" · "))

    rv = name(june, RIVAL)
    pts = [(g, share(d, RIVAL), share(d, NIKH)) for g, d in cn[june].items() if d["valid"] >= 300]
    ahead = sum(y > x for _, x, y in pts)
    print(f"ΝΙΚΗ και {rv} ανά χώρα (300 έγκυρα και πάνω), Ιούνιος 2023: ΝΙΚΗ πάνω σε {ahead} από τις {len(pts)}; "
          + "; ".join(f"{g} {num(y)} / {num(x)}%" for g, x, y in sorted(pts, key=lambda q: -q[2])))
    country_charts.append(chart_scatter(
        f"ΝΙΚΗ και {rv} στο εξωτερικό: η ΝΙΚΗ πάνω σε {ahead} από τις {len(pts)} χώρες",
        f"Ιούνιος 2023, χώρες με 300 έγκυρα και πάνω· κάθε κουκκίδα μια χώρα. Πάνω από τη διαγώνιο: η ΝΙΚΗ πήρε περισσότερο από την {rv}.",
        pts, f"{rv} (%)", "ΝΙΚΗ (%)", f"Ποσοστό ΝΙΚΗΣ και {rv} ανά χώρα, Ιούνιος 2023: "
        + "; ".join(f"{g}: {num(y)}% και {num(x)}%" for g, x, y in pts),
        {max(pts, key=lambda q: q[2])[0], max(pts, key=lambda q: q[1])[0]}, tip=(rv, "ΝΙΚΗ")))

    def area(by, label, title, fold, chart=""):
        keys = sorted(set(by[may]) | set(by[june]), key=lambda g: (-by[june].get(g, {"votes": {}})["votes"].get(NIKH, 0), str(g)))
        rows = []
        for g in keys:
            m, j = by[may].get(g), by[june].get(g)
            cell = lambda d: [str(d["votes"].get(NIKH, 0)), num(share(d, NIKH)), str(rank(d, NIKH)), thousands(d["valid"])] if d else ["-"] * 4
            rows.append([html.escape(str(g))] + cell(m) + cell(j)
                        + [signed(share(j, NIKH) - share(m, NIKH)) if m and j else "-"])
        emit(title, "Θέση: η σειρά της ΝΙΚΗΣ ανάμεσα στα κόμματα εκεί. Με λίγα έγκυρα, μία-δύο ψήφοι αλλάζουν πολύ το ποσοστό.",
             [(label, False), ("Μάιος ψήφοι", True), ("Μάιος %", True), ("Μάιος θέση", True), ("Μάιος έγκυρα", True),
              ("Ιούνιος ψήφοι", True), ("Ιούνιος %", True), ("Ιούνιος θέση", True), ("Ιούνιος έγκυρα", True), ("Μεταβολή", True)],
             rows, fold=fold, chart=chart)
    area(cn, "Χώρα", "ΝΙΚΗ ανά χώρα, Μάιος και Ιούνιος 2023", False, "".join(country_charts))
    jt = sorted(((g, d) for g, d in ct[june].items() if d["votes"].get(NIKH)), key=lambda x: -x[1]["votes"][NIKH])[:12]
    area(ct, "Πόλη (χώρα)", "ΝΙΚΗ ανά πόλη, Μάιος και Ιούνιος 2023", True, chart_bars(
        "Ψήφοι της ΝΙΚΗΣ ανά πόλη, Ιούνιος 2023", "Οι 12 πόλεις με τις περισσότερες ψήφους της· δίπλα το ποσοστό της εκεί.",
        [(g, d["votes"][NIKH], f"{d['votes'][NIKH]} · {num(share(d, NIKH))}%") for g, d in jt],
        "Ψήφοι ΝΙΚΗΣ ανά πόλη, Ιούνιος 2023: " + "; ".join(f"{g} {d['votes'][NIKH]}" for g, d in jt)))

    post, box = groups(EURO, "s.ep_id", "s.kind='Τ'"), groups(EURO, "s.ep_id", "s.kind<>'Τ'")
    names = dict(db.execute("SELECT ep_id, name FROM ep WHERE election=?", (EURO,)))
    tp, tb = total(EURO, "s.kind='Τ'"), total(EURO, "s.kind<>'Τ'")
    n_all = tp["votes"][NIKH] + tb["votes"][NIKH]
    # propensity: the share of ΝΙΚΗ's own votes that came by post, over the share of all valid votes that did
    prop = (tp["votes"][NIKH] / n_all) / (tp["valid"] / (tp["valid"] + tb["valid"]))
    lead = (f"Ευρωεκλογές 2024: από τις {thousands(n_all)} ψήφους της ΝΙΚΗΣ, {thousands(tp['votes'][NIKH])} ήταν επιστολικές "
            f"({num(100 * tp['votes'][NIKH] / n_all)}%), ενώ από όλα τα έγκυρα επιστολικά ήταν το "
            f"{num(100 * tp['valid'] / (tp['valid'] + tb['valid']))}%. Ο ψηφοφόρος της ΝΙΚΗΣ ψήφισε επιστολικά "
            f"{num(prop, 2)} φορές όσο ο μέσος ψηφοφόρος. Στο εξωτερικό, όπου ψήφισαν όλοι επιστολικά, πήρε "
            f"{post[ABROAD]['votes'].get(NIKH, 0)} ψήφους ({num(share(post[ABROAD], NIKH))}%), έναντι "
            f"{ab[june]['votes'][NIKH]} στις κάλπες του εξωτερικού τον Ιούνιο 2023.")
    print(lead)
    SECTIONS.append(f"<p>{lead}</p>")
    pts = [(names[ep], share(box[ep], NIKH), share(post[ep], NIKH)) for ep in post if ep != ABROAD]
    gaps = sorted(pts, key=lambda p: p[2] - p[1])
    marked = {gaps[0][0], gaps[-1][0], max(pts, key=lambda p: p[1])[0]}
    below = sum(y < x for _, x, y in pts)
    SECTIONS.append(chart_scatter(
        f"Επιστολική και κάλπη: η ΝΙΚΗ κάτω από τη γραμμή σε {below} από τις {len(pts)} περιφέρειες",
        "Κάθε κουκκίδα μια περιφέρεια, Ευρωεκλογές 2024. Κάτω από τη διαγώνιο: μικρότερο ποσοστό στην επιστολική απ' ό,τι στην κάλπη.",
        pts, "Κάλπη (%)", "Επιστολική (%)", f"Ποσοστό ΝΙΚΗΣ στην επιστολική και στην κάλπη ανά περιφέρεια: χαμηλότερο στην επιστολική σε "
        f"{below} από τις {len(pts)}. Τα ίδια στοιχεία είναι στον πίνακα που ακολουθεί.", marked))
    idx = []
    for ep in (e for e in post if e != ABROAD):  # abroad has no ballot box in 2024
        mine = post[ep]["votes"].get(NIKH, 0) + box[ep]["votes"].get(NIKH, 0)
        if mine:
            idx.append((names[ep], (post[ep]["votes"].get(NIKH, 0) / mine) / (post[ep]["valid"] / (post[ep]["valid"] + box[ep]["valid"]))))
    lo_i, hi_i = min(idx, key=lambda q: q[1]), max(idx, key=lambda q: q[1])
    print(f"Δείκτης επιστολικής ψήφου της ΝΙΚΗΣ ανά περιφέρεια: από {num(lo_i[1], 2)} ({lo_i[0]}) ως {num(hi_i[1], 2)} ({hi_i[0]}); "
          f"κάτω από 1 σε {sum(v < 1 for _, v in idx)} από τις {len(idx)}")
    SECTIONS.append(chart_strip(
        f"Ο ψηφοφόρος της ΝΙΚΗΣ ψήφισε λιγότερο επιστολικά από τον μέσο σε {sum(v < 1 for _, v in idx)} από τις {len(idx)} περιφέρειες",
        "Ευρωεκλογές 2024. Για κάθε περιφέρεια: το μερίδιο των ψήφων της ΝΙΚΗΣ που ήταν επιστολικές, διά το ίδιο μερίδιο για όλα τα "
        "έγκυρα. 1 = όσο ο μέσος ψηφοφόρος.", idx,
        "Δείκτης επιστολικής ψήφου της ΝΙΚΗΣ ανά περιφέρεια: " + "; ".join(f"{n} {num(v, 2)}" for n, v in sorted(idx, key=lambda q: q[1])),
        [(1, "1 = όσο ο μέσος ψηφοφόρος"), (prop, f"{num(prop, 2)} = όλη η χώρα")], {lo_i[0], hi_i[0]}))
    rows = []
    for ep in sorted((e for e in post if e != ABROAD), key=lambda e: -post[e]["votes"].get(NIKH, 0)):
        p, b = post[ep], box[ep]
        mine = p["votes"].get(NIKH, 0) + b["votes"].get(NIKH, 0)
        rows.append([html.escape(names[ep]), str(p["votes"].get(NIKH, 0)), num(share(p, NIKH)), str(rank(p, NIKH)),
                     num(share(b, NIKH)), str(rank(b, NIKH)), signed(share(p, NIKH) - share(b, NIKH)),
                     num(100 * p["votes"].get(NIKH, 0) / mine) + "%" if mine else "-",
                     num(100 * p["valid"] / (p["valid"] + b["valid"])) + "%"])
    emit("ΝΙΚΗ στην επιστολική ψήφο ανά περιφέρεια, Ευρωεκλογές 2024",
         "«Από τις ψήφους της»: πόσες από τις ψήφους της ΝΙΚΗΣ στην περιφέρεια ήταν επιστολικές· «Από όλα»: το ίδιο για όλα τα έγκυρα.",
         [("Περιφέρεια", False), ("Επιστολικές ψήφοι", True), ("Επιστολική %", True), ("Θέση", True), ("Κάλπη %", True),
          ("Θέση στην κάλπη", True), ("Διαφορά", True), ("Από τις ψήφους της", True), ("Από όλα", True)], rows, fold=True)


def map_data():
    """Payload of the city map: per election, one entry per placed city (valid, registered, stations, votes per party),
    and the parties shown with their names and colours. Cities Nominatim could not place are left off and counted."""
    ll = coords()
    out = {"els": [], "parties": {}}
    for e in ABROAD_ELECTIONS:
        gs = groups(e, "a.city || '|' || a.country", f"s.ep_id={ABROAD}")
        cities = [{"c": g.split("|")[0].strip(), "k": g.split("|")[1], "ll": ll[(g.split("|")[0].strip(), g.split("|")[1])],
                   "v": d["valid"], "r": d["reg"], "n": d["n"], "p": d["votes"]}
                  for g, d in gs.items() if (g.split("|")[0].strip(), g.split("|")[1]) in ll]
        parties = shown(e)
        for p in parties + [p for c in cities for p in c["p"]]:
            if p not in out["parties"]:
                out["parties"][p] = {"name": name(e, p), "color": color(e, p)}
        out["els"].append({"key": e.split("/")[1], "name": ELECTION_NAMES[e], "cities": cities, "shown": parties,
                           "missing": len(gs) - len(cities)})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


MAP_JS = r"""
const D = /*MAPDATA*/null;
const $ = id => document.getElementById(id);
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt = n => n.toLocaleString("el-GR");
const pc = x => (100 * x).toLocaleString("el-GR", {minimumFractionDigits: 1, maximumFractionDigits: 1}) + "%";
const MIN = 100;  // fewer valid votes than this: the share of one party says little, so the circle stays grey
const elSel = $("m-el"), colSel = $("m-col");
D.els.forEach(e => elSel.add(new Option(e.name, e.key)));
const h = new URLSearchParams(location.hash.slice(1));
if (D.els.some(e => e.key === h.get("e"))) elSel.value = h.get("e"); else elSel.value = D.els[D.els.length - 1].key;
const map = L.map("map", mapOptions({scrollWheelZoom: false, worldCopyJump: true})).setView([48, 10], 4);
map.getContainer().classList.add("muted");
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 10, opacity: 0.6,
  attribution: "&copy; OpenStreetMap · Αποτελέσματα: ΥΠΕΣ (ανεπίσημα)"}).addTo(map);
const layer = L.layerGroup().addTo(map), labels = L.layerGroup().addTo(map);
let marks = [];  // [latlng, number, radius] of the circles drawn, for the vote labels
function showLabels() {  // all numbers from zoom 6; below it only on the big circles, where they fit without piling up
  labels.clearLayers();
  if (!$("m-num").checked) return;
  const z = map.getZoom();
  marks.forEach(([ll, n, r]) => { if (z >= 6 || r >= 13) L.marker(ll, {interactive: false, keyboard: false,
    icon: L.divIcon({className: "mnum", html: `<span>${fmt(n)}</span>`, iconSize: null})}).addTo(labels); });
}
map.on("zoomend", showLabels);
const radius = v => 3 + Math.sqrt(v) * 0.42;  // area grows with the valid votes
const first = c => Object.keys(c.p).reduce((a, b) => c.p[a] >= c.p[b] ? a : b);
const share = (c, p) => (c.p[p] || 0) / c.v;
function breaks(vals) {  // quantile breaks over the non-zero values, as on the map pages
  const nz = vals.filter(v => v > 0).sort((a, b) => a - b);
  return nz.length ? [1, 2, 3, 4, 5].map(i => nz[Math.floor(i * nz.length / 6)]) : [];
}
const seq = () => ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"].map(css);
const sw = (col, label) => `<span class="k"><i style="background:${col}"></i>${label}</span>`;
function fillCols(el) {
  const keep = colSel.value;
  colSel.innerHTML = "";
  colSel.add(new Option("Πρώτο κόμμα", "first"));
  el.shown.forEach(p => colSel.add(new Option("Ποσοστό: " + D.parties[p].name, p)));
  colSel.value = [...colSel.options].some(o => o.value === (keep || h.get("p"))) ? (keep || h.get("p")) : "first";
}
function draw(user) {  // user: a control changed, so the address keeps the choice (on load it keeps a #section link)
  const el = D.els.find(e => e.key === elSel.value), mode = colSel.value;
  if (user) history.replaceState(null, "", "#e=" + el.key + (mode === "first" ? "" : "&p=" + mode));
  layer.clearLayers();
  marks = el.cities.map(c => [c.ll, mode === "first" ? c.v : (c.p[mode] || 0), radius(c.v)]);
  showLabels();
  const br = mode === "first" ? [] : breaks(el.cities.filter(c => c.v >= MIN).map(c => share(c, mode)));
  const col = c => {
    if (mode === "first") return D.parties[first(c)].color;
    if (c.v < MIN) return css("--line");
    const x = share(c, mode); if (x <= 0) return css("--s0");
    let i = 0; while (i < br.length && x > br[i]) i++; return seq()[i];
  };
  [...el.cities].sort((a, b) => b.v - a.v).forEach(c => {  // big circles first, small ones on top
    const f = first(c);
    const sel = mode === "first" ? "" : `<br>${D.parties[mode].name}: ${pc(share(c, mode))} (${fmt(c.p[mode] || 0)} ψήφοι)` +
      (c.v < MIN ? "<br><i>λίγες ψήφοι: το ποσοστό λέει λίγα</i>" : "");
    L.circleMarker(c.ll, {radius: radius(c.v), color: css("--surface"), weight: 1.5, fillColor: col(c), fillOpacity: 0.85})
      .bindTooltip(`<b>${c.c}</b> (${c.k})<br>${fmt(c.v)} έγκυρα, ${c.n} ${c.n === 1 ? "τμήμα" : "τμήματα"}, ` +
        `${pc(c.r ? c.v / c.r : 0)} των εγγεγραμμένων<br>Πρώτο: ${D.parties[f].name} ${pc(share(c, f))}${sel}`)
      .on("click", e => e.target.openTooltip()).addTo(layer);
  });
  const firsts = [...new Set(el.cities.map(first))];
  $("m-legend").innerHTML = (mode === "first" ? firsts.map(p => sw(D.parties[p].color, D.parties[p].name)).join("")
    : sw(css("--s0"), "καμία ψήφος") + seq().map((c, i) => i <= br.length ? sw(c, binLabel([-Infinity, ...br][i], br[i], pc)) : "").join("") +
      sw(css("--line"), `κάτω από ${MIN} έγκυρα`)) +
    `<span class="k">Μέγεθος κύκλου: έγκυρα. Αριθμός: ${mode === "first" ? "έγκυρα" : "ψήφοι " + D.parties[mode].name} (με μεγέθυνση, σε όλους τους κύκλους).${el.missing ? ` ${el.missing} πόλεις χωρίς θέση στον χάρτη.` : ""}</span>`;
}
elSel.addEventListener("change", () => { fillCols(D.els.find(e => e.key === elSel.value)); draw(true); });
colSel.addEventListener("change", () => draw(true));
$("m-num").addEventListener("change", showLabels);
fillCols(D.els.find(e => e.key === elSel.value));
draw();
"""


VIEW_JS = """(function () {
  var views = [].slice.call(document.querySelectorAll('.view')), cur = {};
  if (!views.length) return;
  var keys = [], els = {}, labels = {}, elabels = {};
  views.forEach(function (s) {
    var v = s.dataset.v, e = s.dataset.e;
    if (keys.indexOf(v) < 0) { keys.push(v); els[v] = []; labels[v] = s.dataset.vl; }
    if (e) { els[v].push(e); elabels[e] = s.dataset.el; }
  });
  var last = {};
  keys.forEach(function (v) { last[v] = els[v][els[v].length - 1] || ''; });
  cur.v = keys[0]; cur.e = last[keys[0]];
  var bar = document.getElementById('sw'), vrow = document.createElement('div'), erows = {}, vbtn = {}, ebtn = {};
  vrow.className = 'v'; vrow.setAttribute('role', 'group'); vrow.setAttribute('aria-label', 'Τι να δω'); bar.appendChild(vrow);
  function btn(text, fn) {
    var b = document.createElement('button'); b.type = 'button'; b.textContent = text; b.addEventListener('click', fn); return b;
  }
  keys.forEach(function (v) {
    vbtn[v] = btn(labels[v], function () { cur.v = v; cur.e = last[v]; draw(); }); vrow.appendChild(vbtn[v]);
    if (els[v].length < 2) return;
    var row = document.createElement('div'); row.className = 'e'; row.setAttribute('role', 'group'); row.setAttribute('aria-label', 'Εκλογή');
    row.style.setProperty('--n', els[v].length); erows[v] = row;
    els[v].forEach(function (e) { ebtn[e] = btn(elabels[e], function () { cur.e = e; last[v] = e; draw(); }); row.appendChild(ebtn[e]); });
    bar.appendChild(row);
  });
  function draw() {
    keys.forEach(function (v) {
      vbtn[v].setAttribute('aria-pressed', v === cur.v ? 'true' : 'false');
      if (erows[v]) erows[v].hidden = v !== cur.v;
    });
    if (erows[cur.v]) {
      els[cur.v].forEach(function (e) { ebtn[e].setAttribute('aria-pressed', e === cur.e ? 'true' : 'false'); });
      erows[cur.v].style.setProperty('--i', els[cur.v].indexOf(cur.e));
    }
    views.forEach(function (s) { s.classList.toggle('on', s.dataset.v === cur.v && (!s.dataset.e || s.dataset.e === cur.e)); });
    bar.classList.add('ready');
  }
  function reveal(id) {
    var el = id && document.getElementById(decodeURIComponent(id)), s = el && el.closest('.view');
    if (!s) return false;
    cur.v = s.dataset.v; cur.e = s.dataset.e || last[cur.v]; last[cur.v] = cur.e; draw(); return true;
  }
  draw();
  if (location.hash && reveal(location.hash.slice(1))) document.getElementById(decodeURIComponent(location.hash.slice(1))).scrollIntoView();
  addEventListener('hashchange', function () { if (reveal(location.hash.slice(1))) document.getElementById(decodeURIComponent(location.hash.slice(1))).scrollIntoView(); });
  document.addEventListener('click', function (ev) { var a = ev.target.closest && ev.target.closest('a[href^="#"]'); if (a && a.hash.length > 1) reveal(a.hash.slice(1)); });
})();"""

def page():
    # the sections sit in a <div>: common.css moves "main > h2" to the end on phones (a rule for the map pages)
    title = "Ψηφοφόροι εξωτερικού και επιστολική ψήφος"
    jump = "".join([f'<a href="#ab-{e.replace("/", "-")}">Εξωτερικό, {html.escape(ELECTION_NAMES[e])}</a>' for e in ABROAD_ELECTIONS]
                      + ['<a href="#postal">Επιστολική ψήφος, Ευρωεκλογές 2024</a>', '<a href="#nikh">ΝΙΚΗ: αναλυτικά</a>'])
    jump = '<a href="#map-h">Χάρτης πόλεων</a>' + jump
    return f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{meta(title, "Πώς ψήφισαν οι Έλληνες του εξωτερικού ανά χώρα και πόλη (2023) και όσοι ψήφισαν επιστολικά (Ευρωεκλογές 2024).")}
{FONTS}
<!--LEAFLET-->
<script>document.documentElement.classList.add("js")</script><script>/*THEME_JS*/</script><style>{common_css()}
{CHART_CSS}.mctl{{display:flex;flex-wrap:wrap;gap:.5em 1.2em;margin:.6em 0}} .mctl select{{margin-left:.4em}}
.mnum span{{position:absolute;transform:translate(-50%,-50%);white-space:nowrap;font-size:12px;font-weight:600;line-height:1;
  color:var(--ink);paint-order:stroke;-webkit-text-stroke:3px var(--surface)}}
#m-legend{{display:flex;flex-wrap:wrap;gap:.3em 1em;margin:.5em 0 1em;font-size:14px}}
#m-legend .k i{{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:5px;vertical-align:-1px}}
main{{max-width:1100px}} p{{color:var(--ink-2)}} .wrap{{overflow-x:auto;margin-bottom:1.5em}} h2{{font-size:var(--h2);margin:var(--space-2xl) 0 var(--space-sm)}} h3{{font-size:var(--h3);margin:var(--space-lg) 0 var(--space-xs)}}
.sw{{display:grid;justify-items:start;gap:var(--space-md);margin:var(--space-lg) 0 0}}
.sw .v,.sw .e{{display:flex;flex-wrap:wrap}} .sw .v{{gap:var(--space-xs) var(--space-lg)}}
.sw button{{font:inherit;color:var(--ink-2);background:none;border:0;cursor:pointer;transition:color 150ms ease-out}}
.sw button:hover,.sw button[aria-pressed=true]{{color:var(--ink)}}
.sw .v{{gap:var(--space-xs)}}
.sw .v button{{min-height:48px;padding:0 var(--space-lg);font-size:var(--t-lg);font-weight:600;letter-spacing:-.01em;color:var(--ink);border:2px solid color-mix(in srgb,var(--ink) 40%,transparent);border-radius:10px;transition:background-color 150ms ease-out,color 150ms ease-out,border-color 150ms ease-out}}
.sw .v button:hover:not([aria-pressed=true]){{border-color:var(--ink);background:color-mix(in srgb,var(--ink) 7%,transparent)}}
.sw .v button[aria-pressed=true]{{background:var(--ink);border-color:var(--ink);color:var(--paper,var(--surface))}}
.sw .e{{position:relative;display:inline-grid;grid-auto-flow:column;grid-auto-columns:1fr;padding:4px;border-radius:999px;background:color-mix(in srgb,var(--ink) 7%,var(--paper,var(--surface)));border:2px solid color-mix(in srgb,var(--ink) 40%,transparent)}}
.sw .e[hidden]{{display:none}}
.sw .e::before{{content:"";position:absolute;inset:4px auto 4px 4px;width:calc((100% - 8px) / var(--n));border-radius:999px;background:var(--ink);transform:translateX(calc(var(--i) * 100%));transition:transform 280ms cubic-bezier(.16,1,.3,1)}}
.sw .e button{{position:relative;min-height:36px;padding:0 var(--space-lg);border-radius:999px;font-size:var(--t-base)}}
.sw .e button[aria-pressed=true]{{color:var(--paper,var(--surface))}}
.sw button:focus-visible{{outline:2px solid var(--ink);outline-offset:2px}}
@media (pointer:coarse){{.sw .e button{{min-height:44px}}}} @media (prefers-reduced-motion:reduce){{.sw button,.sw .e::before{{transition:none}}}}
.js .view:not(.on){{display:none}} .js .sw:not(.ready){{min-height:112px}} .view>h2:first-child{{margin-top:var(--space-xl)}}
summary h3{{display:inline}}
@media (max-width:599px){{th,td{{padding:8px 4px}} th{{font-size:13px}} td{{font-size:14px}}}}</style></head><body><main id="main">
{header()}
<h1>{title}</h1>
<p>Από τα ανεπίσημα αποτελέσματα του ΥΠΕΣ. Οι ψήφοι αυτές δεν έχουν θέση στους χάρτες των περιφερειών, μετρούν όμως στα σύνολα.
«Εγγεγραμμένοι» στο εξωτερικό και στην επιστολική ψήφο είναι όσοι έκαναν αίτηση, άρα τα έγκυρα ως ποσοστό τους είναι κοντά στη συμμετοχή.</p>
<nav class="jump" aria-label="Μετάβαση στην ενότητα">{jump}</nav>
<div><h2 id="map-h">Χάρτης πόλεων του εξωτερικού</h2>
<div class="mctl"><label>Εκλογή<select id="m-el"></select></label><label>Χρώμα<select id="m-col"></select></label><label><input type="checkbox" id="m-num" checked> Αριθμός ψήφων</label></div>
<div id="map" role="region" aria-label="Χάρτης των πόλεων με εκλογικά τμήματα εξωτερικού· τα ίδια στοιχεία είναι στους πίνακες ανά πόλη"></div>
<div id="m-legend"></div>
<div class="sw" id="sw"></div>
{"".join(SECTIONS)}</div>
{footer(sources='<li>Θέσεις πόλεων: <a href="https://nominatim.openstreetmap.org/" rel="noopener">Nominatim (OpenStreetMap)</a></li>')}</main>
<script>/*SHARED_JS*/</script><script>{VIEW_JS}</script><script>{MAP_JS.replace("/*MAPDATA*/null", map_data())}</script></body></html>"""


def main():
    for e in ABROAD_ELECTIONS:
        view(abroad_section, e, v="kalpi", vl="Εξωτερικό (κάλπη)", e=e.replace("/", "-"), el=ELECTION_NAMES[e])
    view(postal_section, v="postal", vl="Επιστολική ψήφος")
    view(nikh_section, v="nikh", vl="ΝΙΚΗ")
    PAGE.write_text(secure(fill(page(), current="abroad"), PAGE), encoding="utf-8")
    print(f"\nwrote {PAGE}", file=sys.stderr)


if __name__ == "__main__":
    main()
