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
from collections import defaultdict
from pathlib import Path

from config import (
    DB,
    ELECTED,
    ELECTION_NAMES,
    ELECTIONS,
    OG_IMAGES,
    HERE,
    OUT,
    PARTY_SHORT,
    REGIONS,
    SITE_URL,
    og_kind,
    slug,
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


def footer(note="", home=True, compact=False):
    """Site colophon: sources, notes (`note` adds page-specific caveats), links. `compact` keeps it to a few lines
    on pages where the map needs the height. `home` is kept for callers; the Χάρτες column always links the index."""
    today = datetime.date.today()
    return (f'<footer class="site{" compact" if compact else ""}"><div class="cols">'
            '<div><h3>Πηγές</h3><ul>'
            '<li>Αποτελέσματα: <a href="https://ekloges.ypes.gr/" rel="noopener">Υπουργείο Εσωτερικών</a></li>'
            '<li>Όρια: <a href="https://www.statistics.gr/" rel="noopener">ΕΛΣΤΑΤ 2021</a></li>'
            '<li>Υπόβαθρο: <a href="https://www.openstreetmap.org/copyright" rel="noopener">OpenStreetMap</a></li></ul></div>'
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


def fill(page, light=MAP_LIGHT, dark=MAP_DARK, print_=None, current="maps", ctx="", skip="#main", compact=False):
    """Shared parts of every page: colour tokens, site CSS and theme script, fonts, header, footer."""
    for placeholder, text in (("/*THEME_TOKENS*/", theme_css(light, dark, print_)),
                              ("/*SITE_CSS*/", (HERE / "fonts.css").read_text(encoding="utf-8") + (HERE / "site.css").read_text(encoding="utf-8")),
                              ("/*THEME_JS*/", (HERE / "theme.js").read_text(encoding="utf-8")),
                              ("/*SHARED_JS*/", (HERE / "shared.js").read_text(encoding="utf-8")),
                              ("<!--FONTS-->", FONTS), ("<!--HEADER-->", header(current, ctx, skip)), ("<!--FOOTER-->", footer(compact=compact))):
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

LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/"

def secure(page, path=None):
    """Content-Security-Policy (as a <meta>: GitHub Pages sets no headers), referrer policy, favicon and, when config.SITE_URL
    is set, the page's canonical address, og:url and og:image (`path` = the file the page is written to; one outside out/ gets none).
    Call it last, on the finished page: the inline scripts and styles are allowed by their SHA-256 hash, so injected markup cannot run.
    Leaflet (cdnjs, also pinned by integrity=) and the OSM tiles are the only outside sources; the fonts are self-hosted (fonts.css, out/fonts/)."""
    def hashes(tag):
        return [f"'sha256-{base64.b64encode(hashlib.sha256(m.encode()).digest()).decode()}'"
                for m in re.findall(rf"<{tag}>(.*?)</{tag}>", page, re.S)]
    csp = "; ".join([
        "default-src 'none'",
        " ".join(["script-src", *hashes("script"), LEAFLET + "leaflet.min.js"]),
        " ".join(["style-src-elem", *hashes("style"), LEAFLET + "leaflet.min.css"]),
        "style-src-attr 'unsafe-inline'",  # style="" in markup the pages build (legend swatches, table cells)
        "font-src 'self'",
        f"img-src 'self' data: https://tile.openstreetmap.org {LEAFLET}",
        "connect-src 'none'", "base-uri 'none'", "form-action 'none'", "object-src 'none'", "frame-src 'none'"])
    tags = (f'<meta http-equiv="Content-Security-Policy" content="{csp}"><meta name="referrer" content="strict-origin-when-cross-origin">'
            f'<link rel="icon" href="{FAVICON}">')
    if SITE_URL and path is not None and Path(path).resolve().parent == OUT.resolve():  # pages outside out/ are not published
        url = f"{SITE_URL}/out/{urllib.parse.quote(Path(path).name)}"
        kind = og_kind(Path(path).name)
        img, alt = f"{SITE_URL}/out/og/{kind}.png", html.escape(". ".join(OG_IMAGES[kind]), quote=True)
        tags += (f'<link rel="canonical" href="{url}"><meta property="og:url" content="{url}">'
                 f'<meta property="og:image" content="{img}"><meta property="og:image:width" content="1200">'
                 f'<meta property="og:image:height" content="630"><meta property="og:image:alt" content="{alt}">'
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
            f'<figcaption>{html.escape(caption)}.<span class="keys">{swatches}</span><a class="go" href="compare.html">Σύγκριση εκλογών &rarr;</a></figcaption></figure>')

INDEX_CSS = """
/*THEME_TOKENS*/
/*SITE_CSS*/
*{box-sizing:border-box}
html{scrollbar-gutter:stable}
:root{accent-color:var(--pen)}
body{margin:0;background:var(--paper);color:var(--ink);font:1rem/1.55 "IBM Plex Sans",system-ui,sans-serif}
main{max-width:1080px;margin:0 auto;padding:40px 24px 64px}
a{color:var(--pen)}
:focus-visible{outline:2px solid var(--pen);outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
h1{font:600 clamp(2.5rem,8vw,4.5rem)/1.05 "IBM Plex Sans",system-ui,sans-serif;letter-spacing:-.025em;margin:0}
:root{--xm:polygon(14% 0,50% 36%,86% 0,100% 14%,64% 50%,100% 86%,86% 100%,50% 64%,14% 100%,0 86%,36% 50%,0 14%)}
/* the cross marks what is chosen: the open election, the open region, the leading candidate of a row */
:is(.sw button[aria-pressed=true],.jump a[aria-current],.eps .who b)::before{content:"";display:inline-block;width:.6em;height:.6em;margin-right:.35em;background:currentColor;clip-path:var(--xm)}
.lede{max-width:34em;margin:16px 0 28px;color:var(--ink-2);font-size:var(--t-lg)}
.fl{display:block;margin:0 0 6px;font-size:var(--t-sm);font-weight:600;color:var(--ink)}
#f{width:100%;max-width:560px;min-height:48px;font:inherit;font-size:var(--t-lg);color:var(--ink);background:var(--paper) no-repeat 14px 50% / 20px;
   border:1.5px solid var(--ink-2);border-radius:8px;padding:10px 14px 10px 46px}
.try{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;margin:12px 0 0;font-size:var(--t-sm);color:var(--ink-2)}
.try button{font:inherit;color:var(--pen);background:none;border:1px solid var(--line);border-radius:16px;padding:0 14px;min-height:36px;cursor:pointer}
.try button:hover{border-color:var(--pen);background:var(--wash)}
.try .brw{margin-left:6px;color:var(--ink-2);display:inline-block;min-height:24px;line-height:24px}
#f::placeholder{color:var(--ink-2)}
#f:focus-visible{outline:2px solid var(--pen);outline-offset:2px;border-color:var(--pen)}
#n{margin:10px 0 0;min-height:1.55em;color:var(--ink-2);font-size:var(--t-sm)}
/* Ledger: one row per constituency; the columns are shared by every row (subgrid) and by the .lh caption */
.lh,.eps{display:grid;grid-template-columns:44px minmax(0,1.3fr) minmax(0,1.1fr) 5.5rem;column-gap:20px}
.lh{margin:20px 0 0;padding-bottom:6px;font-size:var(--t-xs);color:var(--ink-2)}
.lh :nth-child(1){grid-column:2}.lh :nth-child(2){grid-column:3}.lh :nth-child(3){grid-column:4;text-align:right}
.eps{list-style:none;margin:0;padding:0}
.eps li{grid-column:1/-1;display:grid;grid-template-columns:subgrid;align-items:center;position:relative;border-top:1px solid var(--line);padding:12px 0;overflow-wrap:anywhere}
.eps li:hover{background:var(--wash)}
.eps h4{grid-column:2;grid-row:1;font:600 1.25rem/1.25 "IBM Plex Sans",system-ui,sans-serif;margin:0}
.eps h4 a{color:var(--ink);text-decoration:none}
.eps h4 a:hover{text-decoration:underline;text-underline-offset:4px}
.eps h4 a::after{content:"";position:absolute;inset:0}  /* the whole row opens the map */
.top{display:contents;font-size:var(--t-sm);color:var(--ink-2);line-height:1.4}
.who{grid-column:3;grid-row:1;font-size:var(--t-sm);color:var(--ink-2);line-height:1.4}
.vt{grid-column:4;grid-row:1;font-size:var(--t-sm);color:var(--ink-2);text-align:right;font-variant-numeric:tabular-nums}
.top b{color:var(--ink);font-weight:600}
.country a:active,.eps li a:active,.older summary:active,.fold summary:active{background:var(--wash)}
.older[open]>:not(summary),.fold[open]>:not(summary){animation:fade .15s ease-out}
@keyframes fade{from{opacity:0}}
@media (prefers-reduced-motion:reduce){.older[open]>:not(summary),.fold[open]>:not(summary){animation:none}}
.acts{grid-column:2/-1;grid-row:3;position:relative;display:flex;flex-wrap:wrap;align-items:center;gap:0 14px;margin-top:6px}  /* every election, until the switcher takes over */
body.pick .acts{display:none}
.older summary,.fold summary{display:flex;align-items:center;min-height:32px;cursor:pointer;color:var(--ink-2);font-size:var(--t-sm)}
.older[open]{flex:1 1 100%}
.older[open] summary{margin-bottom:4px}
.dhm{margin:4px 0 0}
.el{display:flex;flex-wrap:wrap;align-items:center;gap:4px 14px;margin:0}
.el a{display:inline-flex;align-items:center;min-height:32px;color:var(--ink-2);font-size:var(--t-sm);white-space:nowrap;
      text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
.el a:hover{color:var(--pen);text-decoration-color:var(--pen)}
.el a.now{padding:0 12px;border:1px solid var(--pen);border-radius:16px;color:var(--pen);background:var(--wash);
          text-decoration:none;font-weight:600}
.el a.now:hover{background:var(--pen);color:var(--paper)}
.sil{grid-column:1;grid-row:1;width:44px;height:44px;color:var(--ink-2)}
.sil path{fill:currentColor;fill-opacity:.22;stroke:currentColor;stroke-width:1;stroke-linejoin:round}
.reg{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;margin:0}  /* the selected tab names the region; this stays as the heading and the scroll target */
.grp:not(:has(li:not([hidden]))){display:none}  /* a region head goes with its cards */
.key{display:flex;gap:8px;align-items:center;margin:20px 0 0;font-size:var(--t-sm);color:var(--ink-2)}
.gr{margin:20px 0 0;max-width:380px}
.gr a:first-child{display:block;border-radius:8px}
.gr a:first-child:hover svg{opacity:.88}
.gr .go{display:inline-flex;align-items:center;min-height:36px;margin:8px 0 0;padding:0 14px;border:1px solid var(--pen);border-radius:16px;background:var(--wash);color:var(--pen);text-decoration:none;font-weight:600}
.gr .go:hover{background:var(--pen);color:var(--paper)}
.gr svg{display:block;width:100%;height:auto;max-height:260px}
.gr figcaption{margin:6px 0 0;font-size:var(--t-xs);color:var(--ink-2)}
.gr .keys{display:flex;flex-wrap:wrap;gap:2px 12px;margin-top:4px}
.gr .k{display:inline-flex;align-items:center;white-space:nowrap}
.gr .k i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ink-2) 75%,var(--paper))}
@media (min-width:900px){
  /* one focal point: title and search on the left, the map as tall as the first screen on the right */
  main>header:not(.bar){display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,540px);column-gap:48px;align-content:center;min-height:calc(100svh - 190px)}
  main>header:not(.bar)>:not(.gr){grid-column:1}
  .gr{grid-column:2;grid-row:1/span 5;align-self:center;margin:0;max-width:none}
  .gr svg{max-height:min(68svh,640px);margin:0 auto}
}
.dhm{margin:0 0 8px;color:var(--ink-2);font-size:var(--t-xs);line-height:1.45}
.eps .dhm{grid-column:2/-1;grid-row:2;margin:4px 0 0;position:relative}
.sw{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;margin:20px 0 0;font-size:var(--t-sm);color:var(--ink-2)}
.sw[hidden]{display:none}
.sw .swl{margin-right:6px}
.sw button{font:inherit;color:var(--ink-2);background:none;border:1px solid var(--line);border-radius:16px;padding:0 14px;min-height:36px;cursor:pointer}
.sw button:hover{color:var(--pen)}
.sw button:active{background:var(--wash)}
.sw button[aria-pressed=true]{color:var(--pen);border-color:var(--pen);background:var(--wash);font-weight:600}
.cap{margin:24px 0 0;max-width:34em;font-size:var(--t-sm);color:var(--ink-2)}
.cap b{color:var(--ink);font-weight:600}
.nb{white-space:nowrap}
.sf{position:relative;max-width:560px}
.sf::before{content:"";position:absolute;left:14px;top:14px;width:20px;height:20px;background:var(--ink-2);-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='8.5' cy='8.5' r='5.5'/%3E%3Cpath d='M13 13l4.5 4.5'/%3E%3C/svg%3E") center/contain no-repeat;mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='8.5' cy='8.5' r='5.5'/%3E%3Cpath d='M13 13l4.5 4.5'/%3E%3C/svg%3E") center/contain no-repeat;pointer-events:none;z-index:1}
.sug{position:absolute;left:0;right:0;top:100%;z-index:20;list-style:none;margin:4px 0 0;padding:4px;background:var(--paper);border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px color-mix(in srgb,var(--ink) 18%,transparent)}
.sug[hidden]{display:none}
.sug a{display:grid;gap:1px;padding:10px 12px;min-height:44px;color:var(--ink);text-decoration:none;border-radius:6px}
.sug a b{font:600 1.0625rem/1.25 "IBM Plex Sans",system-ui,sans-serif}
.sug a span{color:var(--ink-2);font-size:var(--t-sm)}
.sug a.act,.sug a:hover{background:var(--wash)}
.sug a.more{min-height:36px;padding:8px 12px;color:var(--pen);font-size:var(--t-sm)}
.country,#regions{margin-top:96px}
.country h2,#regions>h2{font:600 1.5rem/1.2 "IBM Plex Sans",system-ui,sans-serif;letter-spacing:-.01em;margin:0 0 16px}
.cg{display:grid;grid-template-columns:minmax(0,1.4fr) repeat(2,minmax(0,1fr));gap:0 48px;align-items:start}
.cg>div{position:relative;border-top:2px solid var(--ink);padding:12px 0 28px}
.cg .main h3{font-size:var(--t-xl)}
.cg .main h3 a{text-decoration:none}
.cg .main h3 a::after{content:"";position:absolute;inset:0}  /* whole card is the link */
.cg .main:hover h3 span{transform:translateX(4px)}
.cg h3 span{display:inline-block;transition:transform .15s}
.fold summary::before{content:"+";display:inline-block;width:1.25em;font-size:var(--t-lg);line-height:1;transition:transform .15s}
.fold[open]>summary::before{transform:rotate(45deg)}
@media (prefers-reduced-motion:reduce){.cg h3 span,.fold summary::before{transition:none}}
.cg h3{font:600 1.25rem/1.25 "IBM Plex Sans",system-ui,sans-serif;margin:0 0 6px}
.cg h3 a{color:var(--ink);text-underline-offset:4px}
.cg p{color:var(--ink-2);margin:0 0 8px;font-size:var(--t-base)}
.cg .els{font-size:var(--t-sm);margin:0}
.cg ul{margin:0;padding:0;list-style:none}
.cg li{padding:3px 0}
.jump{position:sticky;top:0;z-index:5;display:flex;gap:4px 20px;margin:16px 0 0;padding:10px 0;flex-wrap:wrap;
      background:var(--paper);border-bottom:1px solid var(--line);font-size:var(--t-sm)}
.jump a{color:var(--ink-2);text-decoration:none;display:inline-block;min-height:24px;white-space:nowrap}
.jump a:hover{color:var(--ink);text-decoration:underline;text-underline-offset:4px}
.jump a[aria-current]{color:var(--ink);font-weight:600;text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:6px}
body.tabs:not(:has(#f:not(:placeholder-shown))) .grp:not(.on){display:none}  /* one region at a time; a search looks in all */
.rsel{display:none;align-items:center;gap:10px;width:100%;color:var(--ink-2)}
.rsel select{flex:1;min-width:0;min-height:44px;font:inherit;font-size:var(--t-base);color:var(--ink);background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:0 10px}
.rsel select:focus-visible{outline:2px solid var(--pen);outline-offset:2px}
@media (max-width:639px){body.tabs .jump a{display:none}body.tabs .rsel{display:flex}.jump{overflow:visible}}  /* phones: one native select instead of a 13-tab row */
.eps li{scroll-margin-top:64px}
.reg{scroll-margin-top:calc(var(--jh,64px) + 8px)}  /* --jh: the sticky jump row's height, set by script (it wraps to two lines) */
body:has(#f:not(:placeholder-shown)) :is(.country,.jump){display:none}  /* results start right under the search */
body:has(#f:not(:placeholder-shown)) #regions{margin-top:40px}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
@media (max-width:1023px){.cg{grid-template-columns:repeat(2,minmax(0,1fr))}.cg .main{grid-column:1/-1}}
@media (max-width:639px){.cg{grid-template-columns:1fr}.country,#regions{margin-top:64px}}
@media (max-width:759px){
  .lh{display:none}
  .eps{grid-template-columns:44px minmax(0,1fr);column-gap:14px}
  .eps li{padding:10px 0}
  .sil{grid-row:1/3;align-self:start}
  .eps h4{grid-row:1}
  .top{display:block;grid-column:2;grid-row:2;margin:2px 0 0}
  .who,.vt{display:inline;font-size:var(--t-xs)}
  .vt::before{content:" · "}
  .eps .dhm{grid-row:3}
  .acts{grid-row:4}
}
@media (max-width:599px){main{padding:24px 16px 48px}.lede{font-size:var(--t-base);margin-bottom:20px}#f{font-size:var(--t-base)}.cap{margin-top:16px}}
@media (pointer:coarse){.sw button{min-height:44px}.older summary,.fold summary{min-height:44px}.el a{min-height:44px}.el a.now{padding:0 16px}.country li a,.jump a,.cg h3 a{display:inline-flex;align-items:center;min-height:44px}}
"""
INDEX_JS = """
document.querySelectorAll(".try button").forEach(b => b.addEventListener("click", () => { const f = document.getElementById("f"); f.value = b.textContent; f.dispatchEvent(new Event("input")); f.focus(); }));
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
    s.textContent = [li.closest(".grp").querySelector(".reg").textContent, (li.querySelector(".who") || {}).textContent].filter(Boolean).join(" · ");
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
    : shown === 1 ? "1 περιφέρεια. Enter για τον πιο πρόσφατο χάρτη." : `${shown} περιφέρειες`;
});
// Election switcher: every row's name opens the chosen election. Without script each row lists all its elections.
const sw = document.querySelector(".sw");
const open = e => {
  sw.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b.dataset.e === e));
  for (const li of items) li.querySelector("h4 a").href = (li.querySelector(`.el a[data-e="${e}"]`) || li.querySelector(".el a")).href;
};
sw.addEventListener("click", ev => { const b = ev.target.closest("button"); if (b) open(b.dataset.e); });
sw.hidden = false;
document.body.classList.add("pick");
open(sw.querySelector("button").dataset.e);
// Region tabs: the jump row shows one region at a time. Without script every region stays listed.
const groups = [...document.querySelectorAll(".grp")], tabs = [...document.querySelectorAll(".jump a")];
const rsel = document.querySelector(".rsel select");
rsel.replaceChildren(...tabs.map(a => new Option(a.textContent, a.hash.slice(1))));
rsel.addEventListener("change", () => { try { history.pushState(null, "", "#" + rsel.value); } catch { /* sandboxed srcdoc viewers forbid history calls: the page works, only the link does not follow */ } show(rsel.value); });
const pick = g => {
  groups.forEach(x => x.classList.toggle("on", x === g));
  const id = g.querySelector(".reg").id; if (rsel.value !== id) rsel.value = id;
  tabs.forEach(a => a.hash === "#" + g.querySelector(".reg").id ? a.setAttribute("aria-current", "true") : a.removeAttribute("aria-current"));
};
const jump = document.querySelector(".jump"), setJh = () => document.documentElement.style.setProperty("--jh", jump.offsetHeight + "px");
setJh(); addEventListener("resize", setJh);
const show = id => {
  const el = document.getElementById(id), g = el && el.closest(".grp");
  if (g) { pick(g); if (jump.offsetHeight) setJh(); el.scrollIntoView({behavior: "instant"}); } else if (!location.hash || !document.querySelector(".grp.on")) pick(groups[0]);  // back to the bare address = the first region
};
const fromHash = () => show(location.hash.slice(1));
document.body.classList.add("tabs");
fromHash();
addEventListener("hashchange", fromHash);
document.querySelector(".jump").addEventListener("click", e => {
  const a = e.target.closest("a");
  if (a) { e.preventDefault(); try { history.pushState(null, "", a.hash); } catch { /* sandboxed srcdoc viewers forbid history calls: the page works, only the link does not follow */ } show(a.hash.slice(1)); }
});
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
    """One ledger row. The name opens the newest election (the switcher retargets it); `chips` are the
    election links, newest first: without script they show in the row, the older ones folded into a <details>.
    `note` is the optional list of municipalities."""
    now, *older = chips
    folded = (f'<details class="older"><summary>Παλαιότερες εκλογές ({len(older)})</summary>'
              f'<p class="el">{"".join(older)}</p></details>') if older else ""
    return (f'<li id="ep-{ep}" data-k="{html.escape(keys)}" data-n="{n_own}"><h4><a href="{href}">{html.escape(name)}</a></h4>'
            f'{sil}{lead}{note}<div class="acts"><p class="el">{now}</p>{folded}</div></li>')

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
        t = top.get(name)
        # The cross marks the candidate with the most crosses: the one mark on the page that carries data.
        lead = (f'<p class="top"><span class="sr">{TOP_KEY}: </span><span class="who"><b>{html.escape(t[0])}</b> '
                f'({html.escape(t[1])})</span> <span class="vt">{f"{t[2]:,}".replace(",", ".")}</span></p>' if t else "")
        by_region.setdefault(region_of.get(latest["ep"], "Λοιπές"), []).append(
            card(latest["ep"], name, k, len(own), lead, note, chips, urllib.parse.quote(links[-1][0]), latest.get("sil", "")))
    # the link name carries the note beside it, so two links to the same constituency read differently in a list of links
    nikh_rows = "".join(
        (lambda note: f'<li><a href="{urllib.parse.quote(f)}" aria-label="{html.escape(m["ep_name"])}, {note}">{html.escape(m["ep_name"])}</a> <span>{note}</span></li>')(
            ELECTION_NAMES.get(m["election"], m["election"])
            + (", " + html.escape(elected[m["ep"]]) if m["election"] == "2023/june" and m["ep"] in elected else ""))
        for f, m in nikh)
    nikh_rows += "".join(f'<li><a href="{urllib.parse.quote(f)}" aria-label="{html.escape(m["ep_name"])}, {html.escape(m["label"])}">{html.escape(m["ep_name"])}</a> <span>{html.escape(m["label"])}</span></li>'
                         for f, m in tm if "_tm_131-" not in f)
    groups = "".join(f'<section class="grp"><h3 class="reg" id="reg-{i}">{html.escape(region)}</h3><div class="lh" aria-hidden="true"><span>Περιφέρεια</span><span>{TOP_KEY}</span><span>Σταυροί</span></div><ul class="eps">{"".join(lis)}</ul></section>'
                     for i, (region, lis) in enumerate(by_region.items()) if lis)
    jump = "".join(f'<a href="#reg-{i}">{html.escape(region)}</a>' for i, (region, lis) in enumerate(by_region.items()) if lis)
    switch = "".join(f'<button type="button" data-e="{e}" aria-pressed="false">{n}</button>' for e, n in reversed(ELECTION_NAMES.items()))
    gr = HERE / "out" / "greece_map.html"
    greece = gr.read_text(encoding="utf-8") if gr.exists() else ""  # written by compare.py
    nikh_n = nikh_rows.count("<li>")
    coverage = "".join(
        f'<li><a href="index_{e.replace("/", "-")}.html">{name}</a></li>' for e, name in reversed(ELECTION_NAMES.items())
        if (OUT / f'index_{e.replace("/", "-")}.html').exists())
    last = list(ELECTIONS)[-1]
    n_tm = None
    if DB.exists():
        with sqlite3.connect(DB) as con:
            n_tm = con.execute("SELECT COUNT(*) FROM station WHERE election=? AND kind='Κ'", (last,)).fetchone()[0]
    dots = lambda n: f"{n:,}".replace(",", ".")
    figs = [(len(eps), "εκλογικές περιφέρειες"), (len(ELECTIONS), f"εκλογές ({list(ELECTIONS)[0][:4]}–{last[:4]})")]
    figs += [(n_tm, "εκλογικά τμήματα")] if n_tm else []
    nums = " · ".join(f'<span class="nb"><b>{dots(n)}</b>&nbsp;{label}</span>' for n, label in figs)
    (OUT / "index.html").write_text(secure(fill(f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Χάρτες σταυρών</title>
{meta("Χάρτες σταυρών", "Χάρτες αποτελεσμάτων των ελληνικών εκλογών ανά κοινότητα και εκλογικό τμήμα.")}
{FONTS}
<script>/*THEME_JS*/</script>
<style>{INDEX_CSS}</style></head><body><main id="main">
<!--HEADER-->
<header>
<h1>Χάρτες σταυρών</h1>
<p class="lede">Πού ψηφίστηκε κάθε κόμμα και κάθε υποψήφιος, ανά κοινότητα και εκλογικό τμήμα.</p>
<div id="s" hidden><label class="fl" for="f">Αναζήτηση περιφέρειας</label>
<div class="sf"><input id="f" type="search" role="combobox" aria-expanded="false" aria-controls="sug" aria-autocomplete="list" placeholder="Δήμος ή νομός, π.χ. Πάτρα, Αργολίδα" autocomplete="off" enterkeyhint="search" spellcheck="false">
<ul id="sug" class="sug" role="listbox" aria-label="Προτάσεις" hidden></ul></div>
<p id="n" aria-live="polite"></p>
<p class="try">Δοκίμασε: <button type="button">Αθήνα</button><button type="button">Θεσσαλονίκη</button><button type="button">Πάτρα</button><a class="brw" href="#regions">ή περιήγηση ανά περιφέρεια &darr;</a></p></div>
<p class="cap">{nums}</p>
{greece}
</header>
<section class="country" aria-labelledby="ct"><h2 id="ct">Χάρτες και εργαλεία για όλη τη χώρα</h2><div class="cg">
<div class="main"><h3><a href="compare.html">Σύγκριση εκλογών <span aria-hidden="true">&rarr;</span></a></h3><p>Πρώτο κόμμα και ποσοστά ανά κοινότητα, για όλες τις αναμετρήσεις.</p><p class="els">{" · ".join(ELECTION_NAMES.values())}</p>
<h3><a href="forecast.html">Πρόβλεψη βουλευτικών εκλογών <span aria-hidden="true">&rarr;</span></a></h3><p>Πιθανότητες αυτοδυναμίας, ποσοστά και έδρες κάθε κόμματος, από τον μέσο όρο των δημοσκοπήσεων.</p></div>
<div id="tm"><h3>Αναφορές και εξαγωγές</h3><p>Αναλυτικές αναφορές ανά κόμμα και εκλογή, με δεδομένα για λήψη.</p>
<ul><li><a href="NIKH_eklegmenoi_2023.html">Αναφορά Μαΐου–Ιουνίου</a></li>
<li><a href="nikh_2023-2024.html">Χάρτης όλης της χώρας, 2019–2024</a></li>
<li><a href="nikh_polls.html">Δημοσκοπήσεις από το 2023</a></li>
<li><a href="../exports/NIKH_2023_ana_dhm_enotita.csv">CSV ανά δημοτική ενότητα</a></li></ul>
<details class="fold"><summary>Περισσότερες αναφορές ({nikh_n + 1})</summary><ul><li><a href="nikh_targets.html">Χάρτης στόχευσης: κάστρα, φθορά, δεξαμενές, έδρες</a></li>{nikh_rows}</ul></details></div>
<div id="cov"><h3>Κάλυψη χαρτών</h3><p>Πόσοι ψήφοι αποδίδονται στον χάρτη, ανά νομό και εκλογή.</p><ul>{coverage}</ul></div>
</div></section>
<section id="regions" aria-labelledby="rt"><h2 id="rt">Εκλογικές περιφέρειες</h2>
<div class="sw" role="group" aria-label="Άνοιγμα στην εκλογή" hidden><span class="swl">Άνοιγμα στην εκλογή</span>{switch}</div>
<nav class="jump" aria-label="Περιφέρειες">{jump}<label class="rsel">Περιφέρεια <select></select></label></nav>
{groups}
</section>
{footer(" Οι ψήφοι ετεροδημοτών και ειδικών τμημάτων δεν έχουν θέση στον χάρτη.", home=False)}
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
