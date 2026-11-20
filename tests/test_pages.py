"""Structure checks on the generated pages in out/ (stdlib html.parser, no browser).

Run: python -I -X utf8 -m unittest discover -s tests
Needs the pages built (build.py <election> all, build.py index, compare.py).
"""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "out"
PLACEHOLDER = re.compile(r"/\*[A-Z_]{4,}\*/|<!--[A-Z]{4,}-->")
# Pages that load shared.js and draw a map or search: the new templates. Station maps and the NIKH report are
# rebuilt from the venue spreadsheet, so a stale one is not a failure here.
APP = sorted(p for p in OUT.glob("*.html") if re.fullmatch(r"(2019|2023-may|2023-june|2024-euro)_\d+\.html", p.name))
SPECIAL = [OUT / "index.html", OUT / "compare.html"]


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
        for p in APP + [OUT / "compare.html"]:
            s = read(p)
            self.assertIn('property="og:title"', s, p.name)
            self.assertIn('name="description"', s, p.name)

    def test_no_middle_dot_in_titles(self):
        for p in APP:
            s = read(p)
            self.assertNotIn("`${T.title} · ${D.ep_name}`", s, p.name)

    def test_csp_matches_inline_blocks(self):
        import base64
        import hashlib
        h = lambda t: "'sha256-" + base64.b64encode(hashlib.sha256(t.encode()).digest()).decode() + "'"
        for p in APP + SPECIAL:
            s = read(p)
            csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', s)
            self.assertTrue(csp, p.name)
            for tag, body in re.findall(r"<(script|style)(?:\s[^>]*)?>(.*?)</>", s, re.S):
                if tag == "script" and "src=" in s[s.find(body) - 200:s.find(body)]:
                    continue
                self.assertIn(h(body), csp.group(1), f"{p.name}: inline {tag} not allowed")
            self.assertIsNone(re.search(r"\son[a-z]+=\"", s), f"{p.name}: inline handler")
            for tag in re.findall(r"<(?:script|link)[^>]+leaflet[^>]+>", s):
                self.assertIn("integrity=", tag, p.name)


class Cards(HTMLParser):
    """Collects, per index card, whether it has a <details class=older> and how many election links it shows."""
    def __init__(self):
        super().__init__()
        self.cards, self.cur, self.nation_at, self.eps_at, self.pos, self.groups = [], None, None, None, 0, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.pos += 1
        cls = (a.get("class") or "").split()
        if tag == "nav" and "nation" in cls:
            self.nation_at = self.pos
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
        elif tag == "a" and self.cur is not None and a.get("href", "").endswith(".html"):
            self.cur["links"] += 1


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


if __name__ == "__main__":
    unittest.main()
