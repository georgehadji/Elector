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
    FORECAST_COLOURS,
    HERE,
    LEAFLET_SRI,
    LEAFLET_VERSION,
    NIKH,
    OUT,
    PARTY_COLOR,
    PARTY_SHORT,
    REGIONS,
    SITE_URL,
    og_kind,
    slug,
    source,
)
from analysis import seats_law as LAW  # the electoral law's figures: seats, majority, threshold
from geo import exteriors, frame, path
from matching import ep_label

# Site header and footer of every page. The toggle's pressed state means dark; theme.js keeps it in sync.
THEME_BTN = ('<button id="theme" type="button" aria-pressed="false" aria-label="Σκούρο θέμα"><svg viewBox="0 0 16 16" aria-hidden="true">'
             '<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 1.5v11a5.5 5.5 0 0 1 0-11z"/></svg></button>')
FONTS = "".join(f'<link rel="preload" href="fonts/{f}.woff2" as="font" type="font/woff2" crossorigin>'
                for f in ("ibm-plex-sans-greek", "ibm-plex-sans-latin", "literata-greek"))  # the @font-face rules are in fonts.css
MARK = ('<svg class="mark" viewBox="0 0 40 40" aria-hidden="true"><rect x="3" y="3" width="34" height="34" rx="3"/>'
        '<path d="M11 12 C16 17 22 24 29 29"/><path d="M28 11 C23 16 17 23 12 30"/></svg>')
NAV = (("index", "index.html", "Περιφέρειες"), ("compare", "compare.html", "Σύγκριση εκλογών"),
       ("forecast", "forecast.html", "Πρόβλεψη"), ("abroad", "abroad.html", "Εξωτερικό"))
MONTHS = ("Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου",
          "Ιουλίου", "Αυγούστου", "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου")


def nav(current="maps"):
    """The site's pages; `current` is one of NAV's keys (that page) or "maps", a page under Περιφέρειες (aria-current="true")."""
    cur = ("index", "true") if current == "maps" else (current, "page")
    links = "".join(f'<a href="{href}"' + (f' aria-current="{cur[1]}"' if cur[0] == key else "") + f">{label}</a>"
                    for key, href, label in NAV)
    return f'<nav aria-label="Κύριο μενού">{links}</nav>'

def header(current="maps", ctx="", skip="#main"):
    """Site bar: wordmark, nav, theme toggle, skip link; `ctx` is the wayfinding row of map pages."""
    to = "στον χάρτη" if skip == "#map" else "στο περιεχόμενο"
    home = f'<a class="home" href="index.html">{MARK}Χάρτες Ψήφων</a>'  # the same on every page, so the nav never moves
    return (f'<a class="skip" href="{skip}">Μετάβαση {to}</a><header class="bar{" with-ctx" if ctx else ""}">{home}'
            f'{nav(current)}{THEME_BTN}</header>{ctx}')


def footer(note="", home=True, compact=False, sources=""):
    """Site colophon: the name again, at full width, over the site's pages, its sources (`sources` adds page-specific <li> items)
    and notes (`note` adds page-specific caveats). `compact` keeps it to a line on pages where the map needs the height.
    `home` is kept for callers; the Χάρτες column always links the index."""
    today = datetime.date.today()
    pages = "".join(f'<li><a href="{href}">{label}</a></li>' for _, href, label in NAV)
    return (f'<footer class="site{" compact" if compact else ""}">'
            f'<p class="name">{MARK}Χάρτες Ψήφων</p>'
            '<p class="what">Σταυροί και ποσοστά των κομμάτων ανά κοινότητα και εκλογικό τμήμα, από το 2019 έως το 2024.</p>'
            f'<div class="cols"><div><h2>Χάρτες</h2><ul>{pages}'
            '<li><button type="button" class="copy">Αντιγραφή συνδέσμου</button></li></ul></div>'
            '<div><h2>Πηγές</h2><ul>'
            '<li>Αποτελέσματα: <a href="https://ekloges.ypes.gr/" rel="noopener">Υπουργείο Εσωτερικών</a></li>'
            '<li>Όρια: <a href="https://www.statistics.gr/" rel="noopener">ΕΛΣΤΑΤ 2021</a></li>'
            '<li>Υπόβαθρο: <a href="https://www.openstreetmap.org/copyright" rel="noopener">OpenStreetMap</a></li>'
            f'{sources}</ul></div>'
            f'<div><h2>Σημειώσεις</h2><p>Ανεπίσημα αποτελέσματα.{note} Μόνο δημόσια συγκεντρωτικά αποτελέσματα, κανένα προσωπικό δεδομένο.</p></div></div>'
            f'<p class="built">Ενημέρωση: {today.day} {MONTHS[today.month - 1]} {today.year}</p></footer>')


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


def leaflet_tags():
    """The self-hosted Leaflet stylesheet and script with their SRI hashes: the one place the version is written."""
    v = f"vendor/leaflet-{LEAFLET_VERSION}/"
    return (f'<link rel="stylesheet" href="{v}leaflet.min.css" integrity="{LEAFLET_SRI["leaflet.min.css"]}" crossorigin="anonymous">\n'
            f'<script src="{v}leaflet.min.js" integrity="{LEAFLET_SRI["leaflet.min.js"]}" crossorigin="anonymous"></script>')


def fill(page, light=MAP_LIGHT, dark=MAP_DARK, print_=None, current="maps", ctx="", skip="#main", compact=False, sources=""):
    """Shared parts of every page: colour tokens, site CSS and theme script, fonts, header, footer."""
    for placeholder, text in (("/*THEME_TOKENS*/", theme_css(light, dark, print_)),
                              ("/*SITE_CSS*/", (HERE / "fonts.css").read_text(encoding="utf-8") + (HERE / "site.css").read_text(encoding="utf-8")),
                              ("/*THEME_JS*/", (HERE / "theme.js").read_text(encoding="utf-8")),
                              ("/*SHARED_JS*/", (HERE / "shared.js").read_text(encoding="utf-8")),
                              ("<!--LEAFLET-->", leaflet_tags()), ("<!--FONTS-->", FONTS), ("<!--HEADER-->", header(current, ctx, skip)), ("<!--FOOTER-->", footer(compact=compact, sources=sources))):
        page = page.replace(placeholder, text)
    return page


def meta(title, description):
    """Description, Open Graph and Twitter card tags. The picture and address tags come from secure(), which knows the file;
    without SITE_URL there is no picture, so the card is "summary"."""
    t, d = html.escape(title, quote=True), html.escape(description, quote=True)
    return (f'<meta name="description" content="{d}"><meta property="og:type" content="website">'
            f'<meta property="og:site_name" content="Χάρτες Ψήφων"><meta property="og:locale" content="el_GR">'
            f'<meta property="og:title" content="{t}"><meta property="og:description" content="{d}">'
            f'<meta name="twitter:card" content="{"summary_large_image" if SITE_URL else "summary"}">')

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40' fill='none' stroke='%231f4e9c' "
           "stroke-width='3' stroke-linecap='round'%3E%3Crect x='3' y='3' width='34' height='34' rx='3'/%3E"
           "%3Cpath d='M11 12C16 17 22 24 29 29M28 11C23 16 17 23 12 30'/%3E%3C/svg%3E")  # the site mark; img-src allows data:

LEAFLET = f"https://cdnjs.cloudflare.com/ajax/libs/leaflet/{LEAFLET_VERSION}/"  # for pages written outside out/: no vendor/ folder beside them


def secure(page, path=None):
    """Content-Security-Policy (as a <meta>: GitHub Pages sets no headers), referrer policy, favicon and, when config.SITE_URL
    is set, the page's canonical address, og:url and og:image (`path` = the file the page is written to; one outside out/ gets none).
    Call it last, on the finished page: the inline scripts and styles are allowed by their SHA-256 hash, so injected markup cannot run.
    Leaflet (pinned by integrity=) and the fonts are self-hosted in out/, so only the OSM tiles come from outside. A page written
    anywhere else (a client's map, `path` None) has no vendor/ folder beside it: its Leaflet link and CSP point to cdnjs instead."""
    home = path is not None and Path(path).resolve().parent == OUT.resolve()
    if not home:
        page = page.replace(f"vendor/leaflet-{LEAFLET_VERSION}/", LEAFLET)
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
                 f'<meta property="og:image:height" content="630"><meta property="og:image:alt" content="{alt[1] if alt else "Χάρτες Ψήφων"}">'
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
/* The index: the search beside the map of Greece, then a board of filled tiles (see the note above the sections). */
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
.fl{display:block;margin:0 0 var(--space-xs);font-size:var(--t-base);font-weight:600;color:var(--ink)}
.sf{position:relative}
#f{width:100%;min-height:56px;font:inherit;font-size:var(--text-lead);color:var(--ink);background:var(--paper);
   border:1.5px solid var(--ink-2);border-radius:8px;padding:var(--space-sm) var(--space-md) var(--space-sm) 52px}
#f::placeholder{color:var(--ink-2)}
#f:focus-visible{outline:2px solid var(--pen);outline-offset:2px;border-color:var(--pen)}
.sf::before{content:"";position:absolute;left:var(--space-md);top:18px;width:20px;height:20px;background:var(--ink-2);-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='8.5' cy='8.5' r='5.5'/%3E%3Cpath d='M13 13l4.5 4.5'/%3E%3C/svg%3E") center/contain no-repeat;mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='8.5' cy='8.5' r='5.5'/%3E%3Cpath d='M13 13l4.5 4.5'/%3E%3C/svg%3E") center/contain no-repeat;pointer-events:none;z-index:1}
#n{margin:var(--space-xs) 0 0;color:var(--ink-2);font-size:var(--t-base)}
#n:empty{display:none}
.try{margin:var(--space-md) 0 0;font-size:var(--t-base)}
.try a{display:inline-flex;align-items:center;min-height:44px;color:var(--ink);text-underline-offset:4px}
.try a:hover{color:var(--pen)}
.sug{position:absolute;left:0;right:0;top:100%;z-index:20;list-style:none;margin:var(--space-2xs) 0 0;padding:var(--space-2xs);background:var(--paper);border:1px solid var(--line);border-radius:8px}
.sug a{display:grid;gap:var(--space-2xs);padding:var(--space-sm);min-height:44px;color:var(--ink);text-decoration:none;border-radius:6px}
.sug a b{font-size:var(--text-lead);font-weight:600;line-height:1.25}
.sug a span{color:var(--ink-2);font-size:var(--t-base)}
.sug a.act,.sug a:hover{background:var(--wash)}
.sug a.more{min-height:36px;color:var(--pen);font-size:var(--t-base)}
.gr{margin:0}
.gr a:first-child{display:block;border-radius:8px}
.gr a:first-child:hover svg{opacity:.88}
.gr svg{display:block;width:100%;height:auto;max-height:min(72svh,680px);margin-inline:auto}
.gr figcaption{margin:var(--space-sm) 0 0;font-size:var(--t-base);color:var(--ink-2)}
.gr .keys{display:flex;flex-wrap:wrap;gap:var(--space-2xs) var(--space-md);margin-top:var(--space-xs)}
.gr .k{display:inline-flex;align-items:center;gap:var(--space-xs);white-space:nowrap}
.gr .k i{display:inline-block;width:12px;height:12px;border-radius:2px;box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ink-2) 75%,var(--paper))}
/* Below the hero the page is a board: filled tiles with 8px gaps, no rules, no shadows. Colour carries the data: every
   constituency tile wears its first party's colour for the chosen election, and each region's tile counts them. */
:root{
  --board:var(--space-xs);
  --deep:light-dark(#1b2230,#262c38);--deep-2:light-dark(#242d3e,#2e3542);--on-deep:light-dark(#fbfaf6,#ecebe7);--on-deep-2:light-dark(#c9cdd6,#b9bcc4);
  --field:light-dark(#1f4e9c,#2a4a86);--on-field:#ffffff;
  --on-dark:#ffffff;--on-light:#111111}
.sec{padding-top:var(--section-gap)}
.head{display:grid;grid-template-columns:minmax(0,6fr) minmax(0,6fr);column-gap:var(--gap-columns);align-items:end;margin-bottom:var(--space-xl)}
.head .lead{max-width:44ch}
/* Όλη η χώρα: three tools as tiles, each led by its own figure */
.tools{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);grid-template-rows:auto auto;gap:var(--board)}
.tool{position:relative;display:flex;flex-direction:column;gap:var(--space-md);padding:var(--space-xl);min-height:280px}
.tool.fc{grid-row:1/3;background:var(--deep);color:var(--on-deep)}
.tool.cm{background:var(--field);color:var(--on-field)}
.tool.ab{background:var(--wash);color:var(--ink)}
.tool h3{font-size:var(--text-title)}
.tool h3 a{color:inherit;text-decoration:none}
.tool h3 a::after{content:"";position:absolute;inset:0}
.tool:hover h3 a{text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:6px}
.tool p{margin:0;max-width:40ch;font-size:var(--t-base);line-height:1.5}
.tool .fig{margin-top:auto;font-size:var(--text-display);font-weight:600;letter-spacing:-.03em;line-height:.95;font-variant-numeric:tabular-nums}
.tool.fc p:not(.fig){color:var(--on-deep-2)}
.seats{position:relative;display:flex;height:40px;margin-top:var(--space-xl);transform-origin:left}
.seats span{background:var(--c);min-width:2px}
.seats span+span{box-shadow:inset 2px 0 0 var(--deep)}
.seats .rest{background:var(--deep-2)}
.seats .maj{position:absolute;left:calc(100% * var(--maj));top:calc(-1 * var(--space-lg));bottom:calc(-1 * var(--space-2xs));padding-left:var(--space-2xs);border-left:2px solid var(--on-deep);background:none;box-shadow:none;font-size:var(--t-base);line-height:1;color:var(--on-deep);white-space:nowrap}
.sk{display:flex;flex-wrap:wrap;gap:var(--space-2xs) var(--space-md);list-style:none;margin:0;padding:0;font-size:var(--t-base);color:var(--on-deep)}
.sk li{display:inline-flex;align-items:center;gap:var(--space-xs);font-variant-numeric:tabular-nums}
.sk i{width:12px;height:12px;background:var(--c)}
/* Εκλογικές περιφέρειες: a board per region, the region's tile first */
html{scroll-padding-top:96px}
.ctl{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-xs);margin-inline:calc(-1 * var(--space-xs));padding:var(--space-sm) var(--space-xs);background:var(--paper)}
.ctl[hidden]{display:none}
.ctl .swl{margin-right:var(--space-xs);color:var(--ink-2)}
.sw{display:contents}
.sw button{font:inherit;color:var(--ink);background:var(--wash);border:0;border-radius:22px;padding:0 var(--space-md);min-height:44px;cursor:pointer;transition:transform .12s ease-out}
.sw button:hover{background:color-mix(in srgb,var(--wash),var(--ink) 10%)}
.sw button:active{transform:scale(.96)}
.sw button[aria-pressed=true]{color:var(--paper);background:var(--ink);font-weight:600}
.tk{margin:0 0 0 auto;color:var(--ink-2);font-size:var(--t-base)}
.grp{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,4fr);gap:var(--board);margin-top:var(--board)}
.grp:not(:has(li:not([hidden]))){display:none}  /* a region goes with its tiles */
.eps{display:grid;grid-template-columns:repeat(auto-fit,minmax(232px,1fr));gap:var(--board);list-style:none;margin:0;padding:0}
.rt{display:flex;flex-direction:column;gap:var(--space-md);padding:var(--space-lg);background:var(--deep);color:var(--on-deep)}
.reg{font-size:var(--text-title)}
.rs{display:flex;flex-direction:column;gap:var(--space-sm);margin-top:auto}
.rs[hidden]{display:none}
.strip{display:flex;flex-wrap:wrap;gap:4px;margin:0}
.strip i{width:20px;height:20px;background:var(--c)}
.rs p:last-child{margin:0;color:var(--on-deep-2);font-size:var(--t-base);line-height:1.45}
.eps li{position:relative;display:flex;flex-direction:column;min-height:256px;background:var(--wash);overflow-wrap:break-word}
.eps li:hover{background:color-mix(in srgb,var(--wash),var(--ink) 7%)}
.fp{display:flex;flex-direction:column;justify-content:flex-end;align-items:flex-start;gap:var(--space-2xs);min-height:104px;margin:0;padding:var(--space-md) var(--space-lg);background:var(--c);color:var(--on-dark);font-size:var(--text-title);font-variant-numeric:tabular-nums;line-height:1}
.fp.dk{color:var(--on-light)}
.fp>b,.fp>.v{position:relative;z-index:2}  /* above the silhouette */
.fp[hidden]{display:none}
.sil{position:absolute;z-index:1;top:var(--space-sm);right:var(--space-sm);width:auto;height:80px;max-width:36%;color:var(--on-dark);pointer-events:none}
.eps li:has(.fp.dk:not([hidden])) .sil{color:var(--on-light)}
.sil path{fill:currentColor;fill-opacity:.3;stroke:currentColor;stroke-width:1;stroke-linejoin:round}
.eps h4{margin:var(--space-md) var(--space-lg) 0;font-size:var(--text-lead);font-weight:600;line-height:1.25}
.eps h4 a{color:var(--ink);text-decoration:none}
.eps h4 a:hover{text-decoration:underline;text-underline-offset:4px}
.eps h4 a::after{content:"";position:absolute;inset:0}  /* the whole tile opens the map */
.top{flex:1;display:flex;flex-direction:column;margin:var(--space-2xs) 0 0;padding:0 var(--space-lg) var(--space-lg)}
.top[hidden]{display:none}
.who{position:relative;display:block;padding-left:1em;color:var(--ink-2);font-size:var(--t-base)}
.who b{color:var(--ink);font-weight:600}
.eps .who b::before{content:"";position:absolute;left:0;top:.45em;width:.6em;height:.6em;background:currentColor;clip-path:var(--xm)}
.vt{margin-top:auto;padding-top:var(--space-md);font-size:var(--text-title);font-weight:600;font-variant-numeric:tabular-nums;line-height:1}
.vt small{margin-left:var(--space-2xs);font-size:var(--t-base);font-weight:400;color:var(--ink-2)}
.eps .dhm{position:relative;margin:0;padding:0 var(--space-lg) var(--space-md);color:var(--ink-2);font-size:var(--t-base);line-height:1.5}
.acts{position:relative;display:flex;flex-wrap:wrap;align-items:center;gap:0 var(--space-md);padding:0 var(--space-lg) var(--space-md)}  /* every election, until the switcher takes over */
body.pick .acts{display:none}
.older summary{display:flex;align-items:center;min-height:44px;cursor:pointer;color:var(--ink-2)}
.older[open]{flex:1 1 100%}
.el{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2xs) var(--space-md);margin:0}
.el a{display:inline-flex;align-items:center;min-height:44px;color:var(--ink-2);white-space:nowrap;text-underline-offset:3px}
.el a:hover{color:var(--pen)}
.el a.now{color:var(--pen);font-weight:600}
/* ΝΙΚΗ: a cell in the party's colour beside four rows on the deep ground */
.nks{margin-top:var(--section-gap)}
.nkg{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--board)}
.nka{display:flex;flex-direction:column;justify-content:space-between;gap:var(--space-xl);min-height:520px;padding:var(--space-xl);background:var(--c);color:var(--on-light)}
.nka.lt{color:var(--on-dark)}
.nka h2{font-size:var(--text-section);letter-spacing:-.04em;line-height:.95}
.nka .lead{color:inherit;max-width:28ch}
.nk{display:grid;grid-auto-rows:1fr;list-style:none;margin:0;padding:0}
.nk li{position:relative;display:flex;flex-direction:column;justify-content:center;gap:var(--space-xs);padding:var(--space-lg) var(--space-xl);background:var(--deep);color:var(--on-deep)}
.nk li:nth-child(even){background:var(--deep-2)}
.nk a{color:inherit;font-size:var(--text-title);font-weight:600;line-height:1.25;text-decoration:none}
.nk a::after{content:"";position:absolute;inset:0}
.nk li:hover a{text-decoration:underline;text-underline-offset:5px}
.nk li>span{color:var(--on-deep-2)}
.fold{margin-top:var(--board);background:var(--wash)}
.fold summary{display:flex;align-items:center;justify-content:space-between;min-height:64px;padding:0 var(--space-xl);cursor:pointer;font-size:var(--text-lead);font-weight:600;list-style:none}
.fold summary::-webkit-details-marker{display:none}
.fold summary::after{content:"+";font-size:var(--text-title);font-weight:400;line-height:1;transition:transform .15s}
.fold[open]>summary::after{transform:rotate(45deg)}
.fold summary:hover{background:color-mix(in srgb,var(--wash),var(--ink) 7%)}
.fold:not([open]) ul{display:none}
.fold ul{columns:3 260px;column-gap:var(--gap-columns);list-style:none;margin:0;padding:var(--space-sm) var(--space-xl) var(--space-xl)}
.fold li{break-inside:avoid;padding-block:var(--space-xs)}
.fold li a{color:var(--ink);font-weight:600}
.fold li span{display:block;color:var(--ink-2)}
/* Δεδομένα και κάλυψη: one filled bar per election, filled to the share of valid votes the maps place */
.data{display:grid;grid-template-columns:minmax(0,4fr) minmax(0,8fr);column-gap:var(--gap-columns);align-items:start}
.data .lead{margin-top:var(--space-md)}
.dl{display:grid;gap:var(--board);list-style:none;margin:0;padding:0}
.dl li{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;column-gap:var(--space-lg);min-height:72px;padding:0 var(--space-lg);background:var(--wash);overflow:hidden}
.dl .fill{position:absolute;inset:0;background:color-mix(in srgb,var(--pen) 22%,var(--wash));transform:scaleX(var(--v,0));transform-origin:left;transition:transform .9s cubic-bezier(.2,.7,.2,1)}
.dl a,.dl b{position:relative;color:var(--ink);font-size:var(--text-title);font-weight:600;text-decoration:none}
.dl a::after{content:"";position:absolute;inset:-24px -100vw -24px -24px}
.dl li:hover a{text-decoration:underline;text-underline-offset:5px}
.dl b{font-variant-numeric:tabular-nums}
.dl li>span{position:relative;color:var(--ink-2)}
.foot{padding-top:var(--section-gap-s)}
.older summary:active,.fold summary:active{background:color-mix(in srgb,var(--wash),var(--ink) 12%)}
.older[open]>:not(summary),.fold[open]>:not(summary){animation:fade .15s ease-out}
@keyframes fade{from{opacity:0}}
/* Entrances: only when script runs and motion is welcome. Tiles rise but never fade, so nothing is ever hidden. */
.mo .rise{transition:transform .6s cubic-bezier(.2,.7,.2,1) var(--d,0ms)}
.mo .rise:not(.in){transform:translateY(32px)}
.mo .rise:not(.in) .fill{transform:scaleX(0)}
.mo .rise:not(.in) .seats{transform:scaleX(0)}
.mo .seats{transition:transform 1s cubic-bezier(.2,.7,.2,1) .2s}
@media (prefers-reduced-motion:reduce){.fold summary::after,.dl .fill,.sw button{transition:none}.older[open]>:not(summary),.fold[open]>:not(summary){animation:none}}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
/* Micro-interactions, only when motion is welcome; every state is reachable without them. */
:root{--ease-out:cubic-bezier(.16,1,.3,1)}
@media (prefers-reduced-motion:no-preference){
  /* switching elections: each region's new colours sweep across its tiles, its strip counts them in */
  .go .fp:not([hidden]){animation:wipe .5s var(--ease-out) both;animation-delay:calc(var(--i,0) * 24ms)}
  @keyframes wipe{from{clip-path:inset(0 100% 0 0)}}
  .go .rs:not([hidden]) .strip i{animation:pop .35s var(--ease-out) both;animation-delay:calc(var(--j,0) * 40ms)}
  @keyframes pop{from{transform:scale(0)}}
  /* the chosen election's pill glides to the new button (View Transitions); the rest of the page does not cross-fade */
  .sw button[aria-pressed=true]{view-transition-name:pick}
  ::view-transition-group(pick){animation-duration:.3s;animation-timing-function:var(--ease-out)}
  html.vt-pick::view-transition-old(root),html.vt-pick::view-transition-new(root){animation:none}
  .sug:not([hidden]){animation:drop .16s var(--ease-out)}
  @keyframes drop{from{opacity:0;transform:translateY(-4px)}}
  #f{transition:border-color .15s}
  .sw button,.fold summary,.sug a{transition:background-color .15s,transform .12s ease-out}
  .tool,.eps li,.mo :is(.tool,.eps li).rise{transition:background-color .15s,transform .6s cubic-bezier(.2,.7,.2,1) var(--d,0ms)}  /* keeps the entrance's timing */
  @media (pointer:fine){
    .sil{transition:transform .5s var(--ease-out)}
    .eps li:hover .sil{transform:translate(-4px,4px) scale(1.08)}
    .tool.fc:hover{background:color-mix(in srgb,var(--deep),var(--on-deep) 6%)}
    .tool.cm:hover{background:color-mix(in srgb,var(--field),#fff 8%)}
    .tool.ab:hover{background:color-mix(in srgb,var(--wash),var(--ink) 7%)}
  }
}
body:has(#f:not(:placeholder-shown)) :is(#country,.nks,#cov){display:none}  /* while searching, the tiles come right after the first screen */
@media (max-width:60rem){
  .hero{grid-template-columns:minmax(0,1fr);row-gap:var(--space-xl);min-height:0}
  .head,.data,.nkg,.grp{grid-template-columns:minmax(0,1fr)}
  .head{row-gap:var(--space-md);margin-bottom:var(--space-lg)}
  .tools{grid-template-columns:minmax(0,1fr)}
  .tool.fc{grid-row:auto}
  .tool{min-height:0;padding:var(--space-lg)}
  .nka{min-height:0}
  .data .dl{margin-top:var(--space-xl)}
  .tk{flex-basis:100%;margin:0}
}
@media (max-width:40rem){.ctl{position:static}html{scroll-padding-top:var(--space-md)}}
@media (max-width:40rem){
  .eps{grid-template-columns:repeat(2,minmax(0,1fr))}
  .eps li{min-height:0}
  .eps:has(.dhm){grid-template-columns:minmax(0,1fr)}
  .fp{min-height:96px;padding:var(--space-sm) var(--space-md);font-size:var(--text-lead)}
  .sil{display:none}
  .eps h4,.top,.eps .dhm,.acts{padding-inline:var(--space-md);margin-inline:0}
  .eps h4{font-size:var(--t-base);padding-top:var(--space-sm);margin-top:0}
  .who{font-size:var(--t-base)}
  .vt{font-size:var(--text-lead);padding-top:var(--space-sm)}
  .vt small{display:block;margin:var(--space-2xs) 0 0;font-size:var(--t-base)}
  .nk li,.fold summary,.fold ul,.nka{padding-inline:var(--space-lg)}
  #f{font-size:var(--t-base);padding-left:44px}#f::placeholder{font-size:var(--t-base)}.sf::before{left:var(--space-sm)}
}
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
// Up to 6 constituencies under the field: the name, its region and its first candidate; the rest stay in the board below.
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
    a.className = "more"; a.href = "#regions"; a.textContent = `και ${total - 6} ακόμη παρακάτω`; a.addEventListener("click", closeSug);
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
// Election switcher: every tile opens the chosen election and wears its first party; its line shows the first candidate of
// that election, or of the newest earlier one with per-candidate crosses (data-x), named in #tk. Without script each tile
// lists all its elections and shows the default one.
const sw = document.querySelector(".sw"), ctl = document.querySelector(".ctl");
const open = e => {
  let x = "";
  sw.querySelectorAll("button").forEach(b => { b.setAttribute("aria-pressed", b.dataset.e === e); if (b.dataset.e === e) x = b.dataset.x; });
  const tk = document.getElementById("tk"), xb = sw.querySelector(`button[data-e="${x}"]`);
  if (tk) { tk.hidden = !xb; if (xb) { tk.querySelector(".te").textContent = xb.textContent;
    tk.querySelector(".tn").textContent = x === e ? "" : ` (${sw.querySelector(`button[data-e="${e}"]`).textContent}: χωρίς σταυρούς ανά τμήμα)`; } }
  for (const li of items) {
    li.querySelector("h4 a").href = (li.querySelector(`.el a[data-e="${e}"]`) || li.querySelector(".el a")).href;
    li.querySelectorAll(".top").forEach(p => { p.hidden = p.dataset.e !== x; });
  }
  document.querySelectorAll(".fp, .rs").forEach(p => { p.hidden = p.dataset.e !== e; });
};
const motion = matchMedia("(prefers-reduced-motion: no-preference)");
items.forEach(li => li.style.setProperty("--i", Math.min([...li.parentElement.children].indexOf(li), 12)));
document.querySelectorAll(".strip").forEach(s => [...s.children].forEach((i, j) => i.style.setProperty("--j", Math.min(j, 12))));
sw.addEventListener("click", ev => {
  const b = ev.target.closest("button");
  if (!b || b.getAttribute("aria-pressed") === "true") return;
  if (!motion.matches) return open(b.dataset.e);
  document.body.classList.add("go");  // from the first switch on, newly shown bands sweep in
  if (!document.startViewTransition) return open(b.dataset.e);
  const root = document.documentElement;
  root.classList.add("vt-pick");
  document.startViewTransition(() => open(b.dataset.e)).finished.finally(() => root.classList.remove("vt-pick"));
});
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
// Tiles rise into place as they come into view, a few at a time; the bars fill. Nothing is hidden, with or without script.
if (matchMedia("(prefers-reduced-motion: no-preference)").matches && "IntersectionObserver" in window) {
  document.body.classList.add("mo");
  // A figure counts up to its printed value once; the text it ends on is the original, so nothing is ever computed wrong.
  const count = el => {
    const t = el.textContent, m = t.match(/[0-9][0-9.]*(,[0-9]+)?/);
    if (!m) return;
    const v = parseFloat(m[0].replaceAll(".", "").replace(",", ".")), dec = m[1] ? m[1].length - 1 : 0;
    const fmt = new Intl.NumberFormat("el-GR", {minimumFractionDigits: dec, maximumFractionDigits: dec}), t0 = performance.now();
    const step = now => { const k = Math.min((now - t0) / 900, 1);
      el.textContent = k < 1 ? t.replace(m[0], fmt.format(v * (1 - (1 - k) ** 3))) : t; if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  };
  const io = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) { en.target.classList.add("in"); en.target.querySelectorAll(".fig, .dl b").forEach(count); io.unobserve(en.target); } }),
                                      { rootMargin: "0px 0px -6% 0px" });
  document.querySelectorAll(".rise").forEach(el => {
    const sib = [...el.parentElement.children].filter(c => c.classList.contains("rise"));
    el.style.setProperty("--d", `${Math.min(sib.indexOf(el), 6) * 70}ms`);
    io.observe(el);
  });
}
"""


def card(ep, name, keys, n_own, first, lead, note, chips, href, sil=""):
    """One constituency tile. `first` is one band per election in its first party's colour (the switcher shows one);
    the name opens the default election (the switcher retargets it); `chips` are the election links, newest first:
    without script they show in the tile, the older ones folded into a <details>. `lead` is one line per election with
    crosses (the switcher shows one); `note` is the optional list of municipalities."""
    now, *older = chips
    folded = (f'<details class="older"><summary>Παλαιότερες εκλογές ({len(older)})</summary>'
              f'<p class="el">{"".join(older)}</p></details>') if older else ""
    return (f'<li id="ep-{ep}" class="rise" data-k="{html.escape(keys)}" data-n="{n_own}">{first}{sil}'
            f'<h4><a href="{href}"><span>{html.escape(name)}</span></a></h4>'
            f'{lead}{note}<div class="acts"><p class="el">{now}</p>{folded}</div></li>')


def _on(colour):
    """"dk" when dark text reads better than white on `colour` (#rrggbb), else "lt" (WCAG relative luminance)."""
    lin = [(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4) for c in (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))]
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return "dk" if (y + 0.05) / 0.05 > 1.05 / (y + 0.05) else "lt"


def _pct(x, dec=1):
    return f"{100 * x:.{dec}f}".replace(".", ",") + "%"


def _write_index(order, nikh, elected):
    """out/index.html: the search beside the map of Greece, the nationwide tools, a board of every constituency (its
    region's tile first, each tile in its first party's colour, one link per election), the ΝΙΚΗ reports, and the share
    of the vote each election's maps place, with the coverage pages and the data to download."""
    def fold(s):
        return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()

    def dots(n):
        return f"{n:,}".replace(",", ".")

    # Municipalities (δήμοι) and municipal units of each constituency: search aliases, so a voter can type a town.
    dhm, den = defaultdict(dict), defaultdict(set)
    top, first, colour, mapped, valid, pname = {}, {}, {}, {}, {}, {}
    n_comm = n_countries = n_tm = None
    last = list(ELECTIONS)[-1]
    if DB.exists():
        with sqlite3.connect(DB) as con:
            for e, ep, d, u in con.execute("SELECT DISTINCT election, ep_id, dhm_descr, den_descr FROM station WHERE kind = 'Κ'"):
                dhm[e, ep][d] = None
                den[e, ep].add(u)
            # The candidate with the most crosses, per election and constituency. June 2023 has a few constituencies only
            # (party leaders' totals) and Euro 2024 none: those elections show the newest earlier election that has them all.
            for e, ep, cand, pid, party, votes in con.execute(
                    "SELECT t.election, t.ep_id, c.name, p.party_id, p.name, MAX(t.votes) FROM ep_total t "
                    "JOIN candidate c USING(election, ep_id, party_id, cand_id) JOIN party p USING(election, party_id) "
                    "WHERE t.cand_id > 0 AND t.votes > 0 GROUP BY t.election, t.ep_id"):
                top[e, ep] = (cand, PARTY_SHORT.get(pid, party), votes)
            # Each constituency's first party and its share of the valid votes, per election: the colour of its tile.
            for e, pid, c, nm in con.execute("SELECT election, party_id, color, name FROM party"):
                colour[e, pid] = PARTY_COLOR.get(pid) or ("#" + c[2:] if c else "#888888")
                pname[e, pid] = PARTY_SHORT.get(pid, nm)  # a party without a short name keeps the ministry's name
            ep_valid = {(e, ep): v for e, ep, v in con.execute("SELECT election, ep_id, SUM(valid) FROM station GROUP BY 1, 2")}
            for e, ep, pid, votes in con.execute(
                    "SELECT s.election, s.ep_id, v.party_id, SUM(v.votes) FROM party_votes v JOIN station s USING(election, tm_id) "
                    "GROUP BY 1, 2, 3"):
                if votes > first.get((e, ep), (0, 0, 0))[2]:
                    first[e, ep] = (pid, votes / (ep_valid[e, ep] or 1), votes)
            # The share of valid votes that has a place on the maps (special stations, postal votes and voters abroad do not).
            for e, v, m in con.execute("SELECT s.election, SUM(s.valid), SUM(CASE WHEN m.tm_id IS NULL THEN 0 ELSE s.valid END) "
                                       "FROM station s LEFT JOIN area_match m USING(election, tm_id) GROUP BY 1"):
                valid[e], mapped[e] = v, m
            n_comm = con.execute("SELECT COUNT(DISTINCT comm_code) FROM area_match").fetchone()[0]
            n_countries = con.execute("SELECT election, COUNT(DISTINCT country) FROM abroad GROUP BY 1 ORDER BY 1 DESC").fetchone()
            n_tm = con.execute("SELECT COUNT(*) FROM station WHERE election=? AND kind='Κ'", (last,)).fetchone()[0]
    # Tiles open the newest parliamentary election by default: the one the forecast and the candidates are about.
    default = next(e for e in reversed(ELECTIONS) if source(e)[1] == "v")
    per = Counter(e for e, _ in top)
    crossed = [e for e in ELECTIONS if per[e] and per[e] >= 0.9 * max(per.values())]
    crosses_of = {e: next((c for c in reversed(crossed) if list(ELECTIONS).index(c) <= list(ELECTIONS).index(e)), "") for e in ELECTIONS}
    eps, tm = {}, []
    for f, m in order:
        if "_tm_" in f:
            tm.append((f, m))  # station maps exist for a few constituencies only: listed apart, not on the tiles
        else:
            eps.setdefault(m["ep_name"], []).append((f, m))
    rank = list(ELECTION_NAMES)
    region_of = {ep: region for region, eps_ in REGIONS for ep in eps_}
    by_region = {region: [] for region, _ in REGIONS}  # keeps the regions' north-to-south order
    firsts = defaultdict(lambda: defaultdict(list))  # region -> election -> first parties of its constituencies

    def band(e, ep):
        """The tile's band for one election: its first party and share, in that party's colour."""
        if (e, ep) not in first:
            return ""
        pid, share, _ = first[e, ep]
        c = colour.get((e, pid), "#888888")
        return (f'<p class="fp {_on(c)}" data-e="{e}" style="--c:{c}"{"" if e == default else " hidden"}><span class="sr">Πρώτο κόμμα, '
                f'{ELECTION_NAMES[e]}: </span><b>{html.escape(pname.get((e, pid), ""))}</b> <span class="v">{_pct(share)}</span></p>')

    for name in sorted(eps, key=fold):
        links = sorted(eps[name], key=lambda fm: rank.index(fm[1]["election"]) if fm[1]["election"] in rank else -1)
        latest = links[-1][1]
        region = region_of.get(latest["ep"], "Λοιπές")
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
        # The cross marks the candidate with the most crosses.
        lead = "".join(
            f'<p class="top" data-e="{m["election"]}"{"" if m["election"] == crosses_of[default] else " hidden"}>'
            f'<span class="who"><span class="sr">{TOP_KEY}, {ELECTION_NAMES[m["election"]]}: </span><b>{html.escape(t[0])}</b> '
            f'({html.escape(t[1])})</span><span class="vt">{dots(t[2])}<small>σταυροί</small></span></p>'
            for _, m in reversed(links) if m["election"] in crossed and (t := top.get((m["election"], m["ep"]))))
        bands = "".join(band(m["election"], m["ep"]) for _, m in reversed(links))
        for _, m in links:
            if (m["election"], m["ep"]) in first:
                firsts[region][m["election"]].append(first[m["election"], m["ep"]][0])
        first_href = next((f for f, m in links if m["election"] == default), links[-1][0])
        by_region.setdefault(region, []).append(
            card(latest["ep"], name, k, len(own), bands, lead, note, chips, urllib.parse.quote(first_href), latest.get("sil", "")))

    def summary(region, e):
        """The region tile's line for one election: a square per constituency in its first party's colour, then the count."""
        pids = firsts[region][e]
        if not pids:
            return ""
        count = Counter(pids).most_common()
        squares = "".join(f'<i style="--c:{colour.get((e, p), "#888888")}"></i>' * c for p, c in count)
        words = ", ".join(f"{pname.get((e, p), '')} σε {c}" for p, c in count)
        return (f'<div class="rs" data-e="{e}"{"" if e == default else " hidden"}><p class="strip" aria-hidden="true">{squares}</p>'
                f'<p>Πρώτο κόμμα, {ELECTION_NAMES[e]}: {words} από {len(pids)}.</p></div>')

    groups = "".join(
        f'<section class="grp"><div class="rt rise"><h3 class="reg" id="reg-{i}">{html.escape(region)}</h3>'
        f'{"".join(summary(region, e) for e in reversed(ELECTION_NAMES))}</div><ul class="eps">{"".join(lis)}</ul></section>'
        for i, (region, lis) in enumerate(by_region.items()) if lis)
    # the link name carries the note beside it, so two links to the same constituency read differently in a list of links
    nikh_rows = "".join(
        (lambda note: f'<li><a href="{urllib.parse.quote(f)}" aria-label="{html.escape(m["ep_name"])}, {note}">{html.escape(m["ep_name"])}</a> <span>{note}</span></li>')(
            ELECTION_NAMES.get(m["election"], m["election"])
            + (", " + html.escape(elected[m["ep"]]) if m["election"] == "2023/june" and m["ep"] in elected else ""))
        for f, m in nikh)
    nikh_rows += "".join(f'<li><a href="{urllib.parse.quote(f)}" aria-label="{html.escape(m["ep_name"])}, {html.escape(m["label"])}">{html.escape(m["ep_name"])}</a> <span>{html.escape(m["label"])}</span></li>'
                         for f, m in tm if "_tm_131-" not in f)
    switch = "".join(f'<button type="button" data-e="{e}" data-x="{crosses_of[e]}" aria-pressed="false">{n}</button>' for e, n in reversed(ELECTION_NAMES.items()))
    tk = (f'<p class="tk" id="tk">Πρώτοι σε σταυρούς: <span class="te">{ELECTION_NAMES[crosses_of[default]]}</span>'
          f'<span class="tn">{"" if crosses_of[default] == default else f" ({ELECTION_NAMES[default]}: χωρίς σταυρούς ανά τμήμα)"}</span></p>'
          if crosses_of[default] else "")
    gr = HERE / "out" / "greece_map.html"
    greece = gr.read_text(encoding="utf-8") if gr.exists() else ""  # written by compare.py
    nikh_n = nikh_rows.count("<li>")
    nikh_c = colour.get((default, NIKH), "#dd6c6d")
    coverage = "".join(
        f'<li class="rise"><span class="fill"{f" style=--v:{mapped[e] / valid[e]:.4f}" if valid.get(e) else ""}></span>'
        f'<a href="index_{e.replace("/", "-")}.html" aria-label="Κάλυψη χαρτών, {name}"><span>{name}</span></a>'
        f'<span>{f"<b>{_pct(mapped[e] / valid[e])}</b> στον χάρτη" if valid.get(e) else "Κάλυψη χαρτών"}</span></li>'
        for e, name in reversed(ELECTION_NAMES.items()) if (OUT / f'index_{e.replace("/", "-")}.html').exists())
    first_year = list(ELECTIONS)[0][:4]
    figs = [f"{len(eps)} εκλογικές περιφέρειες", f"{len(ELECTIONS)} εκλογές από το {first_year} έως το {last[:4]}"]
    figs += [f"{dots(n_tm)} εκλογικά τμήματα"] if n_tm else []
    nums = (", ".join(figs[:-1]) + " και " + figs[-1] + ".") if len(figs) > 1 else figs[0] + "."
    # The forecast tile repeats the forecast page's headline: ΝΔ's chance of a majority and the median seats today.
    fc_fig, fc_text, fc_bar = "", "Αυτοδυναμία, ποσοστά και έδρες από τον μέσο όρο των δημοσκοπήσεων.", ""
    fj = HERE / "analysis" / "forecast.json"
    if fj.exists():
        fd = json.loads(fj.read_text(encoding="utf-8"))
        h, names = fd["horizons"]["0"], fd["names"]
        seats = sorted(((p, v["seats"][1]) for p, v in h["parties"].items() if v.get("seats") and v["seats"][1] > 0),
                       key=lambda pv: (list(FORECAST_COLOURS).index(pv[0]) if pv[0] in FORECAST_COLOURS else 99, -pv[1]))
        col = {p: (f"light-dark({FORECAST_COLOURS[p][0]},{FORECAST_COLOURS[p][1]})" if p in FORECAST_COLOURS else "var(--on-deep-2)") for p, _ in seats}
        d = datetime.date.fromisoformat(fd["as_of"])
        p_maj = h["p_nd_majority"]
        fc_fig = f'<p class="fig">{_pct(p_maj, 1 if p_maj < 0.1 else 0)}</p>'
        fc_text = f"πιθανότητα αυτοδυναμίας της ΝΔ σε εκλογές σήμερα, από τον μέσο όρο των δημοσκοπήσεων στις {d.day}/{d.month}/{d.year}."
        total = sum(s for _, s in seats)
        fc_bar = (f'<div class="seats" style="--maj:{LAW.MAJORITY / LAW.SEATS:.4f}" role="img" aria-label="Αυτοδυναμία με {LAW.MAJORITY} έδρες. Διάμεσες έδρες: '
                  + ", ".join(f"{names.get(p, p)} {s}" for p, s in seats) + '">'
                  + "".join(f'<span style="--c:{col[p]};flex:{s}"></span>' for p, s in seats)
                  + (f'<span class="rest" style="flex:{LAW.SEATS - total}"></span>' if total < LAW.SEATS else "")
                  + f'<span class="maj">{LAW.MAJORITY} αυτοδυναμία</span>'
                  + '</div><ul class="sk" aria-hidden="true">'
                  + "".join(f'<li><i style="--c:{col[p]}"></i>{html.escape(names.get(p, p))} {s}</li>' for p, s in seats)
                  + "</ul>")
    cm_fig = f'<p class="fig">{dots(n_comm)}</p>' if n_comm else ""
    cm_text = "κοινότητες, με το πρώτο κόμμα και τα ποσοστά τους" if n_comm else "Πρώτο κόμμα και ποσοστά ανά κοινότητα"
    ab_fig = f'<p class="fig">{n_countries[1]}</p>' if n_countries else ""
    ab_text = (f"χώρες με εκλογικά τμήματα για τους Έλληνες του εξωτερικού, {ELECTION_NAMES[n_countries[0]]}, και όσοι ψήφισαν επιστολικά."
               if n_countries else "Πώς ψήφισαν οι Έλληνες του εξωτερικού ανά χώρα και πόλη, και όσοι ψήφισαν επιστολικά.")
    (OUT / "index.html").write_text(secure(fill(f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Χάρτες Ψήφων</title>
{meta("Χάρτες Ψήφων", "Χάρτες αποτελεσμάτων των ελληνικών εκλογών ανά κοινότητα και εκλογικό τμήμα.")}
{FONTS}
<script>/*THEME_JS*/</script>
<style>{INDEX_CSS}</style></head><body><main id="main">
<div class="container"><!--HEADER-->
<header class="hero">
<div>
<h1>Χάρτες Ψήφων</h1>
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
<div class="tool fc rise"><h3><a href="forecast.html"><span>Πρόβλεψη εκλογών</span></a></h3>{fc_fig}<p>{fc_text}</p>{fc_bar}</div>
<div class="tool cm rise"><h3><a href="compare.html"><span>Σύγκριση εκλογών</span></a></h3>{cm_fig}<p>{cm_text}, από το {first_year} έως το {last[:4]}.</p></div>
<div class="tool ab rise"><h3><a href="abroad.html"><span>Εξωτερικό και επιστολική ψήφος</span></a></h3>{ab_fig}<p>{ab_text}</p></div>
</div></section>
<section class="sec container" id="regions" aria-labelledby="rt">
<div class="head"><h2 id="rt">Εκλογικές περιφέρειες</h2><p class="lead">{nums} Κάθε πλακίδιο έχει το χρώμα του πρώτου κόμματος στην εκλογή που διαλέγεις.</p></div>
<div class="ctl" role="group" aria-label="Άνοιγμα στην εκλογή" hidden><span class="swl">Άνοιγμα στην εκλογή</span><div class="sw" data-d="{default}">{switch}</div>{tk}</div>
{groups}
</section>
<section class="nks" aria-labelledby="pt"><div class="container">
<div class="nkg"><div class="nka {_on(nikh_c)} rise" style="--c:{nikh_c}"><h2 id="pt">ΝΙΚΗ</h2><p class="lead">Αναφορές, χάρτες και δημοσκοπήσεις του κόμματος.</p></div>
<ul class="nk"><li class="rise"><a href="NIKH_eklegmenoi_2023.html"><span>Εκλεγμένοι Μαΐου και Ιουνίου 2023</span></a></li>
<li class="rise"><a href="nikh_2023-2024.html"><span>Όλη η χώρα ανά διαμέρισμα, 2019 έως 2024</span></a></li>
<li class="rise"><a href="nikh_targets.html"><span>Χάρτης στόχευσης</span></a><span>Κάστρα, φθορά, δεξαμενές, έδρες.</span></li>
<li class="rise"><a href="nikh_polls.html"><span>Στις δημοσκοπήσεις από το 2023</span></a></li></ul></div>
<details class="fold"><summary>Χάρτες ανά εκλογικό τμήμα ({nikh_n})</summary><ul>{nikh_rows}</ul></details>
</div></section>
<section class="sec container" id="cov" aria-labelledby="dt"><div class="data">
<div><h2 id="dt">Δεδομένα και κάλυψη</h2><p class="lead">Πόσοι ψήφοι αποδίδονται στον χάρτη, ανά νομό και εκλογή, και δεδομένα για λήψη. Κάθε μπάρα γεμίζει όσο το μερίδιο των έγκυρων ψήφων που έχει θέση στους χάρτες.</p></div>
<ul class="dl">{coverage}<li class="rise"><a href="../exports/NIKH_2023_ana_dhm_enotita.csv"><span>ΝΙΚΗ 2023 ανά δημοτική ενότητα</span></a><span>Αρχείο CSV</span></li></ul>
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
