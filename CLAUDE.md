# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Greek election maps: preference votes (σταυροί) and party shares per electoral district and per polling station, built as static Leaflet HTML pages (data and code inline; Leaflet and fonts are files beside them in `out/`). User-facing text, labels and the README are in Greek; code and comments are in English.

## Commands

No build system, test suite or package config. Python 3.12, stdlib only except `xlrd` (needed by `stations_map.py` and `nikh_report.py` for the ministry venue `.xls`). Lint with `ruff check .` (no config; defaults).

On Windows run scripts as `python -I -X utf8 <script>`: `-X utf8` is required for Greek console output (`-I` ignores `PYTHONIOENCODING`), and the scripts re-add their own directory to `sys.path` because `-I` drops it.

```
python -I -X utf8 fetch.py 2023/may 45        # one constituency -> data/stavroi.sqlite (resumable)
python -I -X utf8 fetch.py 2023/may all       # all constituencies with seats (~22k stations, slow)
python -I -X utf8 build.py 2023/may 45        # -> out/2023-may_45.html
python -I -X utf8 build.py 2023/may all       # all, in parallel + out/index_2023-may.html (match coverage per constituency)
python -I -X utf8 build.py index              # rewrite out/index.html from out/maps.json only
python -I -X utf8 compare.py                  # -> out/compare.html (needs build.py <e> all for every election)
python -I -X utf8 og_image.py                 # -> out/og/*.png share pictures (needs Chrome; --force redraws all)
python -I -X utf8 -m unittest discover -s tests   # matching unit tests, coverage regression, structure of out/*.html (test_pages.py)
python -I -X utf8 tests/test_coverage.py --update # accept new coverage after an intended matching change
python -I -X utf8 stations_map.py 2023/may 31 131 0 <venues.xls> Πατρέων   # cand 0 = party share
python -I -X utf8 nikh_report.py <venues.xls>
```

Election keys: `2019`, `2023/may`, `2023/june`, `2024/euro`, all defined once in `config.ELECTIONS`. Output files replace `/` with `-` (`config.slug`: `2023-may_45.html`, `2019_45.html`).

## Architecture

**Pipeline:** `fetch.py` → SQLite (`data/stavroi.sqlite`, git-ignored, ~150 MB) → `build.py` / `stations_map.py` → `out/*.html`; `build.py` also writes `area_match`, which `compare.py` and `analysis/nikh_map.py` read for the nationwide pages.

**Modules** (no cycles: config ← matching ← web ← build ← compare/stations_map/nikh_report):
- **config.py**: paths, `ELECTIONS`, `source()` (results site per election), the SQLite `SCHEMA`, `PARTY_SHORT` (by party id; ids are stable across elections), `ELECTED`. New elections and parties go here.
- **matching.py**: name matching and `boundaries()` (ELSTAT files, loaded once per process via `functools.cache`). `match_areas()` returns `{(den, ekd): community code}` for one constituency.
- **geo.py**: stdlib geometry for build-time SVG (Douglas-Peucker, union outline by cancelling shared edges). `build.py` stores each constituency's silhouette in `maps.json` (`sil`); `compare.py` writes `out/greece_map.html` (first party per community) that the index embeds, so run `compare.py` before `build.py index`. `config.REGIONS` groups the index cards.
- **shared.js**: pure helpers every page inlines through `fill()` (`/*SHARED_JS*/`): search folding (`fold`, `key`, `hits`, `queryWords`), `binLabel` (one legend wording) and `mapOptions` (reduced motion). `theme.js` defaults to light whatever the system says; the toggle flips light and dark and only "dark" is remembered.
- **Security and share tags:** `web.secure(page, path)` injects a CSP `<meta>` (script/style allowed by SHA-256 of each inline block, computed on the finished page), a referrer policy, a favicon and, when `config.SITE_URL` is set, `canonical`, `og:url`, `og:image` and `twitter:image`; call it last on every page and pass the file the page is written to (a page outside `out/` gets no address tags). `web.meta()` writes description, Open Graph and twitter card. Leaflet is self-hosted in `out/vendor/leaflet-1.9.4/` (pinned downloads from cdnjs, loaded with SRI; the version is in the folder name so `vercel.json` caches it for a year: a new version goes to a new folder), so the only outside source is the OSM tiles. The site is served by Vercel (`.vercelignore` publishes only `index.html`, `vercel.json`, `out/`, `exports/`); `vercel.json` adds the headers a meta cannot set (`frame-ancestors`, nosniff, Permissions-Policy, COOP, CORP: same-origin except `out/og/`) and redirects `/` to `/out/index.html`. Both CSPs apply, so the header one only adds directives. HSTS comes from Vercel. `tests/test_pages.py` checks hashes, no `on*=` handlers, SRI, the share tags, the pictures and `vercel.json`.
- **Share pictures:** `og_image.py` draws `out/og/*.png` (1200x630) with headless Chrome: one per kind in `config.OG_IMAGES` and one per constituency map page (silhouette, name, election). `config.og_kind(file)` says which picture a page gets. Run it after `build.py` (it reads `out/maps.json`); `out/og/manifest.json` holds a hash of what each picture was drawn from, so a changed title, silhouette or look is redrawn, a missing or cut-short PNG is redrawn, orphans are deleted, and `--force` redraws all. If a picture fails the rest are kept and the exit code is 1.
- **CI** (`.github/workflows/ci.yml`): ruff (syntax and pyflakes rules only) and the unittest suite on every push and PR. Vercel still deploys every push to main whether CI passes or not.
- **backup.py**: `VACUUM INTO` snapshot of the DB (gzip) plus the ministry `.xls`, with a checksum per election and table in `manifest.json`; `backup.py verify <dir>` checks a restore. Output in `data/backup/` (git-ignored); store it off this machine.
- **web.py**: everything shared by pages: `fill()` (colour tokens written once as `light-dark()`, site CSS, theme script, fonts, header, footer), `render_page()`, and the index. `record()` adds entries to `out/maps.json` (atomic replace); `write_index()` rebuilds `out/index.html` from it, once per build. Not named `site.py`: that would shadow Python's own `site` module.

- **fetch.py** reads the Ministry of Interior results site (`/stat/{k}/…` static, `/dyn/{k}/…` results; `k`=`v` parliamentary, `e` European). `source(election)` maps an election key to (base URL, kind); Euro 2024 is served from `ekloges.ypes.gr/current`, the rest from `ekloges-prev.singularlogic.eu/{election}`. Station id = `ep * 10000 + seq`, so per-constituency queries use `tm_id BETWEEN ep*10000 AND ep*10000+9999`. Per-station preference votes (`tm_vc_*`) exist for 2019 and May 2023 only; June 2023 and Euro 2024 have party votes only. Party leaders' crosses exist only as constituency totals (`ep_total`).
- **build.py** matches each electoral district (Ε.Δ., `station.ekd_descr`) to an ELSTAT 2021 local community (`data/koinotites_2021.json`) inside its municipal unit (`data/dhm_enotites_2021.json`), by name or via a settlement (`data/oikismoi_2021.csv`). The ministry uses genitive forms and ELSTAT nominative, so matching compares word stems (`norm` → `stems`, with `phonetic` and `one_edit` fallbacks in `find`). Unmatched districts and special/absentee stations are left off the map; coverage % is reported.
  - **Party mode:** when a constituency has no per-station `cand_votes`, `main()` switches to party mode. It creates one pseudo-candidate `"{pid}:0"` per party, and the template divides by valid votes instead of party votes (`D.mode === "party"`).
  - **Rendering:** `render_page()` inlines `common.css`/`common.js` into the `/*COMMON_CSS*/`/`/*COMMON_JS*/` placeholders, then the JSON payload into `/*DATA*/null`. Data, CSS and JS are inline; the only files a page loads are `out/vendor/leaflet-1.9.4/` and `out/fonts/` (a page written outside `out/` loads Leaflet from cdnjs instead, so it still works on its own).
  - **Parallel build:** `build_all` runs one constituency per process (`ProcessPoolExecutor`). Workers only read the DB and write their own page; they return their maps.json entry and area matches, and the parent writes both (`save()`), so there is one writer. Two separate build processes at once can still race on `out/maps.json`.
  - **Index:** `out/index.html` is generated (`web.write_index()`), including the per-party artifact links and the NIKH section. Hand edits to it are lost.
- **stations_map.py** places polling stations at venues from the ministry `.xls`. It geocodes with Nominatim, at most 1 request/s with a generic User-Agent, and caches results in `data/venues_geo.json`. A geocode is kept only if it falls inside the station's ELSTAT municipal unit. `XLS_EP` aliases constituency names that differ between the results site and the spreadsheet (Β1/Β2/Β3 Αθηνών).
- **nikh_report.py** compares NIKH (party 131) May vs June 2023 in the 9 constituencies where it elected an MP.
- **compare.py**, **analysis/nikh_map.py**: nationwide pages from `build.communities()` (area_match joined with stations and party votes, one row per ELSTAT community).
- **analysis/**: the ΝΙΚΗ statistics scripts. `analysis/CONTEXT.md` is the catalog (script → inputs → outputs → section of `analysis/NIKH.md`, and where each shared fact lives, e.g. `config.NIKH`).
- **Templates** (`template.html`, `stations_template.html`) read everything from the injected `D` object. Deep links: `#party=<pid>&cand=<cid>`.
  - **Initial fit:** `fitOnceSized()` in `common.js` delays the first `fitBounds` until the container has a real size. Pages opened in hidden tabs/panes lay out at 0×0 and would otherwise fit to zoom 0.

## Data notes

- Results on the site are unofficial; this is stated on pages and in the README.
- Use only public aggregate results and public venue addresses. No voter lists or personal data.
- `out/` and `exports/` are committed generated artifacts; `data/*.json|csv` are committed ELSTAT boundaries plus the geocode cache.
