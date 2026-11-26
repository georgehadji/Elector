"""Portal: one tenant never reaches another's files; login, links, lockout and sessions behave. No network, temp folders only."""
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from portal import app, security, store, tenants


def _tenant(root, slug, files, publish):
    d = root / slug
    d.mkdir()
    for name, data in files.items():
        (d / name).write_bytes(data)
    (d / "client.json").write_text(json.dumps({"name": slug.upper(), "publish": publish}), encoding="utf-8")


def _csrf(headers):
    return dict(headers)["Set-Cookie"].split(";")[0].split("=", 1)[1]


class PortalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["STAVROI_CLIENTS"] = str(self.root)
        app.SECURE = True
        _tenant(self.root, "alpha", {"report.pdf": b"%PDF alpha", "notes.txt": b"private alpha", "page.html": b"<p>alpha</p>"},
                [{"title": "Αναφορά", "file": "report.pdf"}, {"title": "Σελίδα", "file": "page.html", "note": "x"}])
        _tenant(self.root, "beta", {"report.pdf": b"%PDF beta"}, [{"title": "R", "file": "report.pdf"}])
        self.st = store.Store(":memory:")
        for s in ("alpha", "beta"):
            self.st.add_tenant(s, s.upper())
            self.st.add_user(f"u@{s}.gr", s, "correct horse battery")

    def tearDown(self):
        os.environ.pop("STAVROI_CLIENTS", None)
        self.tmp.cleanup()

    def login(self, tenant):
        _, h, _ = app.handle(self.st, "GET", "/login", {})
        csrf = _csrf(h)
        body = f"csrf={csrf}&email=u%40{tenant}.gr&password=correct+horse+battery".encode()
        status, h, _ = app.handle(self.st, "POST", "/login", {"Cookie": f"lcsrf={csrf}"}, body)
        self.assertEqual(status, 303)
        return next(v.split(";")[0] for k, v in h if k == "Set-Cookie" and v.startswith("sid=") and "Max-Age=0" not in v)

    def get(self, path, cookie=None):
        return app.handle(self.st, "GET", path, {"Cookie": cookie} if cookie else {})

    def test_published_file_served_to_own_tenant_only(self):
        a, b = self.login("alpha"), self.login("beta")
        s, _, body = self.get("/t/alpha/f/report.pdf", a)
        self.assertEqual((s, body), (200, b"%PDF alpha"))
        self.assertEqual(self.get("/t/alpha/f/report.pdf", b)[0], 404)  # other tenant: same answer as for a missing one
        self.assertEqual(self.get("/t/beta/f/report.pdf", a)[0], 404)
        self.assertEqual(self.get("/t/alpha/f/report.pdf")[0], 302)  # no session -> login

    def test_unpublished_and_traversal_refused(self):
        a = self.login("alpha")
        for p in ("/t/alpha/f/notes.txt", "/t/alpha/f/client.json", "/t/alpha/f/../beta/report.pdf", "/t/alpha/f/..%2Fbeta%2Freport.pdf",
                  "/t/alpha/f/%2e%2e/beta/report.pdf", "/t/alpha/f/", "/t/nope/"):
            self.assertEqual(self.get(p, a)[0], 404, p)

    def test_manifest_cannot_point_outside_folder(self):
        (self.root / "secret.txt").write_text("outside")
        (self.root / "alpha" / "client.json").write_text(json.dumps({"publish": [
            {"title": "x", "file": "../secret.txt"}, {"title": "y", "file": "/etc/passwd"}, {"title": "z", "file": "..\\secret.txt"}]}))
        self.assertEqual(tenants.published("alpha"), [])
        self.assertIsNone(tenants.resolve("alpha", "../secret.txt"))

    def test_dashboard_lists_only_own_files(self):
        s, _, body = self.get("/t/alpha/", self.login("alpha"))
        self.assertEqual(s, 200)
        self.assertIn("Αναφορά", body.decode())
        self.assertNotIn("/t/beta", body.decode())

    def test_wrong_password_and_unknown_user_look_the_same(self):
        _, h, _ = app.handle(self.st, "GET", "/login", {})
        csrf = _csrf(h)
        r = []
        for email in ("u%40alpha.gr", "nobody%40x.gr"):
            s, _, b = app.handle(self.st, "POST", "/login", {"Cookie": f"lcsrf={csrf}"}, f"csrf={csrf}&email={email}&password=wrong".encode())
            r.append((s, re.sub(rb'value="[^"]*"', b"", b)))
        self.assertEqual(r[0][0], 401)
        self.assertEqual(r[0], r[1])

    def test_login_needs_csrf(self):
        s, _, b = app.handle(self.st, "POST", "/login", {"Cookie": "lcsrf=abc"}, b"csrf=zzz&email=u%40alpha.gr&password=correct+horse+battery")
        self.assertEqual(s, 401)
        self.assertNotIn("sid", b.decode())

    def test_lockout_after_failures_even_with_right_password(self):
        for _ in range(store.LOCK_AFTER):
            self.assertIsNone(self.st.login("u@alpha.gr", "bad"))
        self.assertIsNone(self.st.login("u@alpha.gr", "correct horse battery"))
        self.assertIsNotNone(self.st.login("u@alpha.gr", "correct horse battery", now=time.time() + store.LOCK_WINDOW + 5))

    def test_magic_link_is_single_use_and_scanner_safe(self):
        t = self.st.make_link("u@alpha.gr")
        s, h, _ = self.get(f"/magic/{t}")  # GET shows a button and spends nothing
        self.assertEqual(s, 200)
        csrf = _csrf(h)
        first = app.handle(self.st, "POST", f"/magic/{t}", {"Cookie": f"lcsrf={csrf}"}, f"csrf={csrf}".encode())[0]
        again = app.handle(self.st, "POST", f"/magic/{t}", {"Cookie": f"lcsrf={csrf}"}, f"csrf={csrf}".encode())[0]
        self.assertEqual((first, again), (303, 401))

    def test_expired_link_and_session(self):
        t = self.st.make_link("u@alpha.gr", seconds=10, now=1000)
        self.assertIsNone(self.st.use_link(t, now=2000))
        s = self.st.start_session(self.st.user("u@alpha.gr")["id"], now=1000)
        self.assertIsNone(self.st.session(s, now=1000 + store.SESSION_SECONDS + 1))
        self.assertIsNotNone(self.st.session(s, now=1001))

    def test_disabling_user_or_tenant_ends_access(self):
        c = self.login("alpha")
        self.st.set_tenant_active("alpha", False)
        self.assertEqual(self.get("/t/alpha/", c)[0], 302)
        self.st.set_tenant_active("alpha", True)
        self.st.set_active("u@alpha.gr", False)
        self.assertEqual(self.get("/t/alpha/", c)[0], 302)

    def test_logout_needs_csrf_and_kills_session(self):
        c = self.login("alpha")
        sid = c.split("=", 1)[1]
        csrf = self.st.session(sid)["csrf"]
        app.handle(self.st, "POST", "/logout", {"Cookie": c}, b"csrf=wrong")
        self.assertIsNotNone(self.st.session(sid))
        app.handle(self.st, "POST", "/logout", {"Cookie": c}, f"csrf={csrf}".encode())
        self.assertIsNone(self.st.session(sid))

    def test_cookie_flags_and_headers(self):
        d = dict(app.handle(self.st, "GET", "/login", {})[1])
        for flag in ("HttpOnly", "SameSite=Lax", "Secure"):
            self.assertIn(flag, d["Set-Cookie"])
        self.assertEqual(d["X-Frame-Options"], "DENY")
        self.assertIn("no-store", d["Cache-Control"])

    def test_passwords_hashed_and_weak_refused(self):
        row = self.st.user("u@alpha.gr")
        self.assertTrue(row["pw"].startswith("scrypt$"))
        self.assertNotIn("correct horse", row["pw"])
        self.assertTrue(security.check_password("correct horse battery", row["pw"]))
        self.assertFalse(security.check_password("x", row["pw"]))
        with self.assertRaises(ValueError):
            self.st.set_password("u@alpha.gr", "short")

    def test_svg_served_with_locked_down_csp(self):
        (self.root / "alpha" / "m.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        (self.root / "alpha" / "client.json").write_text(json.dumps({"publish": [{"title": "m", "file": "m.svg"}]}))
        _, h, _ = self.get("/t/alpha/f/m.svg", self.login("alpha"))
        self.assertIn("default-src 'none'", dict(h)["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
