"""Structure checks on the generated pages in out/ (stdlib html.parser, no browser).

Run: python -I -X utf8 -m unittest discover -s tests
Needs the pages built (build.py <election> all, build.py index, compare.py).
"""
import json
import re
import struct
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

OUT = Path(__file__).resolve().parent.parent / "out"
PLACEHOLDER = re.compile(r"/\*[A-Z_]{4,}\*/|<!--[A-Z]{4,}-->")
# Pages that load shared.js and draw a map or search: the new templates. Station maps and the NIKH report are
# rebuilt from the venue spreadsheet, so a stale one is not a failure here.
APP = sorted(p for p in OUT.glob("*.html") if re.fullmatch(r"(2019|2023-may|2023-june|2024-euro)_\d+\.html", p.name))
SPECIAL = [OUT / "index.html", OUT / "compare.html", OUT / "nikh_polls.html", OUT / "forecast.html"]
FRAGMENTS = {"greece_map.html"}  # a <figure> the index inlines, not a page
ALL = sorted(p for p in OUT.glob("*.html") if p.name not in FRAGMENTS)
sys.path.insert(0, str(OUT.parent))


def read(p):
    return p.read_text(encoding="utf-8")


@unittest.skipUnless(APP and all(p.exists() for p in SPECIAL), "pages not built")
class Pages(unittest.TestCase):
    def test_no_placeholder_left(self):
        for p in APP + SPECIAL:
            s = read(p)
            # only the data placeholder the template itself documents may appear in comments of inlined code
            left = [m for m in PLACEHOLDER.findall(s) if m != "/*DATA*/"]
            self.assertFalse(left, f"{p.name}: {left[:3]}")

    def test_helpers_defined_once(self):
        for p in APP + SPECIAL:
            s = read(p)
            self.assertEqual(s.count("const fold ="), 1, p.name)
            self.assertEqual(s.count("const binLabel ="), 1, p.name)

    def test_maps_use_shared_options(self):
        for p in APP + [OUT / "compare.html"]:
            s = read(p)
            self.assertIn("L.map(", s, p.name)
            self.assertEqual(len(re.findall(r'L\.map\("map", (?!mapOptions\()', s)), 0, p.name)

    def test_share_tags(self):
        for p in ALL:
            s = read(p)
            for tag in ('property="og:title"', 'property="og:description"', 'property="og:type"',
                        'property="og:locale"', 'name="description"', 'name="twitter:card"', "<title>"):
                self.assertIn(tag, s, f"{p.name}: {tag}")

    def test_absolute_urls_only_with_site_url(self):
        from config import SITE_URL
        for p in ALL:
            s = read(p)
            url = re.search(r'property="og:url" content="([^"]*)"', s)
            canon = re.search(r'rel="canonical" href="([^"]*)"', s)
            if not SITE_URL:  # a relative or guessed address is worse than none
                self.assertFalse(url or canon, p.name)
                continue
            want = f"{SITE_URL}/out/{quote(p.name)}"
            self.assertEqual(url and url.group(1), want, p.name)
            self.assertEqual(canon and canon.group(1), want, p.name)

    def test_og_image_tags(self):
        from config import SITE_URL, og_kind
        for p in ALL:
            s = read(p)
            img = re.search(r'property="og:image" content="([^"]*)"', s)
            self.assertTrue((OUT / "og" / f"{og_kind(p.name)}.png").exists(), f"{p.name}: run og_image.py")
            if not SITE_URL:
                self.assertIsNone(img, p.name)
                continue
            self.assertEqual(img and img.group(1), f"{SITE_URL}/out/og/{og_kind(p.name)}.png", p.name)
            for tag in ('property="og:image:alt"', 'content="summary_large_image"', 'name="twitter:image"'):
                self.assertIn(tag, s, f"{p.name}: {tag}")

    def test_og_pictures_are_1200_by_630(self):
        pictures = sorted((OUT / "og").glob("*.png"))
        self.assertTrue(pictures)
        for png in pictures:
            data = png.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", png.name)
            self.assertEqual(struct.unpack(">II", data[16:24]), (1200, 630), png.name)
            self.assertLess(len(data), 300_000, png.name)

    def test_leaflet_is_self_hosted_and_pinned(self):
        import base64
        import hashlib
        for p in ALL:
            s = read(p)
            self.assertNotIn("cdnjs", s, p.name)
            for tag in re.findall(r"<(?:script|link)[^>]+leaflet[^>]+>", s):
                url = re.search(r'(?:src|href)="(vendor/leaflet-1.9.4/[^"]+)"', tag)
                want = re.search(r'integrity="sha256-([^"]+)"', tag)
                self.assertTrue(url and want, f"{p.name}: {tag}")
                digest = base64.b64encode(hashlib.sha256((OUT / url.group(1)).read_bytes()).digest()).decode()
                self.assertEqual(want.group(1), digest, f"{p.name}: {url.group(1)}")

    def test_no_middle_dot_in_titles(self):
        for p in APP:
            s = read(p)
            self.assertNotIn("`${T.title} · ${D.ep_name}`", s, p.name)

    def test_header_and_footer(self):
        for p in APP + SPECIAL:
            s = read(p)
            self.assertEqual(len(re.findall(r'<nav aria-label="Κύριο μενού">', s)), 1, p.name)
            self.assertIn("aria-current=", s, p.name)
            self.assertIn('class="skip"', s, p.name)
            self.assertRegex(s, r"Ενημέρωση: \d{1,2} \S+ \d{4}", p.name)
            self.assertNotIn("github.com", s, p.name)
        # a map page can switch to its constituency's other elections
        self.assertIn('class="ctx"', read(APP[0]))

    def test_tokens_written_once_with_light_dark(self):
        for p in APP + SPECIAL:
            s = read(p)
            self.assertIn("light-dark(", s, p.name)
            self.assertNotIn("@media (prefers-color-scheme:dark){:root:not", s, p.name)
            self.assertEqual(s.count(":root[data-theme=dark]{color-scheme:dark}"), 1, p.name)

    def test_fonts_self_hosted(self):
        for p in APP + SPECIAL:
            s = read(p)
            self.assertNotIn("fonts.googleapis.com", s, p.name)
            self.assertNotIn("fonts.gstatic.com", s, p.name)
            self.assertIn("font-src 'self'", s, p.name)
        files = set(re.findall(r"url\(fonts/([^)]+\.woff2)\)", read(SPECIAL[0])))
        self.assertTrue(files)
        self.assertTrue(all((OUT / "fonts" / f).exists() for f in files), files)

    def test_skip_link_text(self):
        bad = [p.name for p in OUT.glob("*.html") if "σττ" in read(p)]
        self.assertFalse(bad, bad[:5])

    def test_no_ministry_quote_for_tonos_alpha(self):
        # the ministry writes "Άνδρου" as "’νδρου"; config.accented fixes it where names enter the database
        bad = [p.name for p in OUT.glob("*.html") if re.search("’[Α-Ωα-ω]", read(p))]
        self.assertFalse(bad, bad[:5])

    def test_csp_matches_inline_blocks(self):
        import base64
        import hashlib
        h = lambda t: "'sha256-" + base64.b64encode(hashlib.sha256(t.encode()).digest()).decode() + "'"
        for p in ALL:
            s = read(p)
            csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', s)
            self.assertTrue(csp, p.name)
            self.assertIn('<meta name="referrer" content="strict-origin-when-cross-origin">', s, p.name)
            blocks = re.findall(r"<(script|style)>(.*?)</\1>", s, re.S)  # secure() hashes the blocks without attributes
            self.assertTrue(blocks, p.name)
            for tag, body in blocks:
                self.assertIn(h(body), csp.group(1), f"{p.name}: inline {tag} not allowed")
            self.assertIsNone(re.search(r"\son[a-z]+=\"", s), f"{p.name}: inline handler")
            for tag in re.findall(r"<(?:script|link)[^>]+leaflet[^>]+>", s):
                self.assertIn("integrity=", tag, p.name)


class Cards(HTMLParser):
    """Collects, per index card, whether it has a <details class=older> and how many election links it shows."""
    def __init__(self):
        super().__init__()
        self.cards, self.cur, self.nation_at, self.eps_at, self.pos, self.groups = [], None, None, None, 0, 0
        self.h4 = 0
        self.in_h4 = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.pos += 1
        cls = (a.get("class") or "").split()
        if tag == "section" and a.get("id") == "country":  # the nationwide tools, ahead of the constituency rows
            self.nation_at = self.pos
        elif tag == "h4":
            self.h4 += 1
            self.in_h4 = True
        elif tag == "ul" and "eps" in cls:
            self.eps_at = self.pos
        elif tag == "li" and (a.get("id") or "").startswith("ep-"):
            self.cur = {"older": False, "links": 0, "sil": False}
            self.cards.append(self.cur)
        elif tag == "section" and "grp" in cls:
            self.groups += 1
        elif tag == "svg" and "sil" in cls and self.cur is not None:
            self.cur["sil"] = True
        elif tag == "details" and "older" in cls and self.cur is not None:
            self.cur["older"] = True
        elif tag == "a" and self.cur is not None and not self.in_h4 and a.get("href", "").endswith(".html"):
            self.cur["links"] += 1

    def handle_endtag(self, tag):
        if tag == "h4":
            self.in_h4 = False


@unittest.skipUnless((OUT / "index.html").exists(), "index not built")
class Index(unittest.TestCase):
    def test_cards_fold_older_elections(self):
        c = Cards()
        c.feed(read(OUT / "index.html"))
        self.assertGreater(len(c.cards), 50)
        for card in c.cards:
            self.assertEqual(card["older"], card["links"] > 1)

    def test_cards_have_silhouette_and_region(self):
        c = Cards()
        c.feed(read(OUT / "index.html"))
        self.assertTrue(all(card["sil"] for card in c.cards))
        self.assertEqual(c.groups, 13)

    def test_every_constituency_has_a_region(self):
        import json
        import sys
        sys.path.insert(0, str(OUT.parent))
        from config import REGIONS
        known = {ep for _, eps in REGIONS for ep in eps}
        built = {m["ep"] for f, m in json.loads(read(OUT / "maps.json")).items() if "_tm_" not in f}
        self.assertFalse(built - known, f"no region: {sorted(built - known)}")

    def test_nationwide_block_before_list(self):
        c = Cards()
        c.feed(read(OUT / "index.html"))
        self.assertTrue(c.nation_at and c.eps_at and c.nation_at < c.eps_at)

    def test_heading_outline(self):
        s = read(OUT / "index.html")
        c = Cards()
        c.feed(s)
        self.assertEqual(len(re.findall(r"<h2[ >]", s)), 7)  # two doors, parties and candidates, constituencies, and the footer's three columns
        self.assertIn('href="forecast.html"', s)
        self.assertEqual(len(re.findall(r'<h3 class="reg" id="reg-\d+">', s)), 13)
        self.assertEqual(c.h4, len(c.cards))
        self.assertEqual(s.count("<h1>"), 1)


class SecureLeaflet(unittest.TestCase):
    """secure() points Leaflet at out/vendor/ for pages in out/, and at cdnjs for a page written anywhere else."""
    page = ('<meta charset="utf-8"><link rel="stylesheet" href="vendor/leaflet-1.9.4/leaflet.min.css" integrity="sha256-x">'
            '<script src="vendor/leaflet-1.9.4/leaflet.min.js" integrity="sha256-y"></script><script>1</script>')

    def test_page_in_out_uses_vendor(self):
        from web import secure
        s = secure(self.page, OUT / "x.html")
        self.assertIn('src="vendor/leaflet-1.9.4/leaflet.min.js"', s)
        self.assertIn("script-src 'sha256-", s)
        self.assertIn(" 'self';", s.split("style-src-elem")[0])
        self.assertNotIn("cdnjs", s)

    def test_page_elsewhere_uses_cdn(self):
        from web import secure
        for path in (OUT.parent / "client" / "x.html", None):
            s = secure(self.page, path)
            self.assertNotIn("vendor/leaflet-1.9.4", s)
            self.assertIn('src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"', s)
            csp = re.search(r'Content-Security-Policy" content="([^"]+)"', s).group(1)
            self.assertIn("https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js", csp)
            self.assertNotIn("'self';", csp.split("style-src-elem")[0])


class VercelHeaders(unittest.TestCase):
    """The headers a <meta> cannot set. Needs no built page: vercel.json is in the repo."""
    rules = json.loads((OUT.parent / "vercel.json").read_text(encoding="utf-8"))["headers"]

    def header(self, source, key):
        for rule in self.rules:
            if rule["source"] == source:
                return next((h["value"] for h in rule["headers"] if h["key"] == key), None)
        self.fail(f"no rule for {source}")

    def test_csp_header(self):
        csp = self.header("/(.*)", "Content-Security-Policy")
        for directive in ("frame-ancestors 'none'", "object-src 'none'", "base-uri 'none'", "form-action 'none'",
                          "upgrade-insecure-requests"):
            self.assertIn(directive, csp)

    def test_plain_headers(self):
        self.assertEqual(self.header("/(.*)", "X-Frame-Options"), "DENY")
        self.assertEqual(self.header("/(.*)", "X-Content-Type-Options"), "nosniff")
        self.assertEqual(self.header("/(.*)", "Cross-Origin-Opener-Policy"), "same-origin")
        # tile.openstreetmap.org refuses requests without a Referer, so never "no-referrer"
        self.assertEqual(self.header("/(.*)", "Referrer-Policy"), "strict-origin-when-cross-origin")

    def test_site_is_not_indexed(self):
        self.assertEqual(self.header("/(.*)", "X-Robots-Tag"), "noindex, nofollow, noarchive")
        robots = (OUT.parent / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("Disallow: /", robots)
        for search_engine in ("Googlebot", "Bingbot", "*"):  # a Disallow for these would stop them reading the noindex
            self.assertNotIn(f"User-agent: {search_engine}", robots)
        self.assertIn("!/robots.txt", (OUT.parent / ".vercelignore").read_text(encoding="utf-8"))

    def test_permissions_policy_keeps_copy_button_working(self):
        policy = self.header("/(.*)", "Permissions-Policy")
        for feature in ("camera", "microphone", "geolocation", "payment", "usb", "accelerometer", "gyroscope", "magnetometer",
                        "bluetooth", "serial", "hid", "midi", "display-capture"):
            self.assertIn(f"{feature}=()", policy)
        for feature in ("clipboard-write", "fullscreen"):  # the copy-link button and the map controls need these
            self.assertNotIn(feature, policy)

    def test_resource_policy_open_only_for_share_pictures(self):
        self.assertEqual(self.header("/((?!out/og/).*)", "Cross-Origin-Resource-Policy"), "same-origin")
        self.assertEqual(self.header("/out/og/(.*)", "Cross-Origin-Resource-Policy"), "cross-origin")
        self.assertFalse(self.header("/(.*)", "Cross-Origin-Resource-Policy"))  # that rule would also cover out/og/

    def test_vendor_files_cache_for_a_year(self):
        # safe only because the folder name carries the version: a new Leaflet goes to a new folder
        self.assertEqual(self.header("/out/vendor/(.*)", "Cache-Control"), "public, max-age=31536000, immutable")
        self.assertRegex(str(next(p for p in (OUT / "vendor").iterdir() if p.is_dir()).name), r"-\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
