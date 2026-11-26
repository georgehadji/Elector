"""A tenant's folder and manifest. `analysis/clients/<slug>/client.json` (local, git-ignored) says what the client sees:

  {"name": "ΝΙΚΗ", "party": 131, "rival": 108, "pair": {"base": "2023/june", "target": "2024/euro"},
   "modules": ["base", "venues", "targets"],
   "publish": [{"title": "Αναφορά", "file": "report.pdf", "note": "Η αναφορά για το κόμμα"}]}

`publish` is an allowlist: only the files named there can be fetched, by that exact name. Everything else in the folder
(working notes, inputs, other outputs) stays unreachable. `modules` and the rest are read by the analysis runner, not by the portal.
"""
import json
import os
import re
from pathlib import Path

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
TYPES = {".html": "text/html; charset=utf-8", ".pdf": "application/pdf", ".svg": "image/svg+xml", ".png": "image/png",
         ".jpg": "image/jpeg", ".csv": "text/csv; charset=utf-8", ".txt": "text/plain; charset=utf-8"}  # what may be published


def root():
    return Path(os.environ.get("STAVROI_CLIENTS") or Path(__file__).resolve().parent.parent / "analysis" / "clients")


def folder(slug):
    """The tenant's folder, or None for a slug that is not well formed or has no folder."""
    if not SLUG.match(slug or ""):
        return None
    p = root() / slug
    return p if p.is_dir() else None


def manifest(slug):
    f = folder(slug)
    if not f or not (f / "client.json").is_file():
        return None
    try:
        m = json.loads((f / "client.json").read_text(encoding="utf-8"))
    except ValueError:
        return None
    return m if isinstance(m, dict) else None


def _inside(f, rel):
    """File f/rel if it exists inside f, has a published type and is not reached through a link; else None."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or ".." in Path(rel.replace("\\", "/")).parts:
        return None
    p = (f / rel)
    if p.suffix.lower() not in TYPES or p.is_symlink() or not p.is_file():
        return None
    return p if p.resolve().is_relative_to(f.resolve()) else None


def published(slug):
    """[{title, file, note}] of the manifest's `publish` entries whose file exists; [] when there is none."""
    f, m = folder(slug), manifest(slug)
    if not f or not m:
        return []
    out = []
    for e in m.get("publish", []):
        if isinstance(e, dict) and _inside(f, e.get("file")):
            out.append({"title": str(e.get("title") or e["file"]), "file": e["file"], "note": str(e.get("note") or "")})
    return out


def resolve(slug, rel):
    """Path of a published file of this tenant, or None. A file that is not listed in `publish` is never returned."""
    f = folder(slug)
    if not f or rel not in {e["file"] for e in published(slug)}:
        return None
    return _inside(f, rel)


def display_name(slug):
    m = manifest(slug) or {}
    return str(m.get("name") or slug)
