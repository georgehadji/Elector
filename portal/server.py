"""http.server around app.handle. For one machine or behind a reverse proxy that terminates TLS (then keep cookies Secure).
Without TLS in front, use --insecure for http://localhost only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import app, store


def make_handler(st):
    class H(BaseHTTPRequestHandler):
        server_version = "portal"
        sys_version = ""

        def _go(self):
            n = min(int(self.headers.get("Content-Length") or 0), app.MAX_BODY)
            status, headers, body = app.handle(st, self.command, self.path, dict(self.headers), self.rfile.read(n) if n else b"")
            self.send_response(status)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = do_POST = _go

        def log_message(self, fmt, *args):  # no query strings or tokens in logs
            print(f"{self.command} {self.path.split('?')[0].split('/magic/')[0]} {args[1] if len(args) > 1 else ''}")

    return H


def serve(host="127.0.0.1", port=8080, insecure=False, db=store.DB):
    app.SECURE = not insecure
    srv = ThreadingHTTPServer((host, port), make_handler(store.Store(db)))
    print(f"portal on http://{host}:{port}" + ("  (cookies not Secure: localhost only)" if insecure else ""))
    srv.serve_forever()
