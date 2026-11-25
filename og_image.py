"""Share pictures of the site: out/og/<kind>.png, 1200x630.

Usage: python -I -X utf8 og_image.py [--force]
One picture per kind in config.OG_IMAGES, and one per constituency map page (config.og_kind gives the name): the
constituency's silhouette from out/maps.json, its name and the election. Run it after build.py, which writes maps.json.
Each picture is a small HTML page (site mark, title, line, in the site's own font from out/fonts/) photographed with
headless Chrome, so nothing is installed. out/og/manifest.json remembers a hash of what each picture was drawn from:
a picture is redrawn when its title, line, silhouette or the look below changed, or when the file is missing or damaged
(--force redraws all). Pictures of pages that no longer exist are deleted. A picture that fails is reported at the end
and the exit code is 1; the others are kept.
Edit config.OG_IMAGES (wording) or this file (look), run it, rebuild the pages.
"""
import hashlib
import html
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
from config import ELECTIONS, HERE, OG_IMAGES, OUT, og_kind  # noqa: E402
from web import MARK  # noqa: E402

CHROME = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"]
CSS = """body{margin:0;width:1200px;height:630px;box-sizing:border-box;border-left:16px solid #1f4e9c;background:#fbfaf6;color:#1d1d1b;
font:400 38px/1.35 "IBM Plex Sans",sans-serif;display:flex;flex-direction:column;justify-content:flex-end;padding:0 96px 92px 80px}
.mark{position:absolute;left:80px;top:76px;width:128px;height:128px;color:#1f4e9c}
.mark rect,.mark path{fill:none;stroke:currentColor;stroke-linecap:round}.mark rect{stroke-width:2.4}.mark path{stroke-width:3.2}
h1{margin:0 0 18px;font-size:104px;font-weight:600;line-height:1.05}p{margin:0;color:#46453f}
.area h1{font-size:68px;max-width:660px}.area p{max-width:660px}.area .mark{width:96px;height:96px;top:64px}
.sil{position:absolute;right:96px;top:70px;width:330px;height:470px;color:#1f4e9c}
.sil path{fill:currentColor;fill-opacity:.22;stroke:currentColor;stroke-width:1;stroke-linejoin:round}"""
MANIFEST = OUT / "og" / "manifest.json"
PNG_END = b"IEND\xaeB`\x82"  # last bytes of a complete PNG: a picture cut short by a killed Chrome lacks them


def page(title, line, sil=""):
    fonts = (HERE / "fonts.css").read_text(encoding="utf-8").replace("url(fonts/", f"url({(OUT / 'fonts').as_uri()}/")
    return (f'<!doctype html><meta charset="utf-8"><style>{fonts}{CSS}</style><body class="{"area" if sil else ""}">{MARK}{sil}'
            f"<h1>{html.escape(title)}</h1><p>{html.escape(line)}</p>")


def jobs():
    """{kind: (title, line, silhouette)} of every picture."""
    out = {kind: (title, line, "") for kind, (title, line) in OG_IMAGES.items()}
    maps = json.loads((OUT / "maps.json").read_text(encoding="utf-8"))
    for name, m in maps.items():
        if og_kind(name) == name[:-5]:  # a constituency map page has a picture of its own
            out[name[:-5]] = (m["ep_name"], ELECTIONS[m["election"]][1], m.get("sil", ""))
    return out


def stamp(job):
    """What a picture is drawn from (not the font path, which differs per machine)."""
    return hashlib.sha256(json.dumps([job, CSS], ensure_ascii=False).encode()).hexdigest()[:16]


def valid(png):
    if not png.is_file():
        return False
    data = png.read_bytes()
    return data[:8] == b"\x89PNG\r\n\x1a\n" and data[16:24] == (1200).to_bytes(4, "big") + (630).to_bytes(4, "big") and data.endswith(PNG_END)


def main(force=False):
    chrome = next((c for c in CHROME if Path(c).exists()), None) or shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        raise SystemExit("Chrome λείπει: δεν φτιάχτηκε καμία εικόνα")
    (OUT / "og").mkdir(exist_ok=True)
    work = jobs()
    if MANIFEST.exists():
        known = json.loads(MANIFEST.read_text(encoding="utf-8"))
    else:  # first run with a manifest: the pictures already there were drawn from today's inputs
        known = {k: stamp(j) for k, j in work.items() if valid(OUT / "og" / f"{k}.png")}
    todo = [k for k, j in work.items() if force or known.get(k) != stamp(j) or not valid(OUT / "og" / f"{k}.png")]
    done = {k: known[k] for k in work if k in known and k not in todo}
    failed = []
    with tempfile.TemporaryDirectory() as t:
        def shoot(kind):
            png, src, profile = OUT / "og" / f"{kind}.png", Path(t) / f"{kind}.html", Path(t) / f"profile-{kind}"
            src.write_text(page(*work[kind]), encoding="utf-8")
            try:
                subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                                "--window-size=1200,630", "--virtual-time-budget=3000", f"--user-data-dir={profile}",
                                f"--screenshot={png}", src.as_uri()], check=True, capture_output=True, timeout=90)
            except (subprocess.SubprocessError, OSError) as e:
                print(f"FAILED {kind}: {e}")
            finally:
                shutil.rmtree(profile, ignore_errors=True)
            if not valid(png):
                png.unlink(missing_ok=True)  # never leave a damaged picture to be published
                return kind, False
            print(f"wrote {png} ({png.stat().st_size / 1e3:.0f} KB)")
            return kind, True
        with ThreadPoolExecutor(4) as pool:  # one Chrome per picture, four at a time
            for kind, ok in pool.map(shoot, todo):
                if ok:
                    done[kind] = stamp(work[kind])
                else:
                    failed.append(kind)
    for png in (OUT / "og").glob("*.png"):
        if png.stem not in work:
            png.unlink()
            print(f"removed {png.name}: no such page any more")
    MANIFEST.write_text(json.dumps(done, indent=1, sort_keys=True), encoding="utf-8")
    print(f"{len(todo) - len(failed)} pictures made, {len(work) - len(todo)} kept, {len(failed)} failed")
    if failed:
        raise SystemExit(f"Απέτυχαν: {', '.join(failed)}")


if __name__ == "__main__":
    main("--force" in sys.argv)
