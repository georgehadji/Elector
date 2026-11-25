"""Share pictures of the site: out/og/<kind>.png, 1200x630, one per kind in config.OG_IMAGES (see config.og_kind).

Usage: python -I -X utf8 og_image.py [--force]
Draws each picture as a small HTML page (the site mark, title and line, in the site's own font from out/fonts/) and
photographs it with headless Chrome, so nothing is installed. A picture that exists is kept unless --force:
Chrome does not give identical bytes twice, and an unchanged file keeps the git history quiet.
Edit config.OG_IMAGES (wording) or this file (look), run with --force, rebuild the pages.
"""
import html
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
from config import HERE, OG_IMAGES, OUT  # noqa: E402
from web import MARK  # noqa: E402

CHROME = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"]
CSS = """body{margin:0;width:1200px;height:630px;box-sizing:border-box;border-left:16px solid #1f4e9c;background:#fbfaf6;color:#1d1d1b;
font:400 38px/1.35 "IBM Plex Sans",sans-serif;display:flex;flex-direction:column;justify-content:flex-end;padding:0 96px 92px 80px}
.mark{position:absolute;left:80px;top:76px;width:128px;height:128px;color:#1f4e9c}
.mark rect,.mark path{fill:none;stroke:currentColor;stroke-linecap:round}.mark rect{stroke-width:2.4}.mark path{stroke-width:3.2}
h1{margin:0 0 18px;font-size:104px;font-weight:600;line-height:1.05}p{margin:0;color:#46453f}"""


def page(title, line):
    fonts = (HERE / "fonts.css").read_text(encoding="utf-8").replace("url(fonts/", f"url({(OUT / 'fonts').as_uri()}/")
    return (f'<!doctype html><meta charset="utf-8"><style>{fonts}{CSS}</style>{MARK}'
            f"<h1>{html.escape(title)}</h1><p>{html.escape(line)}</p>")


def main(force=False):
    chrome = next((c for c in CHROME if Path(c).exists()), None) or shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        raise SystemExit("Chrome λείπει: δεν φτιάχτηκε καμία εικόνα")
    (OUT / "og").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        for kind, (title, line) in OG_IMAGES.items():
            png = OUT / "og" / f"{kind}.png"
            if png.exists() and not force:
                continue
            src = Path(t) / f"{kind}.html"
            src.write_text(page(title, line), encoding="utf-8")
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                            "--window-size=1200,630", "--virtual-time-budget=3000", f"--screenshot={png}", src.as_uri()],
                           check=True, capture_output=True)
            print(f"wrote {png} ({png.stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main("--force" in sys.argv)
