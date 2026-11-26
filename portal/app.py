"""Request handling, with no sockets: handle(store, method, path, headers, body) -> (status, headers, body bytes).
server.py puts it behind http.server; the tests call it directly.

Rules: every page of a tenant needs a live session whose tenant is the one in the address, otherwise 404 (a wrong tenant
cannot tell whether the other one exists). Forms carry a CSRF token. A one-time link is spent by a POST, not a GET, so
mail scanners that open links do not use it up. Cookies are HttpOnly, SameSite=Lax, and Secure unless SECURE is False.
"""
import hmac
import html
import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, unquote

from . import store, tenants

SECURE = True  # set False for http://localhost
MAX_BODY = 4096
BASE_CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
HEADERS = [("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
           ("Cache-Control", "private, no-store"), ("Cross-Origin-Resource-Policy", "same-origin"), ("X-Robots-Tag", "noindex, nofollow")]

PAGE = """<!doctype html><html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{title}</title><style>
:root{{color-scheme:light dark;--paper:#fbfaf7;--ink:#1c1a17;--ink2:#5b5750;--line:#d9d4c9;--link:#1f4e9c;--btn:#1f4e9c}}
@media(prefers-color-scheme:dark){{:root{{--paper:#17181b;--ink:#f0eee8;--ink2:#aaa69c;--line:#34363b;--link:#8db4f5;--btn:#3c6fc4}}}}
body{{margin:0;background:var(--paper);color:var(--ink);font:1rem/1.55 "IBM Plex Sans",system-ui,sans-serif}}
main{{max-width:34rem;margin:0 auto;padding:48px 20px}}h1{{font:600 1.75rem/1.2 Literata,Georgia,serif;margin:0 0 24px}}
label{{display:block;margin:16px 0 4px;font-weight:600}}input{{width:100%;box-sizing:border-box;padding:10px 12px;font:inherit;color:inherit;
background:transparent;border:1px solid var(--ink2);border-radius:6px}}button{{margin-top:24px;padding:10px 20px;font:inherit;font-weight:600;color:#fff;
background:var(--btn);border:0;border-radius:6px;cursor:pointer}}button.quiet{{margin:0;color:var(--link);background:none;text-decoration:underline;padding:0}}
.err{{color:#b3261e;margin:0 0 16px}}ul{{list-style:none;padding:0;margin:0}}li{{padding:14px 0;border-top:1px solid var(--line)}}
li a{{color:var(--link);font-weight:600;font-size:1.0625rem}}li p{{margin:4px 0 0;color:var(--ink2)}}.bar{{display:flex;justify-content:space-between;
align-items:center;margin-bottom:24px;color:var(--ink2)}}:focus-visible{{outline:2px solid var(--link);outline-offset:2px}}
</style></head><body><main>{body}</main></body></html>"""


def _page(title, body, status=200, extra=()):
    h = [("Content-Type", "text/html; charset=utf-8"), ("Content-Security-Policy", BASE_CSP), *HEADERS, *extra]
    return status, h, PAGE.format(title=html.escape(title), body=body).encode()


def _redirect(to, status=303, extra=()):
    return status, [("Location", to), *HEADERS, *extra], b""


def _not_found():
    return _page("Δεν βρέθηκε", "<h1>Δεν βρέθηκε</h1>", 404)


def _cookie(name, value, max_age):
    return ("Set-Cookie", f"{name}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}" + ("; Secure" if SECURE else ""))


def _cookies(headers):
    c = SimpleCookie()
    try:
        c.load(headers.get("Cookie", ""))
    except Exception:  # a malformed cookie header is no session
        return {}
    return {k: v.value for k, v in c.items()}


def _form(body):
    return {k: v[0] for k, v in parse_qs(body[:MAX_BODY].decode("utf-8", "replace")).items()}


def _same(a, b):
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


def _login_form(error="", csrf=None):
    csrf = csrf or secrets.token_urlsafe(16)
    msg = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    body = (f'<h1>Σύνδεση</h1>{msg}<form method="post" action="/login"><input type="hidden" name="csrf" value="{csrf}">'
            '<label for="e">Email</label><input id="e" name="email" type="email" autocomplete="username" required autofocus>'
            '<label for="p">Κωδικός</label><input id="p" name="password" type="password" autocomplete="current-password" required>'
            '<button type="submit">Σύνδεση</button></form>')
    return _page("Σύνδεση", body, 200 if not error else 401, [_cookie("lcsrf", csrf, 900)])


def _home(session):
    slug = session["tenant"]
    items = "".join(f'<li><a href="/t/{slug}/f/{quote(e["file"])}">{html.escape(e["title"])}</a>'
                    + (f'<p>{html.escape(e["note"])}</p>' if e["note"] else "") + "</li>" for e in tenants.published(slug))
    items = items or "<li><p>Δεν υπάρχουν ακόμη διαθέσιμα αρχεία.</p></li>"
    out = (f'<div class="bar"><span>{html.escape(session["email"])}</span><form method="post" action="/logout">'
           f'<input type="hidden" name="csrf" value="{session["csrf"]}"><button class="quiet" type="submit">Αποσύνδεση</button></form></div>'
           f'<h1>{html.escape(tenants.display_name(slug))}</h1><ul>{items}</ul>')
    return _page(tenants.display_name(slug), out)


def handle(store_, method, path, headers, body=b""):
    cookies = _cookies(headers)
    session = store_.session(cookies.get("sid"))
    route = unquote(path.split("?", 1)[0])

    if method == "GET" and route == "/":
        return _redirect(f"/t/{session['tenant']}/", 302) if session else _redirect("/login", 302)
    if method == "GET" and route == "/login":
        return _login_form()
    if method == "POST" and route == "/login":
        f = _form(body)
        if not _same(f.get("csrf"), cookies.get("lcsrf")):
            return _login_form("Η φόρμα έληξε. Δοκιμάστε ξανά.")
        user = store_.login(f.get("email", ""), f.get("password", ""))
        if not user:
            return _login_form("Λάθος email ή κωδικός, ή ο λογαριασμός περιμένει λίγο μετά από πολλές προσπάθειες.")
        return _redirect("/", 303, [_cookie("sid", store_.start_session(user["id"]), store.SESSION_SECONDS), _cookie("lcsrf", "", 0)])
    if route.startswith("/magic/") and method in ("GET", "POST"):
        token = route[len("/magic/"):]
        if method == "GET":  # a scanner that only reads the page must not spend the link
            csrf = secrets.token_urlsafe(16)
            body_ = (f'<h1>Σύνδεση</h1><form method="post" action="/magic/{html.escape(quote(token))}"><input type="hidden" name="csrf" value="{csrf}">'
                     '<p>Πατήστε για να συνδεθείτε.</p><button type="submit">Σύνδεση</button></form>')
            return _page("Σύνδεση", body_, 200, [_cookie("lcsrf", csrf, 900)])
        if not _same(_form(body).get("csrf"), cookies.get("lcsrf")):
            return _not_found()
        user = store_.use_link(token)
        if not user:
            return _login_form("Ο σύνδεσμος έληξε ή έχει ήδη χρησιμοποιηθεί.")
        return _redirect("/", 303, [_cookie("sid", store_.start_session(user["id"]), store.SESSION_SECONDS), _cookie("lcsrf", "", 0)])
    if method == "POST" and route == "/logout":
        if session and _same(_form(body).get("csrf"), session["csrf"]):
            store_.end_session(cookies["sid"])
        return _redirect("/login", 303, [_cookie("sid", "", 0)])

    parts = route.split("/")  # ["", "t", slug, ...]
    if method == "GET" and len(parts) >= 3 and parts[1] == "t":
        slug = parts[2]
        if not session:
            return _redirect("/login", 302)
        if session["tenant"] != slug:
            return _not_found()  # same answer as for a tenant that does not exist
        if len(parts) <= 4 and parts[3:] in ([], [""]):
            return _home(session)
        if len(parts) >= 5 and parts[3] == "f":
            p = tenants.resolve(slug, "/".join(parts[4:]))
            if not p:
                return _not_found()
            ctype = tenants.TYPES[p.suffix.lower()]
            h = [("Content-Type", ctype), *HEADERS]
            if p.suffix.lower() == ".svg":
                h.append(("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src data:"))
            return 200, h, p.read_bytes()
    return _not_found()
