"""Site-wide parts of every page (colour tokens, header, footer, theme) and the index.

fill() puts the shared parts into a page; render_page() also inlines common.css/js and the page data.
record() keeps out/maps.json, the list of built pages; write_index() turns it into out/index.html.
"""
import base64
import datetime
import hashlib
import html
import json
import os
import re
import sqlite3
import unicodedata
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

from config import (
    DB,
    ELECTED,
    ELECTION_NAMES,
    ELECTIONS,
    HERE,
    OUT,
    PARTY_SHORT,
    REGIONS,
    SITE_URL,
    og_kind,
    slug,
    source,
)
from geo import exteriors, frame, path
from matching import ep_label

# Site header and footer of every page. The toggle's pressed state means dark; theme.js keeps it in sync.
THEME_BTN = ('<button id="theme" type="button" aria-pressed="false" aria-label="Σκούρο θέμα"><svg viewBox="0 0 16 16" aria-hidden="true">'
             '<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 1.5v11a5.5 5.5 0 0 1 0-11z"/></svg></button>')
FONTS = "".join(f'<link rel="preload" href="fonts/{f}.woff2" as="font" type="font/woff2" crossorigin>'
                for f in ("ibm-plex-sans-greek", "ibm-plex-sans-latin"))  # the @font-face rules are in fonts.css
MARK = ('<svg class="mark" viewBox="0 0 40 40" aria-hidden="true"><rect x="3" y="3" width="34" height="34" rx="3"/>'
        '<path d="M11 12 C16 17 22 24 29 29"/><path d="M28 11 C23 16 17 23 12 30"/></svg>')
NAV = (("index", "index.html", "Περιφέρειες"), ("compare", "compare.html", "Σύγκριση εκλογών"))
MONTHS = ("Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου",
          "Ιουλίου", "Αυγούστου", "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου")


def header(current="maps", ctx="", skip="#main"):
    """Site bar: wordmark, three-item nav, theme toggle, skip link; `ctx` is the wayfinding row of map pages.
    `current`: "index" and "compare" are those pages, "maps" is a page under Περιφέρειες (aria-current="true")."""
    cur = {"index": ("index", "page"), "compare": ("compare", "page"), "maps": ("index", "true")}.get(current)
    nav = "".join(f'<a href="{href}"' + (f' aria-current="{cur[1]}"' if cur and cur[0] == key else "") + f">{label}</a>"
                  for key, href, label in NAV)
    to = "στον χάρτη" if skip == "#map" else "στο περιεχόμενο"
    home = (f'<a class="home" href="index.html" aria-label="Χάρτες σταυρών">{MARK}</a>' if current == "index"  # the h1 below says it
            else f'<a class="home" href="index.html">{MARK}Χάρτες σταυρών</a>')
    return (f'<a class="skip" href="{skip}">Μετάβαση {to}</a><header class="bar{" with-ctx" if ctx else ""}">{home}'
            f'<nav aria-label="Κύριο μενού">{nav}</nav>{THEME_BTN}</header>{ctx}')


def footer(note="", home=True, compact=False, sources=""):
    """Site colophon: sources (`sources` adds page-specific <li> items), notes (`note` adds page-specific caveats), links. `compact` keeps it to a few lines
    on pages where the map needs the height. `home` is kept for callers; the Χάρτες column always links the index."""
    today = datetime.date.today()
    return (f'<footer class="site{" compact" if compact else ""}"><div class="cols">'
            '<div><h3>Πηγές</h3><ul>'
            '<li>Αποτελέσματα: <a href="https://ekloges.ypes.gr/" rel="noopener">Υπουργείο Εσωτερικών</a></li>'
            '<li>Όρια: <a href="https://www.statistics.gr/" rel="noopener">ΕΛΣΤΑΤ 2021</a></li>'
            '<li>Υπόβαθρο: <a href="https://www.openstreetmap.org/copyright" rel="noopener">OpenStreetMap</a></li>'
            f'{sources}</ul></div>'
            f'<div><h3>Σημειώσεις</h3><p>Ανεπίσημα αποτελέσματα.{note} Μόνο δημόσια συγκεντρωτικά αποτελέσματα, κανένα προσωπικό δεδομένο.</p></div>'
            '<div><h3>Χάρτες</h3><ul><li><a href="index.html">Περιφέρειες</a></li><li><a href="compare.html">Σύγκριση εκλογών</a></li>'
            '<li><button type="button" class="copy">Αντιγραφή συνδέσμου</button></li></ul></div></div>'
            f'<p class="built">Ενημέρωση: {today.day} {MONTHS[today.month - 1]} {today.year}{MARK}</p></footer>')


def context_row(data):
    """Wayfinding row of a map page: the constituency and its other elections (from maps.json)."""
    name = html.escape(data["ep_name"])
    if "venues" in data or "ep" not in data:
        return f'<div class="ctx"><b>{name}</b></div>'
    sib = {m["election"]: f for f, m in load_maps().items() if m["ep"] == data["ep"] and "_tm_" not in f}
    sib.setdefault(data["election"], f"{slug(data['election'])}_{data['ep']}.html")
    links = "".join((f'<a href="{sib[e]}" aria-current="page">{ELECTION_NAMES[e]}</a>' if e == data["election"]
                     else f'<a href="{sib[e]}">{ELECTION_NAMES[e]}</a>') for e in reversed(list(ELECTIONS)) if e in sib)
    return f'<div class="ctx"><b>{name}</b><nav aria-label="Εκλογές αυτής της περιφέρειας">{links}</nav></div>'


def theme_css(light, dark, print_=None):
    """Colour tokens, each written once with light-dark(): light is the default; the toggle sets
    data-theme; print is always light, with `print_` overriding single tokens."""
    def decl(t):
        return ";".join(f"--{k}:{v}" for k, v in t.items())
    both = {k: f"light-dark({v},{dark[k]})" if dark.get(k, v) != v else v for k, v in light.items()}
    out = (f":root{{color-scheme:light;{decl(both)}}}\n"
           ":root[data-theme=light]{color-scheme:light}\n:root[data-theme=dark]{color-scheme:dark}\n")
    if print_ is not None:
        out += f"@media print{{:root,:root[data-theme]{{color-scheme:light;{decl(print_)}}}}}\n"
    return out


# Map pages: warm grays, a purple sequential ramp (s0-s6; blue is ND's colour, so no ramp uses it) and a red-gray-blue diverging one (d-3..d3).
MAP_LIGHT = {"surface": "#fbfaf6", "ink": "#1d1d1b", "ink-2": "#46453f", "line": "#d9d6cc", "chip": "#f1efe6", "shadow": "rgba(0,0,0,.18)",
             "s0": "#f3eef8", "s1": "#dccbea", "s2": "#bda0d6", "s3": "#9c78bf", "s4": "#7a4fa8", "s5": "#5a2f8a", "s6": "#3a1866",
             "scrim": "rgba(0,0,0,.5)", "on-scrim": "#fff",
             "link": "#1f4e9c", "d-3": "#a8302e", "d-2": "#e0736b", "d-1": "#f6c4c0", "d0": "#d9d6cc", "d1": "#9ec5f4", "d2": "#3987e5",
             "d3": "#104281"}
MAP_DARK = {"surface": "#15171b", "ink": "#ecebe7", "ink-2": "#c2c1bc", "line": "#33363c", "chip": "#1e2128",
            "shadow": "rgba(0,0,0,.5)", "d0": "#5a5955", "link": "#8fb0f0",
            # dark: more votes is lighter, so the strongest areas stand out from the dark surface (3:1 or better from s3 up)
            "s0": "#2b2437", "s1": "#4a3870", "s2": "#6b4f9e", "s3": "#8d6dc4", "s4": "#ab8ddc", "s5": "#c8b2ee", "s6": "#e6dbf8",
            "d-3": "#ff9a92", "d-2": "#e0736b", "d-1": "#a45a56", "d1": "#4f7dbd", "d2": "#6aa3ee", "d3": "#a8cdfb"}  # dark: scrim and on-scrim stay as in light
# Index: cool paper and ink, one blue pen.
INDEX_LIGHT = {"paper": "#fbfaf6", "ink": "#1d1d1b", "ink-2": "#46453f", "line": "#d9d6cc", "pen": "#1f4e9c", "wash": "#f1efe6"}
INDEX_DARK = {"paper": "#15171b", "ink": "#ecebe7", "ink-2": "#c2c1bc", "line": "#33363c", "pen": "#8fb0f0", "wash": "#1e2128"}


def fill(page, light=MAP_LIGHT, dark=MAP_DARK, print_=None, current="maps", ctx="", skip="#main", compact=False, sources=""):
    """Shared parts of every page: colour tokens, site CSS and theme script, fonts, header, footer."""
    for placeholder, text in (("/*THEME_TOKENS*/", theme_css(light, dark, print_)),
                              ("/*SITE_CSS*/", (HERE / "fonts.css").read_text(encoding="utf-8") + (HERE / "site.css").read_text(encoding="utf-8")),
                              ("/*THEME_JS*/", (HERE / "theme.js").read_text(encoding="utf-8")),
                              ("/*SHARED_JS*/", (HERE / "shared.js").read_text(encoding="utf-8")),
                              ("<!--FONTS-->", FONTS), ("<!--HEADER-->", header(current, ctx, skip)), ("<!--FOOTER-->", footer(compact=compact, sources=sources))):
        page = page.replace(placeholder, text)
    return page


def meta(title, description):
    """Description, Open Graph and Twitter card tags. The picture and address tags come from secure(), which knows the file;
    without SITE_URL there is no picture, so the card is "summary"."""
    t, d = html.escape(title, quote=True), html.escape(description, quote=True)
    return (f'<meta name="description" content="{d}"><meta property="og:type" content="website">'
            f'<meta property="og:site_name" content="Χάρτες σταυρών"><meta property="og:locale" content="el_GR">'
            f'<meta property="og:title" content="{t}"><meta property="og:description" content="{d}">'
            f'<meta name="twitter:card" content="{"summary_large_image" if SITE_URL else "summary"}">')

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40' fill='none' stroke='%231f4e9c' "
           "stroke-width='3' stroke-linecap='round'%3E%3Crect x='3' y='3' width='34' height='34' rx='3'/%3E"
           "%3Cpath d='M11 12C16 17 22 24 29 29M28 11C23 16 17 23 12 30'/%3E%3C/svg%3E")  # the site mark; img-src allows data:

LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/"  # for pages written outside out/: no vendor/ folder beside them


def secure(page, path=None):
    """Content-Security-Policy (as a <meta>: GitHub Pages sets no headers), referrer policy, favicon and, when config.SITE_URL
    is set, the page's canonical address, og:url and og:image (`path` = the file the page is written to; one outside out/ gets none).
    Call it last, on the finished page: the inline scripts and styles are allowed by their SHA-256 hash, so injected markup cannot run.
    Leaflet (pinned by integrity=) and the fonts are self-hosted in out/, so only the OSM tiles come from outside. A page written
    anywhere else (a client's map, `path` None) has no vendor/ folder beside it: its Leaflet link and CSP point to cdnjs instead."""
    home = path is not None and Path(path).resolve().parent == OUT.resolve()
    if not home:
        page = page.replace("vendor/leaflet-1.9.4/", LEAFLET)
    js, css = ("'self'",) * 2 if home else (LEAFLET + "leaflet.min.js", LEAFLET + "leaflet.min.css")
    def hashes(tag):
        return [f"'sha256-{base64.b64encode(hashlib.sha256(m.encode()).digest()).decode()}'"
                for m in re.findall(rf"<{tag}>(.*?)</{tag}>", page, re.S)]
    csp = "; ".join([
        "default-src 'none'",
        " ".join(["script-src", *hashes("script"), js]),
        " ".join(["style-src-elem", *hashes("style"), css]),
        "style-src-attr 'unsafe-inline'",  # style="" in markup the pages build (legend swatches, table cells)
        "font-src 'self'",
        "img-src 'self' data: https://tile.openstreetmap.org",
        "connect-src 'none'", "base-uri 'none'", "form-action 'none'", "object-src 'none'", "frame-src 'none'"])
    tags = (f'<meta http-equiv="Content-Security-Policy" content="{csp}"><meta name="referrer" content="strict-origin-when-cross-origin">'
            f'<meta name="robots" content="noindex, nofollow, noarchive">'  # the X-Robots-Tag header in vercel.json says the same; no robots.txt Disallow, or crawlers never see this
            f'<link rel="icon" href="{FAVICON}">')
    if SITE_URL and home:  # pages outside out/ are not published
        url = f"{SITE_URL}/out/{urllib.parse.quote(Path(path).name)}"
        kind = og_kind(Path(path).name)
        img = f"{SITE_URL}/out/og/{kind}.png"
        alt = re.search(r'property="og:title" content="([^"]*)"', page)  # already escaped; the picture says the same
        tags += (f'<link rel="canonical" href="{url}"><meta property="og:url" content="{url}">'
                 f'<meta property="og:image" content="{img}"><meta property="og:image:width" content="1200">'
                 f'<meta property="og:image:height" content="630"><meta property="og:image:alt" content="{alt[1] if alt else "Χάρτες σταυρών"}">'
                 f'<meta name="twitter:image" content="{img}">')
    return page.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + tags, 1)

def common_css():
    return fill((HERE / "common.css").read_text(encoding="utf-8"), print_={"surface": "#fff"})


def render_page(template, data, path=None):
    """Template with the shared UI (common.css/js, theme, header, footer) and the page data inlined: one self-contained file.
    `path` is the file the page is written to (see secure())."""
    page = (HERE / template).read_text(encoding="utf-8")
    page = fill(page.replace("/*COMMON_CSS*/", common_css()).replace("/*COMMON_JS*/", (HERE / "common.js").read_text(encoding="utf-8")),
                ctx=context_row(data), skip="#map")
    data = {**data, "election_title": ELECTIONS[data["election"]][1]}
    kind = "Ψήφοι κομμάτων" if data.get("mode") == "party" else "Σταυροί προτίμησης"
    unit = "εκλογικό τμήμα" if "venues" in data else "εκλογικό διαμέρισμα"
    et = data["election_title"]
    page = page.replace("<!--META-->", meta(f"{kind}, {data['ep_name']}",
                                            f"{kind} ανά {unit}, {data['ep_name']}, {et[0].lower() + et[1:]}."))
    return secure(page.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False)), path)  # last: data may contain anything


# A ballpoint cross in a ballot box, the mark a voter puts next to a candidate: the one decorative element of the site.
TOP_KEY = "Πρώτος σε σταυρούς"  # screen-reader prefix of each row's leading candidate, followed by the election

def greece_figure(areas, key, caption, size=440):
    """Static map of Greece for the index: `areas` = [(GeoJSON geometry, colour)], `key` = [(name, colour)].
    One path per colour; neighbouring areas keep their own outline, simplified to whole units. The colours are
    declared once as custom properties in the figure's own <style>, so no colour is written on an element."""
    to_xy, w, h = frame([g for g, _ in areas], size)
    by_color = defaultdict(list)
    for g, color in areas:
        by_color[color].extend(exteriors(g))
    tok = {c: f"g{i}" for i, c in enumerate(dict.fromkeys([*by_color, *(c for _, c in key)]))}
    style = (":root{" + ";".join(f"--{t}:{c}" for c, t in tok.items()) + "}"
             + "".join(f".gr .{t}{{fill:var(--{t});stroke:var(--{t})}}.gr i.{t}{{background:var(--{t})}}" for t in tok.values()))
    paths = "".join(f'<path class="{tok[c]}" d="{path(rings, to_xy, 0.8, 1.0)}"/>' for c, rings in by_color.items())
    swatches = "".join(f'<span class="k"><i class="{tok[c]}"></i>{html.escape(n)}</span>' for n, c in key)
    # the map itself opens the comparison; the index's "Σύγκριση εκλογών" tile says it in words
    return (f'<figure class="gr"><style>{style}</style><a href="compare.html"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(caption)}">'
            f'<g stroke-width=".6" stroke-linejoin="round">{paths}</g></svg></a>'
            f'<figcaption>{html.escape(caption)}.<span class="keys">{swatches}</span></figcaption></figure>')

INDEX_CSS = """
/* Hallmark · shape: 20 Ecosystem Index · genre: editorial · theme: brand · redesign: full · job: find a constituency's map
 * paper: #fbfaf6 · accent: #1f4e9c · display: IBM Plex Sans · body: IBM Plex Sans · hero: Stage · nav: kept (the site bar every page shares) · footer: kept (the site colophon) · signature: the map of Greece by first party, beside the search
 * axes: paper/plex/pen · posture: Restrained · contrast: pass · fold: pass · v2.0.0 */
/* Hallmark · pre-emit critique: P3 H5 E4 S4 R4 V4 · weakest: P, a reference page argues little; it leads with the search and the map so the first screen says find your constituency */
/* Hallmark · dropped "Για κόμματα και υποψηφίους" · the section is headed by the party it is about, ΝΙΚΗ */
/* Hallmark · waive 24b · site.css .ctx nav, .site h3, .site.compact, .copyfield · the off-scale gaps belong to the bar and colophon every map page shares, kept as found */
/* Hallmark · waive 39b · site.css .site .copy, 24px · the colophon's copy-link button is shared chrome, kept as found; its target meets WCAG 2.5.8 */
/* Hallmark · waive 49b · .tool h3 a, .nk a, .dl a at 320px · these links are headings set large across a whole tile; a heading may wrap */
/* Hallmark · reworded "Πρόβλεψη εκλογών →" to "Πρόβλεψη εκλογών" · 63 names the glued arrow */
/* Hallmark · reworded "Σύγκριση εκλογών →" to "Σύγκριση εκλογών" · 63 names the glued arrow */
/* Hallmark · reworded "Εξωτερικό και επιστολική ψήφος →" to "Εξωτερικό και επιστολική ψήφος" · 63 names the glued arrow */
/* Hallmark · reworded "Εκλεγμένοι Μαΐου–Ιουνίου 2023" to "Εκλεγμένοι Μαΐου και Ιουνίου 2023" · 19 names the dash; "2019–2024" to "2019 έως 2024" the same */
/* Hallmark · reworded the figures line "59 εκλογικές περιφέρειες · 4 εκλογές · …" to one sentence · 63 names the middle dots */
/*THEME_TOKENS*/
:root{
  --font-body:"IBM Plex Sans",system-ui,sans-serif;
  --space-2xs:4px;--space-xs:8px;--space-sm:12px;--space-md:16px;--space-lg:24px;--space-xl:40px;--space-2xl:64px;--space-3xl:96px;
  --text-display:clamp(2.75rem,5vw + 1rem,5.25rem);--text-section:clamp(2rem,2.5vw + 1rem,3.5rem);--text-2xl:clamp(1.5rem,1vw + 1.1rem,1.953rem);
  --text-title:clamp(1.25rem,.75vw + .875rem,1.625rem);--text-lead:clamp(1.125rem,.35vw + 1rem,1.375rem);
  --container:1440px;--gutter:64px;--gap-columns:32px;--section-gap-s:120px;--section-gap:144px;--section-gap-l:176px;
  accent-color:var(--pen)}
@media (max-width:60rem){:root{--gutter:24px;--section-gap-s:80px;--section-gap:96px;--section-gap-l:120px}}
@media (max-width:40rem){:root{--gutter:16px;--section-gap-s:56px;--section-gap:72px;--section-gap-l:96px;--gap-columns:16px}}
/*SITE_CSS*/
*,*::before,*::after{box-sizing:border-box}
html{scrollbar-gutter:stable}
html,body{overflow-x:clip}
body{margin:0;background:var(--paper);color:var(--ink);font:1rem/1.55 var(--font-body)}
a{color:var(--pen)}
:focus-visible{outline:2px solid var(--pen);outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.container{width:100%;max-width:var(--container);margin-inline:auto;padding-inline:var(--gutter)}
h1,h2,h3{margin:0;font-family:var(--font-body);font-weight:600;letter-spacing:-.02em;line-height:1.05;overflow-wrap:break-word;min-width:0;text-wrap:balance}
h1{max-width:12ch;font-size:var(--text-display)}
h2{max-width:20ch;font-size:var(--text-section)}
h3{font-size:var(--text-title);line-height:1.2}
.lead{margin:0;max-width:40ch;font-size:var(--text-lead);line-height:1.45;color:var(--ink-2)}
:root{--xm:polygon(14% 0,50% 36%,86% 0,100% 14%,64% 50%,100% 86%,86% 100%,50% 64%,14% 100%,0 86%,36% 50%,0 14%)}
/* the cross marks what is chosen: the open election, the leading candidate of a row */
:is(.sw button[aria-pressed=true],.eps .who b)::before{content:"";display:inline-block;width:.6em;height:.6em;margin-right:var(--space-2xs);background:currentColor;clip-path:var(--xm)}
/* Hero (Stage): title, one sentence and the search on five columns, the map on seven */
.hero{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);column-gap:var(--space-3xl);align-items:center;min-height:calc(100svh - 96px);padding-block:var(--space-xl) var(--space-2xl)}
.hero .lead{margin-top:var(--space-lg)}
#s{margin-top:var(--space-xl)}
.fl{display:block;margin:0 0 var(--space-xs);font-size:var(--t-sm);font-weight:600;color:var(--ink)}
.sf{position:relative}
#f{width:100%;min-height:56px;font:inherit;font-size:var(--text-lead);color:var(--ink);background:var(--paper);
   border:1.5px solid var(--ink-2);border-radius:8px;padding:var(--space-sm) var(--space-md) var(--space-sm) 52px}
#f::placeholder{color:var(--ink-2)}
#f:focus-visible{outline:2px solid var(--pen);outline-offset:2px;border-color:var(--pen)}
.sf::before{content:"";position:absolute;left:var(--space-md);top:18px;width:20px;height:20px;background:var(--ink-2);-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='8.5' cy='8.5' r='5.5'/%3E%3Cpath d='M13 13l4.5 4.5'/%3E%3C/svg%3E") center/contain no-repeat;mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='8.5' cy='8.5' r='5.5'/%3E%3Cpath d='M13 13l4.5 4.5'/%3E%3C/svg%3E") center/contain no-repeat;pointer-events:none;z-index:1}
#n{margin:var(--space-xs) 0 0;color:var(--ink-2);font-size:var(--t-sm)}
#n:empty{display:none}
.try{margin:var(--space-md) 0 0;font-size:var(--t-base)}
.try a{display:inline-flex;align-items:center;min-height:44px;color:var(--ink);text-underline-offset:4px}
.try a:hover{color:var(--pen)}
.sug{position:absolute;left:0;right:0;top:100%;z-index:20;list-style:none;margin:var(--space-2xs) 0 0;padding:var(--space-2xs);background:var(--paper);border:1px solid var(--line);border-radius:8px}
.sug a{display:grid;gap:var(--space-2xs);padding:var(--space-sm);min-height:44px;color:var(--ink);text-decoration:none;border-radius:6px}
.sug a b{font-size:var(--t-lg);font-weight:600;line-height:1.25}
.sug a span{color:var(--ink-2);font-size:var(--t-sm)}
.sug a.act,.sug a:hover{background:var(--wash)}
.sug a.more{min-height:36px;color:var(--pen);font-size:var(--t-sm)}
.gr{margin:0}
.gr a:first-child{display:block;border-radius:8px}
.gr a:first-child:hover svg{opacity:.88}
.gr svg{display:block;width:100%;height:auto;max-height:min(72svh,680px);margin-inline:auto}
.gr figcaption{margin:var(--space-sm) 0 0;font-size:var(--t-sm);color:var(--ink-2)}
.gr .keys{display:flex;flex-wrap:wrap;gap:var(--space-2xs) var(--space-md);margin-top:var(--space-xs)}
.gr .k{display:inline-flex;align-items:center;gap:var(--space-xs);white-space:nowrap}
.gr .k i{display:inline-block;width:12px;height:12px;border-radius:2px;box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ink-2) 75%,var(--paper))}
/* Sections: head block, then the body; each parts from the last by a different step */
.sec{padding-top:var(--section-gap)}
.sec.l{padding-top:var(--section-gap-l)}
.head{display:grid;grid-template-columns:minmax(0,6fr) minmax(0,6fr);column-gap:var(--gap-columns);align-items:end;margin-bottom:var(--space-2xl)}
.head .lead{max-width:44ch}
/* Όλη η χώρα: three tools across, each a whole-tile link under a heavy rule */
.tools{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--gap-columns)}
.tool{position:relative;display:flex;flex-direction:column;gap:var(--space-md);min-height:240px;padding-top:var(--space-lg);border-top:3px solid var(--ink)}
.tool h3{font-size:var(--text-2xl)}
.tool h3 a{color:var(--ink);text-decoration:none}
.tool h3 a::after{content:"";position:absolute;inset:0}
.tool:hover h3 a{text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:6px}
.tool:hover{border-top-color:var(--pen)}
.tool p{margin:0;max-width:34ch;color:var(--ink-2);font-size:var(--t-lg);line-height:1.45}
.tool:has(a:active){background:var(--wash)}
/* Εκλογικές περιφέρειες: the region name beside its rows, held in view while its rows scroll */
.ctl{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-xs);margin-bottom:var(--space-xl);font-size:var(--t-base);color:var(--ink-2)}
.ctl[hidden]{display:none}
.ctl .swl{margin-right:var(--space-xs)}
.sw{display:contents}
.sw button{font:inherit;color:var(--ink-2);background:none;border:1px solid var(--line);border-radius:22px;padding:0 var(--space-md);min-height:44px;cursor:pointer}
.sw button:hover{color:var(--pen);border-color:var(--ink-2)}
.sw button:active{background:var(--wash)}
.sw button:disabled{opacity:.5;cursor:not-allowed}
.sw button[aria-pressed=true]{color:var(--pen);border-color:var(--pen);background:var(--wash);font-weight:600}
.rows{display:grid;grid-template-columns:44px minmax(0,1fr) minmax(0,1.15fr) 6.5rem;column-gap:var(--space-lg)}
.lhw{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,9fr);column-gap:var(--gap-columns)}
.lh{grid-column:2;margin:0;padding-bottom:var(--space-sm);font-size:var(--t-sm);color:var(--ink-2)}
.lh span:nth-child(1){grid-column:2}.lh span:nth-child(2){grid-column:3}.lh span:nth-child(3){grid-column:4;text-align:right}
.grp{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,9fr);column-gap:var(--gap-columns);padding-block:var(--space-lg) var(--space-xl);border-top:2px solid var(--ink)}
.grp:not(:has(li:not([hidden]))){display:none}  /* a region goes with its rows */
.reg{position:sticky;top:var(--space-lg);align-self:start;max-width:14ch;padding-top:var(--space-sm);scroll-margin-top:var(--space-lg)}
.eps{list-style:none;margin:0;padding:0}
.eps li{align-items:center;row-gap:var(--space-2xs);position:relative;min-height:72px;padding-block:var(--space-md);border-top:1px solid var(--line);overflow-wrap:break-word;scroll-margin-top:var(--space-lg)}
.eps li:first-child{border-top:0}
.eps li:hover{background:var(--wash)}
.sil{grid-column:1;grid-row:1;width:44px;height:44px;color:var(--ink-2)}
.sil path{fill:currentColor;fill-opacity:.22;stroke:currentColor;stroke-width:1;stroke-linejoin:round}
.eps h4{grid-column:2;grid-row:1;margin:0;font-size:var(--t-lg);font-weight:600;line-height:1.25}
.eps h4 a{color:var(--ink);text-decoration:none}
.eps h4 a:hover{text-decoration:underline;text-underline-offset:4px}
.eps h4 a::after{content:"";position:absolute;inset:0}  /* the whole row opens the map */
.top{display:contents}
.top[hidden]{display:none}
.who{grid-column:3;grid-row:1;color:var(--ink-2)}
.who b{color:var(--ink);font-weight:600}
.vt{grid-column:4;grid-row:1;text-align:right;font-size:var(--t-lg);font-variant-numeric:tabular-nums;white-space:nowrap}
.eps .dhm{grid-column:2/4;grid-row:2;position:relative;margin:0;max-width:75ch;color:var(--ink-2);font-size:var(--t-sm);line-height:1.5}
.acts{grid-column:2/-1;grid-row:3;position:relative;display:flex;flex-wrap:wrap;align-items:center;gap:0 var(--space-md);margin-top:var(--space-2xs)}  /* every election, until the switcher takes over */
body.pick .acts{display:none}
.older summary,.fold summary{display:flex;align-items:center;min-height:44px;cursor:pointer;color:var(--ink-2)}
.older[open]{flex:1 1 100%}
.el{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2xs) var(--space-md);margin:0}
.el a{display:inline-flex;align-items:center;min-height:44px;color:var(--ink-2);white-space:nowrap;text-decoration-color:var(--line);text-underline-offset:3px}
.el a:hover{color:var(--pen);text-decoration-color:var(--pen)}
.el a.now{padding:0 var(--space-md);border:1px solid var(--pen);border-radius:22px;color:var(--pen);background:var(--wash);text-decoration:none;font-weight:600}
/* ΝΙΚΗ: a change of paper, four reports across */
.band{margin-top:var(--section-gap);padding-block:var(--section-gap-s);background:var(--wash)}
.nk{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--gap-columns);list-style:none;margin:0;padding:0}
.nk li{position:relative;display:flex;flex-direction:column;gap:var(--space-sm);min-height:144px;padding-top:var(--space-lg);border-top:2px solid var(--ink)}
.nk a{color:var(--ink);font-size:var(--text-title);font-weight:600;line-height:1.25;text-decoration:none}
.nk a::after{content:"";position:absolute;inset:0}
.nk li:hover a{text-decoration:underline;text-underline-offset:5px}
.nk li:hover{border-top-color:var(--pen)}
.nk span{color:var(--ink-2)}
.fold{margin-top:var(--space-xl);border-top:1px solid var(--line);padding-top:var(--space-sm)}
.fold summary{font-size:var(--t-lg);color:var(--ink)}
.fold summary::before{content:"+";display:inline-block;width:1.25em;font-size:var(--t-xl);line-height:1;transition:transform .15s}
.fold[open]>summary::before{transform:rotate(45deg)}
.fold ul{columns:3 260px;column-gap:var(--gap-columns);list-style:none;margin:var(--space-md) 0 0;padding:0}
.fold li{break-inside:avoid;padding-block:var(--space-xs)}
.fold li a{color:var(--ink);font-weight:600}
.fold li span{display:block;color:var(--ink-2);font-size:var(--t-sm)}
/* Δεδομένα και κάλυψη: the head beside five rows */
.data{display:grid;grid-template-columns:minmax(0,4fr) minmax(0,8fr);column-gap:var(--gap-columns);align-items:start}
.data .lead{margin-top:var(--space-md)}
.dl{list-style:none;margin:0;padding:0;border-top:2px solid var(--ink)}
.dl li{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;column-gap:var(--space-lg);min-height:72px;border-bottom:1px solid var(--line)}
.dl a{color:var(--ink);font-size:var(--text-title);font-weight:600;text-decoration:none}
.dl a::after{content:"";position:absolute;inset:0}
.dl li:hover a{text-decoration:underline;text-underline-offset:5px}
.dl li:hover{background:var(--wash)}
.dl span{color:var(--ink-2);font-size:var(--t-sm)}
.foot{padding-top:var(--section-gap-s)}
.pg-a:active,.eps li a:active,.older summary:active,.fold summary:active{background:var(--wash)}
.older[open]>:not(summary),.fold[open]>:not(summary){animation:fade .15s ease-out}
@keyframes fade{from{opacity:0}}
@media (prefers-reduced-motion:reduce){.fold summary::before{transition:none}.older[open]>:not(summary),.fold[open]>:not(summary){animation:none}}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
body:has(#f:not(:placeholder-shown)) :is(#country,.band,#cov){display:none}  /* while searching, the rows come right after the first screen */
@media (max-width:60rem){
  .hero{grid-template-columns:minmax(0,1fr);row-gap:var(--space-xl);min-height:0}
  .head,.data,.grp,.lhw{grid-template-columns:minmax(0,1fr)}
  .head{row-gap:var(--space-md);margin-bottom:var(--space-xl)}
  .tools{grid-template-columns:minmax(0,1fr)}
  .tool{min-height:0;padding-bottom:var(--space-lg)}
  .lh{display:none}
  .reg{position:static;max-width:none;padding-block:0 var(--space-xs)}
  .rows{grid-template-columns:36px minmax(0,1fr);column-gap:var(--space-md)}
  .sil{width:36px;height:36px;grid-row:1/3;align-self:start}
  .who{grid-column:2;grid-row:2}
  .vt{grid-column:2;grid-row:3;text-align:left;font-size:var(--t-base);color:var(--ink-2)}
  .vt::after{content:" σταυροί"}
  .eps .dhm{grid-column:2;grid-row:4}
  .acts{grid-row:5;grid-column:2}
  .data .dl{margin-top:var(--space-xl)}
}
@media (max-width:40rem){.nk{grid-template-columns:minmax(0,1fr)}.nk li{min-height:0;padding-bottom:var(--space-md)}#f{font-size:var(--t-base);padding-left:44px}#f::placeholder{font-size:var(--t-sm)}.sf::before{left:var(--space-sm)}}
"""
INDEX_JS = """
document.getElementById("s").hidden = false;
const f = document.getElementById("f"), n = document.getElementById("n"), items = [...document.querySelectorAll(".eps li")];
const words = new Map(items.map(li => [li, li.dataset.k.split(" ").map(w => [w, key(w)])]));
const own = li => words.get(li).slice(0, +li.dataset.n);  // the constituency's own name, ahead of its towns
const sug = document.getElementById("sug");
let act = -1;
const setAct = i => {
  const opts = [...sug.querySelectorAll("a[role=option]")];
  act = opts.length ? (i + opts.length) % opts.length : -1;
  opts.forEach((o, k) => o.classList.toggle("act", k === act));
  act >= 0 ? f.setAttribute("aria-activedescendant", opts[act].id) : f.removeAttribute("aria-activedescendant");
};
const closeSug = () => { sug.hidden = true; f.setAttribute("aria-expanded", "false"); setAct(-1); };
// Up to 6 constituencies under the field: the name, its region and its first candidate; the rest stay in the list below.
const suggest = (shown, total) => {
  sug.replaceChildren();
  shown.slice(0, 6).forEach((li, i) => {
    const a = document.createElement("a"), b = document.createElement("b"), s = document.createElement("span");
    a.id = "o" + i; a.href = li.querySelector("h4 a").href; a.setAttribute("role", "option");
    b.textContent = li.querySelector("h4 a").textContent;
    s.textContent = [li.closest(".grp").querySelector(".reg").textContent, (li.querySelector(".top:not([hidden]) .who") || {}).textContent].filter(Boolean).join(", ");
    a.append(b, s); const item = document.createElement("li"); item.setAttribute("role", "presentation"); item.append(a); sug.append(item);
  });
  if (total > 6) {
    const a = document.createElement("a"), item = document.createElement("li");
    a.className = "more"; a.href = "#regions"; a.textContent = `και ${total - 6} ακόμη στη λίστα`; a.addEventListener("click", closeSug);
    item.append(a); sug.append(item);
  }
  const any = shown.length > 0;
  sug.hidden = !any; f.setAttribute("aria-expanded", String(any)); setAct(-1);
};
f.addEventListener("input", () => {
  const qs = queryWords(f.value);
  let shown = 0;
  for (const li of items) {
    const hit = qs.every(q => hits(words.get(li), q)); li.hidden = !hit; shown += hit;
    li.style.order = hit && qs.length && !qs.every(q => hits(own(li), q)) ? 1 : "";  // name matches first
  }
  for (const li of items) { const d = li.querySelector("details"); if (d) d.open = shown === 1 && !li.hidden; }  // the one match shows its older maps
  const ranked = items.filter(li => !li.hidden).sort((a, b) => (+a.style.order || 0) - (+b.style.order || 0));
  qs.length ? suggest(ranked, shown) : closeSug();
  n.textContent = !qs.length ? "" : !shown ? `Καμία περιφέρεια με «${f.value.trim()}». Δοκίμασε το όνομα του δήμου ή του νομού.`
    : shown === 1 ? "1 περιφέρεια. Enter για τον χάρτη της." : `${shown} περιφέρειες`;
});
// Election switcher: every row's name opens the chosen election; its line shows the first candidate of that election,
// or of the newest earlier one with per-candidate crosses (data-x), named in #tk. Without script each row lists all its elections.
const sw = document.querySelector(".sw"), ctl = document.querySelector(".ctl");
const open = e => {
  let x = "";
  sw.querySelectorAll("button").forEach(b => { b.setAttribute("aria-pressed", b.dataset.e === e); if (b.dataset.e === e) x = b.dataset.x; });
  const tk = document.getElementById("tk"), xb = sw.querySelector(`button[data-e="${x}"]`);
  if (tk) { tk.hidden = !xb; if (xb) tk.querySelector(".te").textContent = xb.textContent; }
  for (const li of items) {
    li.querySelector("h4 a").href = (li.querySelector(`.el a[data-e="${e}"]`) || li.querySelector(".el a")).href;
    li.querySelectorAll(".top").forEach(p => { p.hidden = p.dataset.e !== x; });
  }
};
sw.addEventListener("click", ev => { const b = ev.target.closest("button"); if (b) open(b.dataset.e); });
ctl.hidden = false;
document.body.classList.add("pick");
open(sw.dataset.d);
document.addEventListener("click", e => { if (!e.target.closest(".sf")) closeSug(); });
f.addEventListener("focus", () => { if (f.value.trim()) f.dispatchEvent(new Event("input")); });
f.addEventListener("keydown", e => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { if (!sug.hidden) { e.preventDefault(); setAct(act + (e.key === "ArrowDown" ? 1 : -1)); } return; }
  if (e.key === "Escape") { closeSug(); return; }
  if (e.key === "Enter" && act >= 0) { e.preventDefault(); location.href = sug.querySelectorAll("a[role=option]")[act].href; return; }
  const shown = items.filter(li => !li.hidden).sort((a, b) => (+a.style.order || 0) - (+b.style.order || 0));
  if (e.key === "Enter" && f.value.trim() && (shown.length === 1 || +shown[1].style.order > +shown[0].style.order)) location.href = shown[0].querySelector("h4 a").href;
});
"""


def card(ep, name, keys, n_own, lead, note, chips, href, sil=""):
    """One constituency row. The name opens the default election (the switcher retargets it); `chips` are the
    election links, newest first: without script they show in the row, the older ones folded into a <details>.
    `lead` is one line per election with crosses (the switcher shows one); `note` is the optional list of municipalities."""
    now, *older = chips
    folded = (f'<details class="older"><summary>Παλαιότερες εκλογές ({len(older)})</summary>'
              f'<p class="el">{"".join(older)}</p></details>') if older else ""
    return (f'<li id="ep-{ep}" class="rows" data-k="{html.escape(keys)}" data-n="{n_own}"><h4><a href="{href}">{html.escape(name)}</a></h4>'
            f'{sil}{lead}{note}<div class="acts"><p class="el">{now}</p>{folded}</div></li>')

def _write_index(order, nikh, elected):
    """out/index.html: the search beside the map of Greece, the nationwide tools, every constituency (its region beside
    its rows, one link per election), the ΝΙΚΗ reports, and the coverage pages with the data to download."""
    def fold(s):
        return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()

    def dots(n):
        return f"{n:,}".replace(",", ".")

    # Municipalities (δήμοι) and municipal units of each constituency: search aliases, so a voter can type a town.
    dhm, den = defaultdict(dict), defaultdict(set)
    if DB.exists():
        with sqlite3.connect(DB) as con:
            for e, ep, d, u in con.execute("SELECT DISTINCT election, ep_id, dhm_descr, den_descr FROM station WHERE kind = 'Κ'"):
                dhm[e, ep][d] = None
                den[e, ep].add(u)
    # The candidate with the most crosses, per election and constituency. June 2023 has a few constituencies only (party
    # leaders' totals) and Euro 2024 none: those elections show the newest earlier election that has them all (`crosses_of`).
    top = {}
    if DB.exists():
        with sqlite3.connect(DB) as con:
            for e, ep, cand, pid, party, votes in con.execute(
                    "SELECT t.election, t.ep_id, c.name, p.party_id, p.name, MAX(t.votes) FROM ep_total t "
                    "JOIN candidate c USING(election, ep_id, party_id, cand_id) JOIN party p USING(election, party_id) "
                    "WHERE t.cand_id > 0 AND t.votes > 0 GROUP BY t.election, t.ep_id"):
                top[e, ep] = (cand, PARTY_SHORT.get(pid, party), votes)
    # Rows open the newest parliamentary election by default: the one the forecast and the candidates are about.
    default = next(e for e in reversed(ELECTIONS) if source(e)[1] == "v")
    per = Counter(e for e, _ in top)
    crossed = [e for e in ELECTIONS if per[e] and per[e] >= 0.9 * max(per.values())]
    crosses_of = {e: next((c for c in reversed(crossed) if list(ELECTIONS).index(c) <= list(ELECTIONS).index(e)), "") for e in ELECTIONS}
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
        # The newest election is the first link; the others are quieter. The name in each link is for screen readers.
        chips = [
            f'<a{" class=now" if i == 0 else ""} data-e="{m["election"]}" href="{urllib.parse.quote(f)}">'
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
        # The cross marks the candidate with the most crosses: the one mark on the page that carries data.
        # Name and crosses sit in their own columns, headed once above the list.
        lead = "".join(
            f'<p class="top" data-e="{m["election"]}"{"" if m["election"] == crosses_of[default] else " hidden"}>'
            f'<span class="who"><span class="sr">{TOP_KEY}, {ELECTION_NAMES[m["election"]]}: </span><b>{html.escape(t[0])}</b> '
            f'({html.escape(t[1])})</span><span class="vt">{dots(t[2])}<span class="sr"> σταυροί</span></span></p>'
            for _, m in reversed(links) if m["election"] in crossed and (t := top.get((m["election"], m["ep"]))))
        first = next((f for f, m in links if m["election"] == default), links[-1][0])
        by_region.setdefault(region_of.get(latest["ep"], "Λοιπές"), []).append(
            card(latest["ep"], name, k, len(own), lead, note, chips, urllib.parse.quote(first), latest.get("sil", "")))
    # the link name carries the note beside it, so two links to the same constituency read differently in a list of links
    nikh_rows = "".join(
        (lambda note: f'<li><a href="{urllib.parse.quote(f)}" aria-label="{html.escape(m["ep_name"])}, {note}">{html.escape(m["ep_name"])}</a> <span>{note}</span></li>')(
            ELECTION_NAMES.get(m["election"], m["election"])
            + (", " + html.escape(elected[m["ep"]]) if m["election"] == "2023/june" and m["ep"] in elected else ""))
        for f, m in nikh)
    nikh_rows += "".join(f'<li><a href="{urllib.parse.quote(f)}" aria-label="{html.escape(m["ep_name"])}, {html.escape(m["label"])}">{html.escape(m["ep_name"])}</a> <span>{html.escape(m["label"])}</span></li>'
                         for f, m in tm if "_tm_131-" not in f)
    groups = "".join(f'<section class="grp"><h3 class="reg" id="reg-{i}">{html.escape(region)}</h3><ul class="eps">{"".join(lis)}</ul></section>'
                     for i, (region, lis) in enumerate(by_region.items()) if lis)
    switch = "".join(f'<button type="button" data-e="{e}" data-x="{crosses_of[e]}" aria-pressed="false">{n}</button>' for e, n in reversed(ELECTION_NAMES.items()))
    # Column heads, said once; each row also carries them for screen readers.
    tk = (f'<div class="lhw" aria-hidden="true"><p class="lh rows" id="tk"><span>Εκλογική περιφέρεια</span>'
          f'<span>{TOP_KEY}, <span class="te">{ELECTION_NAMES[crosses_of[default]]}</span></span><span>Σταυροί</span></p></div>'
          if crosses_of[default] else "")
    gr = HERE / "out" / "greece_map.html"
    greece = gr.read_text(encoding="utf-8") if gr.exists() else ""  # written by compare.py
    nikh_n = nikh_rows.count("<li>")
    coverage = "".join(
        f'<li><a href="index_{e.replace("/", "-")}.html" aria-label="Κάλυψη χαρτών, {name}">{name}</a><span>Κάλυψη χαρτών</span></li>'
        for e, name in reversed(ELECTION_NAMES.items()) if (OUT / f'index_{e.replace("/", "-")}.html').exists())
    first_year, last = list(ELECTIONS)[0][:4], list(ELECTIONS)[-1]
    n_tm = None
    if DB.exists():
        with sqlite3.connect(DB) as con:
            n_tm = con.execute("SELECT COUNT(*) FROM station WHERE election=? AND kind='Κ'", (last,)).fetchone()[0]
    figs = [f"{len(eps)} εκλογικές περιφέρειες", f"{len(ELECTIONS)} εκλογές από το {first_year} έως το {last[:4]}"]
    figs += [f"{dots(n_tm)} εκλογικά τμήματα"] if n_tm else []
    nums = (", ".join(figs[:-1]) + " και " + figs[-1] + ".") if len(figs) > 1 else figs[0] + "."
    (OUT / "index.html").write_text(secure(fill(f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Χάρτες σταυρών</title>
{meta("Χάρτες σταυρών", "Χάρτες αποτελεσμάτων των ελληνικών εκλογών ανά κοινότητα και εκλογικό τμήμα.")}
{FONTS}
<script>/*THEME_JS*/</script>
<style>{INDEX_CSS}</style></head><body><main id="main">
<div class="container"><!--HEADER-->
<header class="hero">
<div>
<h1>Χάρτες σταυρών</h1>
<p class="lead">Πού ψηφίστηκε κάθε κόμμα και κάθε υποψήφιος, ανά κοινότητα και εκλογικό τμήμα.</p>
<div id="s" hidden><label class="fl" for="f">Αναζήτηση περιφέρειας</label>
<div class="sf"><input id="f" type="search" role="combobox" aria-expanded="false" aria-controls="sug" aria-autocomplete="list" placeholder="Δήμος ή νομός, π.χ. Πάτρα, Αργολίδα" autocomplete="off" enterkeyhint="search" spellcheck="false">
<ul id="sug" class="sug" role="listbox" aria-label="Προτάσεις" hidden></ul></div>
<p id="n" aria-live="polite"></p></div>
<p class="try"><a href="#regions">Όλες οι εκλογικές περιφέρειες</a></p>
</div>
{greece}
</header></div>
<section class="sec container" id="country" aria-labelledby="ct">
<div class="head"><h2 id="ct">Όλη η χώρα</h2></div>
<div class="tools">
<div class="tool"><h3><a href="forecast.html">Πρόβλεψη εκλογών</a></h3><p>Αυτοδυναμία, ποσοστά και έδρες από τον μέσο όρο των δημοσκοπήσεων.</p></div>
<div class="tool"><h3><a href="compare.html">Σύγκριση εκλογών</a></h3><p>Πρώτο κόμμα και ποσοστά ανά κοινότητα, από το {first_year} έως το {last[:4]}.</p></div>
<div class="tool"><h3><a href="abroad.html">Εξωτερικό και επιστολική ψήφος</a></h3><p>Πώς ψήφισαν οι Έλληνες του εξωτερικού ανά χώρα και πόλη, και όσοι ψήφισαν επιστολικά.</p></div>
</div></section>
<section class="sec l container" id="regions" aria-labelledby="rt">
<div class="head"><h2 id="rt">Εκλογικές περιφέρειες</h2><p class="lead">{nums}</p></div>
<div class="ctl" role="group" aria-label="Άνοιγμα στην εκλογή" hidden><span class="swl">Άνοιγμα στην εκλογή</span><div class="sw" data-d="{default}">{switch}</div></div>
{tk}
{groups}
</section>
<section class="band" aria-labelledby="pt"><div class="container">
<div class="head"><h2 id="pt">ΝΙΚΗ</h2><p class="lead">Αναφορές, χάρτες και δημοσκοπήσεις του κόμματος.</p></div>
<ul class="nk"><li><a href="NIKH_eklegmenoi_2023.html">Εκλεγμένοι Μαΐου και Ιουνίου 2023</a></li>
<li><a href="nikh_2023-2024.html">Όλη η χώρα ανά διαμέρισμα, 2019 έως 2024</a></li>
<li><a href="nikh_targets.html">Χάρτης στόχευσης</a><span>Κάστρα, φθορά, δεξαμενές, έδρες.</span></li>
<li><a href="nikh_polls.html">Στις δημοσκοπήσεις από το 2023</a></li></ul>
<details class="fold"><summary>Χάρτες ανά εκλογικό τμήμα ({nikh_n})</summary><ul>{nikh_rows}</ul></details>
</div></section>
<section class="sec container" id="cov" aria-labelledby="dt"><div class="data">
<div><h2 id="dt">Δεδομένα και κάλυψη</h2><p class="lead">Πόσοι ψήφοι αποδίδονται στον χάρτη, ανά νομό και εκλογή, και δεδομένα για λήψη.</p></div>
<ul class="dl">{coverage}<li><a href="../exports/NIKH_2023_ana_dhm_enotita.csv">ΝΙΚΗ 2023 ανά δημοτική ενότητα</a><span>Αρχείο CSV</span></li></ul>
</div></section>
<div class="container foot">
{footer(" Οι ψήφοι των ειδικών τμημάτων (ετεροδημότες κ.ά.), οι επιστολικές και οι ψήφοι του εξωτερικού δεν έχουν θέση στον χάρτη· οι αριθμοί τους είναι σε κάθε σελίδα «Κάλυψη χαρτών» και η ανάλυσή τους στη σελίδα «Εξωτερικό και επιστολική ψήφος».", home=False)}
</div>
</main><script>/*SHARED_JS*/</script><script>{INDEX_JS}</script></body></html>""", INDEX_LIGHT, INDEX_DARK, current="index"), OUT / "index.html"), encoding="utf-8")


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
