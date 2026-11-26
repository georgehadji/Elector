"""Admin and server commands:  python -X utf8 -m portal <command>

  tenant <slug> "<name>"        add or rename a tenant (the folder analysis/clients/<slug>/ holds its files)
  user <email> <slug>           add a user to a tenant (then: link <email> or password <email>)
  password <email>              set a password (asked twice, not echoed)
  link <email> [hours]          print a one-time sign-in link (default 24 h)
  disable|enable <email>        block or restore a user (disabling ends their sessions)
  off|on <slug>                 block or restore a whole tenant
  list                          tenants, users, and what each tenant publishes
  serve [--port=8080] [--host=127.0.0.1] [--insecure]
Base address of links: PORTAL_URL (default http://127.0.0.1:8080).
"""
import getpass
import os
import sys

from . import server, store, tenants


def main(argv):
    if len(argv) < 2 or argv[1] in ("help", "-h", "--help"):
        print(__doc__)
        return 0
    cmd, a = argv[1], argv[2:]
    flags = {x.split("=")[0]: (x.split("=", 1)[1] if "=" in x else True) for x in a if x.startswith("--")}
    a = [x for x in a if not x.startswith("--")]
    if cmd == "serve":
        server.serve(flags.get("--host", "127.0.0.1"), int(flags.get("--port", 8080)), bool(flags.get("--insecure")))
        return 0
    st = store.Store()
    try:
        if cmd == "tenant":
            st.add_tenant(a[0], a[1])
            print(f"{a[0]}: ok" + ("" if tenants.folder(a[0]) else f"  (no folder yet: {tenants.root() / a[0]})"))
        elif cmd == "user":
            st.add_user(a[0], a[1])
            print("ok")
        elif cmd == "password":
            p = getpass.getpass("Κωδικός: ")
            if p != getpass.getpass("Ξανά: "):
                raise ValueError("οι κωδικοί διαφέρουν")
            st.set_password(a[0], p)
            print("ok")
        elif cmd == "link":
            t = st.make_link(a[0], int(float(a[1]) * 3600) if len(a) > 1 else store.LINK_SECONDS)
            print(os.environ.get("PORTAL_URL", "http://127.0.0.1:8080") + "/magic/" + t)
        elif cmd in ("disable", "enable"):
            st.set_active(a[0], cmd == "enable")
            print("ok")
        elif cmd in ("off", "on"):
            st.set_tenant_active(a[0], cmd == "on")
            print("ok")
        elif cmd == "list":
            for t in st.tenants():
                print(f"{t['slug']}  {t['name']}  {'on' if t['active'] else 'OFF'}  files: {[e['file'] for e in tenants.published(t['slug'])]}")
            for u in st.users():
                print(f"  {u['email']}  {u['tenant']}  {'on' if u['active'] else 'OFF'}  {'password' if u['has_pw'] else 'link only'}")
        else:
            print(f"άγνωστη εντολή: {cmd}\n{__doc__}")
            return 2
    except (ValueError, IndexError) as e:
        print(f"σφάλμα: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
