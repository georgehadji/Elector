# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Greek election maps: preference votes (σταυροί) and party shares per electoral district and per polling station, built as self-contained Leaflet HTML pages. User-facing text, labels and the README are in Greek; code and comments are in English.

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
python -I -X utf8 -m unittest discover -s tests   # matching unit tests + coverage regression
python -I -X utf8 tests/test_coverage.py --update # accept new coverage after an intended matching change
python -I -X utf8 stations_map.py 2023/may 31 131 0 <venues.xls> Πατρέων   # cand 0 = party share
python -I -X utf8 nikh_report.py <venues.xls>
```

Election keys: `2019`, `2023/may`, `2023/june`, `2024/euro`, all defined once in `config.ELECTIONS`. Output files replace `/` with `-` (`config.slug`: `2023-may_45.html`, `2019_45.html`).

## Architecture

**Pipeline:** `fetch.py` → SQLite (`data/stavroi.sqlite`, git-ignored, ~150 MB) → `build.py` / `stations_map.py` → `out/*.html`; `build.py` also writes `area_match`, which `compare.py` and `analysis/nikh_map.py` read for the nationwide pages.

**Modules** (no cycles: config ← matching ← web ← build ← compare/stations_map/nikh_report):
- **config.py**: paths, `ELECTIONS`, `source()` (results site per election), the SQLite `SCHEMA`, `PARTY_SHORT` (by party id; ids are stable across elections), `PARTY_ARTIFACTS`, `ELECTED`. New elections and parties go here.
- **matching.py**: name matching and `boundaries()` (ELSTAT files, loaded once per process via `functools.cache`). `match_areas()` returns `{(den, ekd): community code}` for one constituency.
- **web.py**: everything shared by pages: `fill()` (colour tokens, site CSS, theme script, fonts, header, footer), `render_page()`, and the index. `record()` adds entries to `out/maps.json` (atomic replace); `write_index()` rebuilds `out/index.html` from it, once per build. Not named `site.py`: that would shadow Python's own `site` module.

- **fetch.py** reads the Ministry of Interior results site (`/stat/{k}/…` static, `/dyn/{k}/…` results; `k`=`v` parliamentary, `e` European). `source(election)` maps an election key to (base URL, kind); Euro 2024 is served from `ekloges.ypes.gr/current`, the rest from `ekloges-prev.singularlogic.eu/{election}`. Station id = `ep * 10000 + seq`, so per-constituency queries use `tm_id BETWEEN ep*10000 AND ep*10000+9999`. Per-station preference votes (`tm_vc_*`) exist for 2019 and May 2023 only; June 2023 and Euro 2024 have party votes only. Party leaders' crosses exist only as constituency totals (`ep_total`).
- **build.py** matches each electoral district (Ε.Δ., `station.ekd_descr`) to an ELSTAT 2021 local community (`data/koinotites_2021.json`) inside its municipal unit (`data/dhm_enotites_2021.json`), by name or via a settlement (`data/oikismoi_2021.csv`). The ministry uses genitive forms and ELSTAT nominative, so matching compares word stems (`norm` → `stems`, with `phonetic` and `one_edit` fallbacks in `find`). Unmatched districts and special/absentee stations are left off the map; coverage % is reported.
  - **Party mode:** when a constituency has no per-station `cand_votes`, `main()` switches to party mode. It creates one pseudo-candidate `"{pid}:0"` per party, and the template divides by valid votes instead of party votes (`D.mode === "party"`).
  - **Rendering:** `render_page()` inlines `common.css`/`common.js` into the `/*COMMON_CSS*/`/`/*COMMON_JS*/` placeholders, then the JSON payload into `/*DATA*/null`. Every page is standalone, with no local asset files.
  - **Parallel build:** `build_all` runs one constituency per process (`ProcessPoolExecutor`). Workers only read the DB and write their own page; they return their maps.json entry and area matches, and the parent writes both (`save()`), so there is one writer. Two separate build processes at once can still race on `out/maps.json`.
  - **Index:** `out/index.html` is generated (`web.write_index()`), including the per-party artifact links and the NIKH section. Hand edits to it are lost.
- **stations_map.py** places polling stations at venues from the ministry `.xls`. It geocodes with Nominatim, at most 1 request/s with a generic User-Agent, and caches results in `data/venues_geo.json`. A geocode is kept only if it falls inside the station's ELSTAT municipal unit. `XLS_EP` aliases constituency names that differ between the results site and the spreadsheet (Β1/Β2/Β3 Αθηνών).
- **nikh_report.py** compares NIKH (party 131) May vs June 2023 in the 9 constituencies where it elected an MP.
- **compare.py**, **analysis/nikh_map.py**: nationwide pages from `build.communities()` (area_match joined with stations and party votes, one row per ELSTAT community).
- **Templates** (`template.html`, `stations_template.html`) read everything from the injected `D` object. Deep links: `#party=<pid>&cand=<cid>`.
  - **Initial fit:** `fitOnceSized()` in `common.js` delays the first `fitBounds` until the container has a real size. Pages opened in hidden tabs/panes lay out at 0×0 and would otherwise fit to zoom 0.

## Data notes

- Results on the site are unofficial; this is stated on pages and in the README.
- Use only public aggregate results and public venue addresses. No voter lists or personal data.
- `out/` and `exports/` are committed generated artifacts; `data/*.json|csv` are committed ELSTAT boundaries plus the geocode cache.
