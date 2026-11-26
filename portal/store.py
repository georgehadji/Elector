"""SQLite store of tenants, users, sessions, one-time links and login attempts. File: data/portal.sqlite (git-ignored)."""
import sqlite3
import time
from pathlib import Path

from . import security

DB = Path(__file__).resolve().parent.parent / "data" / "portal.sqlite"
SESSION_SECONDS = 12 * 3600
LINK_SECONDS = 24 * 3600
LOCK_AFTER, LOCK_WINDOW = 5, 15 * 60  # failed logins in the window before the account waits

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenant (slug TEXT PRIMARY KEY, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS user (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, pw TEXT, tenant TEXT NOT NULL REFERENCES tenant(slug),
  active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS session (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES user(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS link (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES user(id), expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempt (email TEXT NOT NULL, at REAL NOT NULL);
"""

_DUMMY = security.hash_password("dummy-password-for-timing")


def _norm(email):
    return email.strip().lower()


class Store:
    def __init__(self, path=DB):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    # tenants and users (admin CLI)
    def add_tenant(self, slug, name):
        self.db.execute("INSERT INTO tenant(slug, name) VALUES (?, ?) ON CONFLICT(slug) DO UPDATE SET name=excluded.name", (slug, name))
        self.db.commit()

    def set_tenant_active(self, slug, active):
        self.db.execute("UPDATE tenant SET active=? WHERE slug=?", (int(active), slug))
        self.db.commit()

    def add_user(self, email, tenant, password=None):
        if not self.db.execute("SELECT 1 FROM tenant WHERE slug=?", (tenant,)).fetchone():
            raise ValueError(f"άγνωστος πελάτης: {tenant}")
        if password:
            why = security.weak_password(password)
            if why:
                raise ValueError(why)
        self.db.execute("INSERT INTO user(email, pw, tenant) VALUES (?, ?, ?)",
                        (_norm(email), security.hash_password(password) if password else None, tenant))
        self.db.commit()

    def set_password(self, email, password):
        why = security.weak_password(password)
        if why:
            raise ValueError(why)
        self.db.execute("UPDATE user SET pw=? WHERE email=?", (security.hash_password(password), _norm(email)))
        self.db.commit()

    def set_active(self, email, active):
        self.db.execute("UPDATE user SET active=? WHERE email=?", (int(active), _norm(email)))
        if not active:  # a disabled user loses the sessions they hold
            self.db.execute("DELETE FROM session WHERE user_id IN (SELECT id FROM user WHERE email=?)", (_norm(email),))
        self.db.commit()

    def user(self, email):
        return self.db.execute("SELECT * FROM user WHERE email=?", (_norm(email),)).fetchone()

    def users(self):
        return self.db.execute("SELECT email, tenant, active, pw IS NOT NULL AS has_pw FROM user ORDER BY tenant, email").fetchall()

    def tenants(self):
        return self.db.execute("SELECT * FROM tenant ORDER BY slug").fetchall()

    # one-time links
    def make_link(self, email, seconds=LINK_SECONDS, now=None):
        u = self.user(email)
        if not u:
            raise ValueError(f"άγνωστος χρήστης: {email}")
        token = security.new_token()
        self.db.execute("INSERT INTO link VALUES (?, ?, ?)", (security.token_hash(token), u["id"], (now or time.time()) + seconds))
        self.db.commit()
        return token

    def use_link(self, token, now=None):
        """User row for a valid link; the link is spent either way."""
        h = security.token_hash(token)
        row = self.db.execute("SELECT * FROM link WHERE token=?", (h,)).fetchone()
        self.db.execute("DELETE FROM link WHERE token=?", (h,))
        self.db.commit()
        if not row or row["expires"] < (now or time.time()):
            return None
        return self.db.execute("SELECT * FROM user WHERE id=? AND active=1", (row["user_id"],)).fetchone()

    # login attempts
    def locked(self, email, now=None):
        n = self.db.execute("SELECT COUNT(*) FROM attempt WHERE email=? AND at>?", (_norm(email), (now or time.time()) - LOCK_WINDOW)).fetchone()[0]
        return n >= LOCK_AFTER

    def _failed(self, email, now):
        self.db.execute("INSERT INTO attempt VALUES (?, ?)", (_norm(email), now))
        self.db.execute("DELETE FROM attempt WHERE at<?", (now - LOCK_WINDOW,))
        self.db.commit()

    def login(self, email, password, now=None):
        """User row if the password is right and the account is neither disabled nor waiting; else None.
        The same work is done for an unknown email, so the answer does not reveal which emails exist."""
        now = now or time.time()
        if self.locked(email, now):
            return None
        u = self.user(email)
        ok = security.check_password(password, u["pw"] if u and u["pw"] else _DUMMY)
        if u and u["pw"] and u["active"] and ok:
            self.db.execute("DELETE FROM attempt WHERE email=?", (_norm(email),))
            self.db.commit()
            return u
        self._failed(email, now)
        return None

    # sessions
    def start_session(self, user_id, now=None):
        token, csrf = security.new_token(), security.new_token()
        self.db.execute("INSERT INTO session VALUES (?, ?, ?, ?)", (security.token_hash(token), user_id, csrf, (now or time.time()) + SESSION_SECONDS))
        self.db.commit()
        return token

    def session(self, token, now=None):
        """{id, email, tenant, csrf} for a live session of an active user in an active tenant, else None."""
        if not token:
            return None
        row = self.db.execute(
            "SELECT u.id, u.email, u.tenant, s.csrf, s.expires FROM session s JOIN user u ON u.id=s.user_id JOIN tenant t ON t.slug=u.tenant "
            "WHERE s.token=? AND u.active=1 AND t.active=1", (security.token_hash(token),)).fetchone()
        if not row or row["expires"] < (now or time.time()):
            return None
        return dict(row)

    def end_session(self, token):
        self.db.execute("DELETE FROM session WHERE token=?", (security.token_hash(token),))
        self.db.commit()
