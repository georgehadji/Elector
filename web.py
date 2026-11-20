"""Site-wide parts of every page (colour tokens, header, footer, theme) and the index.

fill() puts the shared parts into a page; render_page() also inlines common.css/js and the page data.
record() keeps out/maps.json, the list of built pages; write_index() turns it into out/index.html.
"""
import html
import json
import os
import re
import sqlite3
import unicodedata
import urllib.parse
from collections import defaultdict

from config import (
    DB,
    ELECTED,
    ELECTION_NAMES,
    ELECTIONS,
    HERE,
    OUT,
    PARTY_ARTIFACTS,
    PARTY_SHORT,
    REGIONS,
)
from geo import exteriors, frame, path
from matching import ep_label

# Site header and footer of every page. The toggle's pressed state means dark; theme.js keeps it in sync.
THEME_BTN = ('<button id="theme" type="button" aria-pressed="false"><svg viewBox="0 0 16 16" aria-hidden="true">'
             '<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 1.5v11a5.5 5.5 0 0 1 0-11z"/></svg>Σκούρο θέμα</button>')
HEADER = f'<header class="bar"><a class="home" href="index.html">Χάρτες σταυρών</a>{THEME_BTN}</header>'
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fira+Sans:wght@400;600&family=GFS+Didot&display=swap">')


def footer(note="", home=True):
    """Site footer; `note` adds page-specific caveats, `home` links back to the index."""
    return ('<footer class="site"><p>Ανεπίσημα αποτελέσματα του Υπουργείου Εσωτερικών, ενωμένα με τα όρια κοινοτήτων της ΕΛΣΤΑΤ 2021.'
            f'{note} Μόνο δημόσια συγκεντρωτικά αποτελέσματα, κανένα προσωπικό δεδομένο.</p><p>'
            + ('<a href="index.html">Όλοι οι χάρτες</a>' if home else "")
            + '<a href="https://github.com/georgehadji/Elector">Κώδικας και δεδομένα στο GitHub</a>'
            '<button type="button" class="copy">Αντιγραφή συνδέσμου</button></p></footer>')


def theme_css(light, dark, print_=None):
    """Colour tokens: light; dark (the system setting unless the toggle chose light, or the toggle chose dark);
    print (always light). CSS needs the dark block twice, a media query and an attribute selector: here it is written once."""
    def decl(t):
        return ";".join(f"--{k}:{v}" for k, v in t.items())
    d = f"color-scheme:dark;{decl(dark)}"
    out = (f":root{{color-scheme:light;{decl(light)}}}\n"
           f"@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{{d}}}}}\n:root[data-theme=dark]{{{d}}}\n")
    if print_ is not None:  # undo every dark override
        out += f"@media print{{:root:not([data-theme]),:root[data-theme]{{color-scheme:light;{decl({k: light[k] for k in dark} | print_)}}}}}\n"
    return out


# Map pages: warm grays, a blue sequential ramp (s0-s6) and a red-gray-blue diverging one (d-3..d3).
MAP_LIGHT = {"surface": "#fcfcfb", "ink": "#1d1d1b", "ink-2": "#5c5b57", "line": "#e4e3df", "chip": "#f2f1ee", "shadow": "rgba(0,0,0,.18)",
             "s0": "#eef4fc", "s1": "#cde2fb", "s2": "#9ec5f4", "s3": "#6da7ec", "s4": "#3987e5", "s5": "#256abf", "s6": "#104281",
             "scrim": "rgba(0,0,0,.5)", "on-scrim": "#fff",
             "link": "#256abf", "d-3": "#a8302e", "d-2": "#e0736b", "d-1": "#f6c4c0", "d0": "#e4e3df", "d1": "#9ec5f4", "d2": "#3987e5",
             "d3": "#104281"}
MAP_DARK = {"surface": "#1a1a19", "ink": "#ecebe7", "ink-2": "#a8a7a2", "line": "#383835", "chip": "#262624",
            "shadow": "rgba(0,0,0,.5)", "d0": "#5a5955", "link": "#6da7ec"}  # dark: scrim and on-scrim stay as in light
# Index: cool paper and ink, one blue pen.
INDEX_LIGHT = {"paper": "#f6f7f9", "ink": "#13233d", "ink-2": "#55627a", "line": "#dde2ea", "pen": "#256abf", "wash": "#eaf1fb"}
INDEX_DARK = {"paper": "#171c24", "ink": "#e8edf5", "ink-2": "#9aa6b8", "line": "#2b3442", "pen": "#6da7ec", "wash": "#1f2a3a"}


def fill(page, light=MAP_LIGHT, dark=MAP_DARK, print_=None):
    """Shared parts of every page: colour tokens, site CSS and theme script, fonts, header, footer."""
    for placeholder, text in (("/*THEME_TOKENS*/", theme_css(light, dark, print_)),
                              ("/*SITE_CSS*/", (HERE / "site.css").read_text(encoding="utf-8")),
                              ("/*THEME_JS*/", (HERE / "theme.js").read_text(encoding="utf-8")),
                              ("/*SHARED_JS*/", (HERE / "shared.js").read_text(encoding="utf-8")),
                              ("<!--FONTS-->", FONTS), ("<!--HEADER-->", HEADER), ("<!--FOOTER-->", footer())):
        page = page.replace(placeholder, text)
    return page


def meta(title, description):
    """Description and Open Graph tags (no og:image: that needs a hosted raster picture)."""
    t, d = html.escape(title, quote=True), html.escape(description, quote=True)
    return (f'<meta name="description" content="{d}"><meta property="og:type" content="website">'
            f'<meta property="og:site_name" content="Χάρτες σταυρών"><meta property="og:locale" content="el_GR">'
            f'<meta property="og:title" content="{t}"><meta property="og:description" content="{d}">')

def common_css():
    return fill((HERE / "common.css").read_text(encoding="utf-8"), print_={"surface": "#fff"})


def render_page(template, data):
    """Template with the shared UI (common.css/js, theme, header, footer) and the page data inlined: one self-contained file."""
    page = (HERE / template).read_text(encoding="utf-8")
    page = fill(page.replace("/*COMMON_CSS*/", common_css()).replace("/*COMMON_JS*/", (HERE / "common.js").read_text(encoding="utf-8")))
    data = {**data, "election_title": ELECTIONS[data["election"]][1]}
    kind = "Ψήφοι κομμάτων" if data.get("mode") == "party" else "Σταυροί προτίμησης"
    unit = "εκλογικό τμήμα" if "venues" in data else "εκλογικό διαμέρισμα"
    et = data["election_title"]
    page = page.replace("<!--META-->", meta(f"{kind}, {data['ep_name']}",
                                            f"{kind} ανά {unit}, {data['ep_name']}, {et[0].lower() + et[1:]}."))
    return page.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))  # last: data may contain anything


# A ballpoint cross in a ballot box, the mark a voter puts next to a candidate: the one decorative element of the site.
CROSS_SVG = ('<svg class="x" viewBox="0 0 40 40" aria-hidden="true"><rect x="3" y="3" width="34" height="34" rx="3"/>'
             '<path d="M11 12 C16 17 22 24 29 29"/>'
             '<path d="M28 11 C23 16 17 23 12 30"/></svg>')
TOP_KEY = "Πρώτος σε σταυρούς, Μάιος 2023"  # said once above the list, and as a screen-reader prefix on each card

def greece_figure(areas, key, caption, size=440):
    """Static map of Greece for the index: `areas` = [(GeoJSON geometry, colour)], `key` = [(name, colour)].
    One path per colour; neighbouring areas keep their own outline, simplified to whole units."""
    to_xy, w, h = frame([g for g, _ in areas], size)
    by_color = defaultdict(list)
    for g, color in areas:
        by_color[color].extend(exteriors(g))
    paths = "".join(f'<path fill="{c}" stroke="{c}" d="{path(rings, to_xy, 0.8, 1.0)}"/>' for c, rings in by_color.items())
    swatches = "".join(f'<span class="k"><i style="background:{c}"></i>{html.escape(n)}</span>' for n, c in key)
    return (f'<figure class="gr"><a href="compare.html"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(caption)}">'
            f'<g stroke-width=".6" stroke-linejoin="round">{paths}</g></svg></a>'
            f'<figcaption>{html.escape(caption)}. <a href="compare.html">Σύγκριση εκλογών</a><span class="keys">{swatches}</span></figcaption></figure>')

INDEX_CSS = """
/*THEME_TOKENS*/
/*SITE_CSS*/
.bar{justify-content:flex-end;margin:-24px 0 16px}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 "Fira Sans",system-ui,sans-serif}
main{max-width:1080px;margin:0 auto;padding:40px 24px 64px}
a{color:var(--pen)}
:focus-visible{outline:2px solid var(--pen);outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
h1{font:400 clamp(44px,9vw,84px)/1 "GFS Didot",Georgia,serif;letter-spacing:-.01em;margin:0;display:flex;align-items:center;gap:.18em}
h1 .x{width:.72em;height:.72em;flex:none}
h1 .x path{stroke-width:4.4}
.x path,.x rect{fill:none;stroke:var(--pen);stroke-width:3.2;stroke-linecap:round}
.x rect{stroke-width:2.4}
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
.top{display:flex;gap:8px;align-items:baseline;margin:0 0 10px;font-size:14px;color:var(--ink-2);line-height:1.4}
.top .x{width:14px;height:14px;flex:none;align-self:center}
.top b{color:var(--ink);font-weight:600}
.nation{display:flex;flex-wrap:wrap;gap:4px 20px;margin:6px 0 0;font-size:14px}
.nation a{color:var(--ink-2);text-underline-offset:3px}
.acts{display:flex;flex-wrap:wrap;align-items:center;gap:0 14px}
.older summary,.fold summary{display:flex;align-items:center;min-height:32px;cursor:pointer;color:var(--ink-2);font-size:14px}
.older[open]{flex:1 1 100%}
.older[open] summary{margin-bottom:4px}
.dhm{margin:4px 0 0}
.el{display:flex;flex-wrap:wrap;align-items:center;gap:4px 14px;margin:0}
.el a{display:inline-flex;align-items:center;min-height:32px;color:var(--ink-2);font-size:14px;white-space:nowrap;
      text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
.el a:hover{color:var(--pen);text-decoration-color:var(--pen)}
.el a.now{padding:0 12px;border:1px solid var(--pen);border-radius:16px;color:var(--pen);background:var(--wash);
          text-decoration:none;font-weight:600}
.el a.now:hover{background:var(--pen);color:var(--paper)}
.sil{position:absolute;right:0;top:12px;width:48px;height:48px;color:var(--ink-2)}
.sil path{fill:currentColor;fill-opacity:.22;stroke:currentColor;stroke-width:1;stroke-linejoin:round}
.eps li{position:relative}
.eps li>h2,.eps li>.top{margin-right:60px}
.reg{font:600 13px/1.2 "Fira Sans",system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-2);margin:28px 0 0}
.grp[hidden]{display:none}
.eps{margin-top:6px}
.key{display:flex;gap:8px;align-items:center;margin:20px 0 0;font-size:14px;color:var(--ink-2)}
.key .x{width:14px;height:14px;flex:none}
.gr{margin:20px 0 0;max-width:380px}
.gr a:first-child{display:block}
.gr svg{display:block;width:100%;height:auto;max-height:260px}
.gr figcaption{margin:6px 0 0;font-size:13px;color:var(--ink-2)}
.gr .keys{display:flex;flex-wrap:wrap;gap:2px 12px;margin-top:4px}
.gr .k{display:inline-flex;align-items:center;white-space:nowrap}
.gr .k i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}
@media (min-width:900px){main{position:relative}.gr{position:absolute;right:24px;top:56px;width:340px;margin:0}.gr svg{max-height:none}h1,.lede,#s,.nation,.key{max-width:calc(100% - 380px)}}
.dhm{margin:0 0 8px;color:var(--ink-2);font-size:13px;line-height:1.45}
.more{margin-top:56px;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:8px 36px}
.more section{border-top:2px solid var(--ink);padding-top:12px}
.more h2{font:400 24px/1.2 "GFS Didot",Georgia,serif;margin:0 0 6px}
.more p{color:var(--ink-2);margin:0 0 10px;font-size:15px}
.more ul{margin:0;padding:0;list-style:none}
.more li{padding:3px 0}
.more li span{color:var(--ink-2);font-size:14px}
footer{margin-top:48px;font-size:14px;max-width:40em}
@media (max-width:599px){main{padding:24px 16px 48px}.eps li{padding:8px 0 6px}.eps h2{margin:0 0 2px}.top{margin:0 0 4px;font-size:13px;line-height:1.3}.bar{margin:-12px 0 12px}.lede{font-size:16px}#f{font-size:17px}}
@media (pointer:coarse){.nation a{display:inline-flex;align-items:center;min-height:44px}.older summary,.fold summary{min-height:44px}.el a{min-height:44px}.el a.now{padding:0 16px}.more li a{display:inline-block;padding:10px 0}}
"""
INDEX_JS = """
document.getElementById("s").hidden = false;
const f = document.getElementById("f"), n = document.getElementById("n"), items = [...document.querySelectorAll(".eps li")];
const words = new Map(items.map(li => [li, li.dataset.k.split(" ").map(w => [w, key(w)])]));
const own = li => words.get(li).slice(0, +li.dataset.n);  // the constituency's own name, ahead of its towns
f.addEventListener("input", () => {
  const qs = queryWords(f.value);
  let shown = 0;
  for (const li of items) {
    const hit = qs.every(q => hits(words.get(li), q)); li.hidden = !hit; shown += hit;
    li.style.order = hit && qs.length && !qs.every(q => hits(own(li), q)) ? 1 : "";  // name matches first
  }
  document.querySelectorAll(".grp").forEach(g => { g.hidden = !g.querySelector("li:not([hidden])"); });  // a region head goes with its cards
  for (const li of items) { const d = li.querySelector("details"); if (d) d.open = shown === 1 && !li.hidden; }  // the one match shows its older maps
  n.textContent = !qs.length ? "" : !shown ? `Καμία περιφέρεια με «${f.value.trim()}». Δοκίμασε το όνομα του δήμου ή του νομού.`
    : shown === 1 ? "1 περιφέρεια. Enter για τον πιο πρόσφατο χάρτη." : `${shown} περιφέρειες`;
});
f.addEventListener("keydown", e => {
  const shown = items.filter(li => !li.hidden).sort((a, b) => (+a.style.order || 0) - (+b.style.order || 0));
  if (e.key === "Enter" && f.value.trim() && (shown.length === 1 || +shown[1].style.order > +shown[0].style.order)) location.href = shown[0].querySelector("a.now").href;
});
"""


def card(ep, name, keys, n_own, lead, note, chips, sil=""):
    """One constituency: the newest election is the default link, the older ones fold into a <details>.
    `chips` are link markup, newest first; `note` is the optional list of municipalities."""
    now, *older = chips
    folded = (f'<details class="older"><summary>Παλαιότερες εκλογές ({len(older)})</summary>'
              f'<p class="el">{"".join(older)}</p>{note}</details>') if older else note
    return (f'<li id="ep-{ep}" data-k="{html.escape(keys)}" data-n="{n_own}"><h2>{html.escape(name)}</h2>'
            f'{sil}{lead}<div class="acts"><p class="el">{now}</p>{folded}</div></li>')

def nationwide():
    """Pages that cover the whole country, ahead of the constituency list."""
    links = (("compare.html", "Σύγκριση εκλογών"), ("#party", "Χάρτες ανά κόμμα"), ("#tm", "Ανά εκλογικό κατάστημα"), ("#cov", "Κάλυψη ανά νομό"))
    return ('<nav class="nation" aria-label="Χάρτες όλης της χώρας">' + "".join(f'<a href="{h}">{t}</a>' for h, t in links) + '</nav>')


def _write_index(order, nikh, elected):
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
            for ep, cand, pid, party, votes in con.execute(
                    "SELECT e.name, c.name, p.party_id, p.name, MAX(t.votes) FROM ep_total t JOIN ep e USING(election, ep_id) "
                    "JOIN candidate c USING(election, ep_id, party_id, cand_id) JOIN party p USING(election, party_id) "
                    "WHERE t.election = '2023/may' AND t.cand_id > 0 GROUP BY t.ep_id"):
                top[ep_label(ep)] = (cand, PARTY_SHORT.get(pid, party), votes)
    eps, tm = {}, []
    for f, m in order:
        if "_tm_" in f:
            tm.append((f, m))  # station maps exist for a few constituencies only: listed apart, not on the cards
        else:
            eps.setdefault(m["ep_name"], []).append((f, m))
    rank = list(ELECTION_NAMES)
    region_of = {ep: region for region, eps_ in REGIONS for ep in eps_}
    by_region = {region: [] for region, _ in REGIONS}  # keeps the regions' north-to-south order
    for name in sorted(eps, key=fold):
        links = sorted(eps[name], key=lambda fm: rank.index(fm[1]["election"]) if fm[1]["election"] in rank else -1)
        latest = links[-1][1]
        # The newest election is the default map; the others are quieter. The name in each link is for screen readers.
        chips = [
            f'<a{" class=now" if i == 0 else ""} href="{urllib.parse.quote(f)}">'
            f'{ELECTION_NAMES.get(m["election"], m["election"])}<span class="sr">, {html.escape(name)}</span></a>'
            for i, (f, m) in enumerate(reversed(links))]
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
        lead = (f'<p class="top">{CROSS_SVG}<span><span class="sr">{TOP_KEY}: </span><b>{html.escape(t[0])}</b> '
                f'({html.escape(t[1])}), {f"{t[2]:,}".replace(",", ".")}</span></p>' if t else "")
        by_region.setdefault(region_of.get(latest["ep"], "Λοιπές"), []).append(
            card(latest["ep"], name, k, len(own), lead, note, chips, latest.get("sil", "")))
    nikh_rows = "".join(
        f'<li><a href="{urllib.parse.quote(f)}">{html.escape(m["ep_name"])}</a> <span>'
        f'{ELECTION_NAMES.get(m["election"], m["election"])}'
        f'{", " + html.escape(elected[m["ep"]]) if m["election"] == "2023/june" and m["ep"] in elected else ""}</span></li>'
        for f, m in nikh)
    nikh_rows += "".join(f'<li><a href="{urllib.parse.quote(f)}">{html.escape(m["ep_name"])}</a> <span>{html.escape(m["label"])}</span></li>'
                         for f, m in tm if "_tm_131-" not in f)
    groups = "".join(f'<section class="grp"><h2 class="reg">{html.escape(region)}</h2><ul class="eps">{"".join(lis)}</ul></section>'
                     for region, lis in by_region.items() if lis)
    gr = HERE / "out" / "greece_map.html"
    greece = gr.read_text(encoding="utf-8") if gr.exists() else ""  # written by compare.py
    nikh_n = nikh_rows.count("<li>")
    coverage = "".join(
        f'<li><a href="index_{e.replace("/", "-")}.html">{name}</a></li>' for e, name in reversed(ELECTION_NAMES.items())
        if (OUT / f'index_{e.replace("/", "-")}.html').exists())
    artifacts = "".join(f'<li><a href="{u}">{html.escape(n)}</a></li>' for n, u in PARTY_ARTIFACTS)
    (OUT / "index.html").write_text(fill(f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Χάρτες σταυρών</title>
<meta name="description" content="Χάρτες αποτελεσμάτων των ελληνικών εκλογών ανά κοινότητα και εκλογικό τμήμα.">
{FONTS}
<script>/*THEME_JS*/</script>
<style>{INDEX_CSS}</style></head><body><main>
<header>
<div class="bar">{THEME_BTN}</div>
<h1>{CROSS_SVG}Χάρτες σταυρών</h1>
<p class="lede">Πού ψήφισε κάθε κόμμα και κάθε υποψήφιος, ανά κοινότητα και ανά εκλογικό τμήμα, σε όλες τις εκλογικές περιφέρειες.</p>
<div id="s" hidden><label class="sr" for="f">Αναζήτηση περιφέρειας</label>
<input id="f" type="search" placeholder="Δήμος ή νομός, π.χ. Πάτρα, Αργολίδα" autocomplete="off">
<p id="n" aria-live="polite"></p></div>
{nationwide()}
{greece}
<p class="key">{CROSS_SVG}<span>{TOP_KEY}</span></p>
</header>
{groups}
<div class="more">
<section id="cov"><h2>Κάλυψη ανά νομό</h2><p>Πόσοι σταυροί και ψήφοι φαίνονται στους χάρτες κάθε εκλογής.</p><ul>{coverage}</ul></section>
<section id="tm"><h2>Ανά εκλογικό κατάστημα</h2><p>ΝΙΚΗ: οι 9 περιφέρειες όπου εξέλεξε βουλευτή τον Ιούνιο του 2023.
<a href="NIKH_eklegmenoi_2023.html">Αναφορά Μαΐου–Ιουνίου</a>, <a href="../exports/NIKH_2023_ana_dhm_enotita.csv">CSV ανά δημοτική ενότητα</a>,
<a href="nikh_2023-2024.html">χάρτης όλης της χώρας: ποσοστά και μεταβολές 2019–2024</a>.</p><details class="fold"><summary>Όλοι οι χάρτες ({nikh_n})</summary><ul>{nikh_rows}</ul></details></section>
<section id="party"><h2>Χάρτες ανά κόμμα</h2><p>Στατικοί χάρτες στο claude.ai, ανοίγουν μόνο για όσους έχουν πρόσβαση.</p><details class="fold"><summary>Όλα τα κόμματα ({len(PARTY_ARTIFACTS)})</summary><ul>{artifacts}</ul></details></section>
</div>
{footer(" Οι ψήφοι ετεροδημοτών και ειδικών τμημάτων δεν έχουν θέση στον χάρτη.", home=False)}
</main><script>/*SHARED_JS*/</script><script>{INDEX_JS}</script></body></html>""", INDEX_LIGHT, INDEX_DARK), encoding="utf-8")


MAPS = OUT / "maps.json"


def load_maps():
    return json.loads(MAPS.read_text(encoding="utf-8")) if MAPS.exists() else {}


def ordered(maps):
    return sorted(maps.items(), key=lambda kv: (kv[1]["election"], kv[1]["ep_name"], "_tm_" in kv[0], kv[1]["label"]))


def links(file, election, ep):
    """Links to the constituency's other maps (area map first) for the page's view switcher."""
    return [{"href": f, "label": m["label"]} for f, m in ordered(load_maps())
            if m["ep"] == ep and m["election"] == election and f != file]


def entry(election, ep, ep_name, label, sil=""):
    """A maps.json record; `sil` is the constituency's silhouette SVG (area maps only)."""
    return {"election": election, "ep": ep, "ep_name": ep_label(ep_name), "label": label, **({"sil": sil} if sil else {})}


def record(entries):
    """Add or replace {file: entry(...)} in out/maps.json. One writer per build: parallel workers
    return their entries and the parent records them; the file is replaced atomically."""
    maps = load_maps()
    maps.update(entries)
    for m in maps.values():  # entries written before a name fix
        m["ep_name"] = ep_label(m["ep_name"])
    tmp = MAPS.with_suffix(".tmp")
    tmp.write_text(json.dumps(maps, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, MAPS)


def write_index():
    """out/index.html from out/maps.json: once per build, not once per page."""
    order = ordered(load_maps())
    nikh = sorted((kv for kv in order if "_tm_131-" in kv[0]), key=lambda kv: (kv[1]["election"] != "2023/june", kv[1]["ep_name"]))
    _write_index(order, nikh, ELECTED)
