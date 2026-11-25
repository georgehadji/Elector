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
TOP_KEY = "Πρώτος σε σταυρούς"  # screen-reader prefix of each card's leading candidate, followed by the election

def greece_figure(areas, key, caption, size=440):
    """Static map of Greece for the index: `areas` = [(GeoJSON geometry, colour)], `key` = [(name, colour)].
    One path per colour; neighbouring areas keep their own outline, simplified to whole units."""
    to_xy, w, h = frame([g for g, _ in areas], size)
    by_color = defaultdict(list)
    for g, color in areas:
        by_color[color].extend(exteriors(g))
    paths = "".join(f'<path fill="{c}" stroke="{c}" d="{path(rings, to_xy, 0.8, 1.0)}"/>' for c, rings in by_color.items())
    swatches = "".join(f'<span class="k"><i style="background:{c}"></i>{html.escape(n)}</span>' for n, c in key)
    # the map itself opens the comparison; the index's own "Σύγκριση εκλογών" door says it in words
    return (f'<figure class="gr"><a href="compare.html"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(caption)}">'
            f'<g stroke-width=".6" stroke-linejoin="round">{paths}</g></svg></a>'
            f'<figcaption>{html.escape(caption)}.<span class="keys">{swatches}</span></figcaption></figure>')

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
/* the cross marks what is chosen: the open election, the leading candidate of a row */
:is(.sw button[aria-pressed=true],.eps .who b,.tk)::before{content:"";display:inline-block;width:.6em;height:.6em;margin-right:.35em;background:currentColor;clip-path:var(--xm)}
.lede{max-width:34em;margin:16px 0 28px;color:var(--ink-2);font-size:var(--t-lg)}
.fl{display:block;margin:0 0 6px;font-size:var(--t-sm);font-weight:600;color:var(--ink)}
#f{width:100%;max-width:560px;min-height:48px;font:inherit;font-size:var(--t-lg);color:var(--ink);background:var(--paper) no-repeat 14px 50% / 20px;
   border:1.5px solid var(--ink-2);border-radius:8px;padding:10px 14px 10px 46px}
#f::placeholder{color:var(--ink-2)}
#f:focus-visible{outline:2px solid var(--pen);outline-offset:2px;border-color:var(--pen)}
#n{margin:10px 0 0;min-height:1.55em;color:var(--ink-2);font-size:var(--t-sm)}
#n:empty{min-height:0;margin:0}
.try{margin:10px 0 0;font-size:var(--t-sm)}
.try a{display:inline-flex;align-items:center;min-height:24px;color:var(--ink-2);text-underline-offset:3px}
.try a:hover{color:var(--pen)}
.sf{position:relative;max-width:560px}
.sf::before{content:"";position:absolute;left:14px;top:14px;width:20px;height:20px;background:var(--ink-2);-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='8.5' cy='8.5' r='5.5'/%3E%3Cpath d='M13 13l4.5 4.5'/%3E%3C/svg%3E") center/contain no-repeat;mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='8.5' cy='8.5' r='5.5'/%3E%3Cpath d='M13 13l4.5 4.5'/%3E%3C/svg%3E") center/contain no-repeat;pointer-events:none;z-index:1}
.sug{position:absolute;left:0;right:0;top:100%;z-index:20;list-style:none;margin:4px 0 0;padding:4px;background:var(--paper);border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px color-mix(in srgb,var(--ink) 18%,transparent)}
.sug[hidden]{display:none}
.sug a{display:grid;gap:1px;padding:10px 12px;min-height:44px;color:var(--ink);text-decoration:none;border-radius:6px}
.sug a b{font:600 1.0625rem/1.25 "IBM Plex Sans",system-ui,sans-serif}
.sug a span{color:var(--ink-2);font-size:var(--t-sm)}
.sug a.act,.sug a:hover{background:var(--wash)}
.sug a.more{min-height:36px;padding:8px 12px;color:var(--pen);font-size:var(--t-sm)}
/* the two other doors, under the search: whole card is the link */
.doors{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;max-width:560px;margin:24px 0 0}
.door{position:relative;border:1px solid var(--line);border-top:3px solid var(--pen);border-radius:8px;padding:12px 16px 14px}
.door:hover,.door:has(a:active){background:var(--wash)}
.door h2{font:600 1.25rem/1.25 "IBM Plex Sans",system-ui,sans-serif;margin:0 0 6px}
.door h2 a{color:var(--ink);text-decoration:none}
.door h2 a::after{content:"";position:absolute;inset:0;border-radius:8px}
.door h2 span{display:inline-block;color:var(--pen);transition:transform .15s}
.door:hover h2 span{transform:translateX(4px)}
.door p{margin:0;color:var(--ink-2);font-size:var(--t-sm);line-height:1.45}
.cap{margin:20px 0 0;max-width:34em;font-size:var(--t-sm);color:var(--ink-2)}
.cap b{color:var(--ink);font-weight:600}
.nb{white-space:nowrap}
.gr{margin:20px 0 0;max-width:380px}
.gr a:first-child{display:block;border-radius:8px}
.gr a:first-child:hover svg{opacity:.88}
.gr svg{display:block;width:100%;height:auto;max-height:260px}
.gr figcaption{margin:6px 0 0;font-size:var(--t-xs);color:var(--ink-2)}
.gr .keys{display:flex;flex-wrap:wrap;gap:2px 12px;margin-top:4px}
.gr .k{display:inline-flex;align-items:center;white-space:nowrap}
.gr .k i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ink-2) 75%,var(--paper))}
@media (min-width:900px){
  /* one focal point: title, search and the two doors on the left, the map as tall as the first screen on the right */
  main>header:not(.bar){display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,540px);column-gap:48px;align-content:center;min-height:calc(100svh - 190px)}
  main>header:not(.bar)>:not(.gr){grid-column:1}
  .gr{grid-column:2;grid-row:1/span 7;align-self:center;margin:0;max-width:none}
  .gr svg{max-height:min(68svh,640px);margin:0 auto}
}
h2.sec{font:600 1.5rem/1.2 "IBM Plex Sans",system-ui,sans-serif;letter-spacing:-.01em;margin:0 0 16px}
/* for parties and candidates: three columns of reports, data and coverage */
.party,#regions{margin-top:96px}
.pg{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0 48px;align-items:start}
.pg>div{border-top:2px solid var(--ink);padding:12px 0 28px}
.pg h3{font:600 1.25rem/1.25 "IBM Plex Sans",system-ui,sans-serif;margin:0 0 6px}
.pg h3 a{color:var(--ink);text-underline-offset:4px}
.pg p{color:var(--ink-2);margin:0 0 8px}
.pg ul{margin:0;padding:0;list-style:none}
.pg li{padding:3px 0}
.pg li span{color:var(--ink-2);font-size:var(--t-sm)}
.older summary,.fold summary{display:flex;align-items:center;min-height:32px;cursor:pointer;color:var(--ink-2);font-size:var(--t-sm)}
.fold summary::before{content:"+";display:inline-block;width:1.25em;font-size:var(--t-lg);line-height:1;transition:transform .15s}
.fold[open]>summary::before{transform:rotate(45deg)}
.older[open]>:not(summary),.fold[open]>:not(summary){animation:fade .15s ease-out}
@keyframes fade{from{opacity:0}}
@media (prefers-reduced-motion:reduce){.door h2 span,.fold summary::before{transition:none}.older[open]>:not(summary),.fold[open]>:not(summary){animation:none}}
.pg a:active,.eps li a:active,.older summary:active,.fold summary:active{background:var(--wash)}
/* constituencies: every region open, in columns; a row opens the map of the chosen election */
.sw{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;margin:0 0 8px;font-size:var(--t-sm);color:var(--ink-2)}
.sw[hidden]{display:none}
.sw .swl{margin-right:6px}
.sw button{font:inherit;color:var(--ink-2);background:none;border:1px solid var(--line);border-radius:16px;padding:0 14px;min-height:36px;cursor:pointer}
.sw button:hover{color:var(--pen)}
.sw button:active{background:var(--wash)}
.sw button[aria-pressed=true]{color:var(--pen);border-color:var(--pen);background:var(--wash);font-weight:600}
.tk{margin:0;font-size:var(--t-sm);color:var(--ink-2)}
.tk[hidden]{display:none}
.cols{columns:3 280px;column-gap:40px}
.grp{break-inside:avoid;padding-top:20px}
.grp:not(:has(li:not([hidden]))){display:none}  /* a region head goes with its cards */
.reg{margin:0 0 4px;padding-bottom:6px;border-bottom:2px solid var(--ink);font:600 var(--t-sm)/1.3 "IBM Plex Sans",system-ui,sans-serif;color:var(--ink)}
.eps{list-style:none;margin:0;padding:0}
.eps li{display:grid;grid-template-columns:28px minmax(0,1fr);column-gap:12px;position:relative;padding:8px 6px;margin:0 -6px;border-radius:6px;overflow-wrap:anywhere;scroll-margin-top:16px}
.eps li:hover{background:var(--wash)}
.sil{grid-column:1;grid-row:1/span 4;width:28px;height:28px;margin-top:1px;color:var(--ink-2)}
.sil path{fill:currentColor;fill-opacity:.22;stroke:currentColor;stroke-width:1;stroke-linejoin:round}
.eps h4{grid-column:2;margin:0;font:600 1.0625rem/1.3 "IBM Plex Sans",system-ui,sans-serif}
.eps h4 a{color:var(--ink);text-decoration:none}
.eps h4 a:hover{text-decoration:underline;text-underline-offset:4px}
.eps h4 a::after{content:"";position:absolute;inset:0}  /* the whole row opens the map */
.top,.eps .dhm,.acts{grid-column:2}
.top{margin:2px 0 0;font-size:var(--t-xs);color:var(--ink-2);line-height:1.4}
.top[hidden]{display:none}
.top b{color:var(--ink);font-weight:600}
.vt{font-variant-numeric:tabular-nums;white-space:nowrap}
.eps .dhm{position:relative;margin:2px 0 0;color:var(--ink-2);font-size:var(--t-xs);line-height:1.45}
.acts{position:relative;display:flex;flex-wrap:wrap;align-items:center;gap:0 14px;margin-top:4px}  /* every election, until the switcher takes over */
body.pick .acts{display:none}
.older[open]{flex:1 1 100%}
.older[open] summary{margin-bottom:4px}
.el{display:flex;flex-wrap:wrap;align-items:center;gap:4px 14px;margin:0}
.el a{display:inline-flex;align-items:center;min-height:32px;color:var(--ink-2);font-size:var(--t-sm);white-space:nowrap;
      text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
.el a:hover{color:var(--pen);text-decoration-color:var(--pen)}
.el a.now{padding:0 12px;border:1px solid var(--pen);border-radius:16px;color:var(--pen);background:var(--wash);
          text-decoration:none;font-weight:600}
.el a.now:hover{background:var(--pen);color:var(--paper)}
body:has(#f:not(:placeholder-shown)) .party{display:none}  /* results start right after the first screen */
body:has(#f:not(:placeholder-shown)) #regions{margin-top:40px}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
@media (max-width:1023px){.pg{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:639px){.pg{grid-template-columns:1fr}.party,#regions{margin-top:64px}}
@media (max-width:599px){main{padding:24px 16px 48px}.lede{font-size:var(--t-base);margin-bottom:20px}#f{font-size:var(--t-base)}
  .doors{gap:8px}.door{padding:10px 12px 12px}.door h2{font-size:1.0625rem}.cap{margin-top:16px}}
@media (pointer:coarse){.sw button{min-height:44px}.older summary,.fold summary{min-height:44px}.el a{min-height:44px}.el a.now{padding:0 16px}.pg li a,.pg h3 a,.try a{display:inline-flex;align-items:center;min-height:44px}}
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
    s.textContent = [li.closest(".grp").querySelector(".reg").textContent, (li.querySelector(".top:not([hidden]) .who") || {}).textContent].filter(Boolean).join(" · ");
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
const sw = document.querySelector(".sw");
const open = e => {
  let x = "";
  sw.querySelectorAll("button").forEach(b => { b.setAttribute("aria-pressed", b.dataset.e === e); if (b.dataset.e === e) x = b.dataset.x; });
  const tk = document.getElementById("tk"), xb = sw.querySelector(`button[data-e="${x}"]`);
  if (tk) { tk.hidden = !xb; if (xb) tk.querySelector("span").textContent = xb.textContent; }
  for (const li of items) {
    li.querySelector("h4 a").href = (li.querySelector(`.el a[data-e="${e}"]`) || li.querySelector(".el a")).href;
    li.querySelectorAll(".top").forEach(p => { p.hidden = p.dataset.e !== x; });
  }
};
sw.addEventListener("click", ev => { const b = ev.target.closest("button"); if (b) open(b.dataset.e); });
sw.hidden = false;
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
    return (f'<li id="ep-{ep}" data-k="{html.escape(keys)}" data-n="{n_own}"><h4><a href="{href}">{html.escape(name)}</a></h4>'
            f'{sil}{lead}{note}<div class="acts"><p class="el">{now}</p>{folded}</div></li>')

def _write_index(order, nikh, elected):
    """out/index.html: search with the two nationwide doors (forecast, comparison) and the map of Greece, the pages
    for parties and candidates, then every constituency with one link per election."""
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
        lead = "".join(
            f'<p class="top" data-e="{m["election"]}"{"" if m["election"] == crosses_of[default] else " hidden"}>'
            f'<span class="sr">{TOP_KEY}, {ELECTION_NAMES[m["election"]]}: </span><span class="who"><b>{html.escape(t[0])}</b> '
            f'({html.escape(t[1])})</span> · <span class="vt">{dots(t[2])} σταυροί</span></p>'
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
    tk = (f'<p class="tk" id="tk">{TOP_KEY}, <span>{ELECTION_NAMES[crosses_of[default]]}</span></p>' if crosses_of[default] else "")
    gr = HERE / "out" / "greece_map.html"
    greece = gr.read_text(encoding="utf-8") if gr.exists() else ""  # written by compare.py
    nikh_n = nikh_rows.count("<li>")
    coverage = "".join(
        f'<li><a href="index_{e.replace("/", "-")}.html">Κάλυψη: {name}</a></li>' for e, name in reversed(ELECTION_NAMES.items())
        if (OUT / f'index_{e.replace("/", "-")}.html').exists())
    first_year, last = list(ELECTIONS)[0][:4], list(ELECTIONS)[-1]
    n_tm = None
    if DB.exists():
        with sqlite3.connect(DB) as con:
            n_tm = con.execute("SELECT COUNT(*) FROM station WHERE election=? AND kind='Κ'", (last,)).fetchone()[0]
    figs = [(len(eps), "εκλογικές περιφέρειες"), (len(ELECTIONS), f"εκλογές ({first_year}–{last[:4]})")]
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
<p id="n" aria-live="polite"></p></div>
<p class="try"><a href="#regions">Όλες οι εκλογικές περιφέρειες &darr;</a></p>
<div class="doors">
<div class="door"><h2><a href="forecast.html">Πρόβλεψη εκλογών <span aria-hidden="true">&rarr;</span></a></h2><p>Αυτοδυναμία, ποσοστά και έδρες από τον μέσο όρο των δημοσκοπήσεων.</p></div>
<div class="door"><h2><a href="compare.html">Σύγκριση εκλογών <span aria-hidden="true">&rarr;</span></a></h2><p>Πρώτο κόμμα και ποσοστά ανά κοινότητα, {first_year}–{last[:4]}.</p></div>
</div>
<p class="cap">{nums}</p>
{greece}
</header>
<section class="party" aria-labelledby="pt"><h2 class="sec" id="pt">Για κόμματα και υποψηφίους</h2><div class="pg">
<div><h3>ΝΙΚΗ</h3><p>Αναφορές, χάρτες και δημοσκοπήσεις του κόμματος.</p>
<ul><li><a href="NIKH_eklegmenoi_2023.html">Εκλεγμένοι Μαΐου–Ιουνίου 2023</a></li>
<li><a href="nikh_2023-2024.html">Όλη η χώρα ανά διαμέρισμα, 2019–2024</a></li>
<li><a href="nikh_targets.html">Χάρτης στόχευσης: κάστρα, φθορά, δεξαμενές, έδρες</a></li>
<li><a href="nikh_polls.html">Στις δημοσκοπήσεις από το 2023</a></li></ul>
<details class="fold"><summary>Χάρτες ανά εκλογικό τμήμα ({nikh_n})</summary><ul>{nikh_rows}</ul></details></div>
<div><h3><a href="abroad.html">Εξωτερικό και επιστολική&nbsp;ψήφος&nbsp;<span aria-hidden="true">&rarr;</span></a></h3><p>Πώς ψήφισαν οι Έλληνες του εξωτερικού ανά χώρα και πόλη, και όσοι ψήφισαν επιστολικά.</p></div>
<div id="cov"><h3>Δεδομένα και κάλυψη</h3><p>Πόσοι ψήφοι αποδίδονται στον χάρτη, ανά νομό και εκλογή, και δεδομένα για λήψη.</p>
<ul>{coverage}<li><a href="../exports/NIKH_2023_ana_dhm_enotita.csv">ΝΙΚΗ 2023 ανά δημοτική ενότητα (CSV)</a></li></ul></div>
</div></section>
<section id="regions" aria-labelledby="rt"><h2 class="sec" id="rt">Εκλογικές περιφέρειες</h2>
<div class="sw" role="group" aria-label="Άνοιγμα στην εκλογή" data-d="{default}" hidden><span class="swl">Άνοιγμα στην εκλογή</span>{switch}</div>
{tk}
<div class="cols">{groups}</div>
</section>
{footer(" Οι ψήφοι των ειδικών τμημάτων (ετεροδημότες κ.ά.), οι επιστολικές και οι ψήφοι του εξωτερικού δεν έχουν θέση στον χάρτη· οι αριθμοί τους είναι σε κάθε σελίδα «Κάλυψη χαρτών» και η ανάλυσή τους στη σελίδα «Εξωτερικό και επιστολική ψήφος».", home=False)}
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
