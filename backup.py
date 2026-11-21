"""Back up data/stavroi.sqlite and the ministry venue spreadsheets, with a checksum per election and table.

Usage: python backup.py                  -> data/backup/<date>/ (snapshot .gz, .xls copies, manifest.json, SHA256SUMS)
       python backup.py verify <dir>     -> unpack the snapshot and check every checksum in its manifest

The ministry sites for past elections may go offline, so the DB cannot always be rebuilt with fetch.py.
Upload a finished backup off this machine, e.g. as a release asset of the private repo:
  gh release create data-<date> data/backup/<date>/* --title "Data <date>" --notes "python backup.py verify"
"""
import datetime
import gzip
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
from config import DB, HERE  # noqa: E402

XLS = HERE / "analysis" / "venues_xls"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def checksums(db):
    """{election: {table: [rows, sha256 of the rows in a fixed order]}}, so a restore shows which election changed."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = {}
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        if "election" not in cols:
            continue
        order = ",".join(str(i + 1) for i in range(len(cols)))
        for (election,) in con.execute(f"SELECT DISTINCT election FROM {table} ORDER BY 1").fetchall():
            h, n = hashlib.sha256(), 0
            for row in con.execute(f"SELECT * FROM {table} WHERE election=? ORDER BY {order}", (election,)):
                h.update(repr(row).encode())
                n += 1
            out.setdefault(election, {})[table] = [n, h.hexdigest()]
    con.close()
    return out


def backup(dest):
    dest.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "stavroi.sqlite"
        con = sqlite3.connect(DB)
        con.execute("VACUUM INTO ?", (str(snap),))  # consistent copy even while fetch.py writes
        con.close()
        sums = checksums(snap)
        with open(snap, "rb") as f, gzip.open(dest / "stavroi.sqlite.gz", "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g, 1 << 20)
        raw = sha256(snap)
    for x in sorted(XLS.glob("*.xls*")):
        shutil.copy2(x, dest / x.name)
    files = {p.name: sha256(p) for p in sorted(dest.iterdir())}
    manifest = {"created": datetime.datetime.now().isoformat(timespec="seconds"), "sqlite_sha256": raw,
                "files": files, "elections": sums}
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (dest / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in files.items()), encoding="utf-8")
    return manifest


def verify(src):
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    bad = [n for n, h in manifest["files"].items() if sha256(src / n) != h]
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "stavroi.sqlite"
        with gzip.open(src / "stavroi.sqlite.gz", "rb") as g, open(snap, "wb") as f:
            shutil.copyfileobj(g, f, 1 << 20)
        if sha256(snap) != manifest["sqlite_sha256"]:
            bad.append("stavroi.sqlite (unpacked)")
        if checksums(snap) != manifest["elections"]:
            bad.append("per-election checksums")
    return bad


if __name__ == "__main__":
    if sys.argv[1:2] == ["verify"]:
        bad = verify(Path(sys.argv[2]))
        print("OK" if not bad else "MISMATCH: " + ", ".join(bad))
        sys.exit(1 if bad else 0)
    dest = HERE / "data" / "backup" / datetime.date.today().isoformat()
    m = backup(dest)
    for e, tables in m["elections"].items():
        print(e, " ".join(f"{t}={n}" for t, (n, _) in tables.items()))
    print(f"{dest}: " + ", ".join(f"{n} {(dest / n).stat().st_size / 1e6:.1f} MB" for n in m["files"]))
