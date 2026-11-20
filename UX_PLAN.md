# UX implementation plan

Source: the design review of the live site at 375×812 (2026-11-20). It covers 2 High findings, 5 Medium and 3 Low.
This plan implements all of them inside the existing architecture. It does not add dependencies: Python stays stdlib only
(plus `xlrd`), JavaScript stays vanilla and is inlined at build time, and there is no bundler.

## Ground rules

- **Module order stays acyclic:** config ← matching ← web ← build ← compare/stations_map/nikh_report.
  Every change lands in the lowest module that owns it.
- **SSOT:**
  - Text, tokens and shared behaviour are defined once.
  - `web.fill()` is the only place that injects shared parts into a page.
  - Nothing is copied between templates.
- **Order of work:** accessibility → conventions → craft → polish, one commit per phase.
- **Ownership:** `stavroi/` belongs to session `local_f4344c7d…`, so that session implements this plan.
  - Commit and push only with the user's approval.
  - Never commit `analysis/*` or `data/st.tmp`.
  - Never stash.
  - Run `git log origin/main..HEAD` before every push.

## Paradigm per module

| Module | Paradigm / pattern | Why |
|---|---|---|
| `web.py` | Functional: pure `data → str` builders composed by `_write_index`, with `fill()` as a template-method-style placeholder pipeline | HTML generation is a pure transform. Small pure builders are testable without a DB |
| `shared.js` (new) | Module of pure functions, with no DOM access at load time | One copy of search folding, legend wording and motion preference for every page, including compare and index, which do not load `common.js` |
| `theme.js` | Finite-state machine: a pure `next(state, system)` transition, plus a thin DOM adapter | Three states (system, light, dark) and two inputs. A table-driven transition removes the "stuck override" bug by construction |
| `common.js` | Adapter around Leaflet: a `mapOptions()` factory and legend builders as pure functions returning markup | Templates stop calling `L.map` with ad-hoc options, and motion and touch policy live in one place |
| `compare_template.html` | Observer: `render()` subscribed to control changes. Strategy: the existing `VIEWS` table. Precomputed index: a search index built once at load | 6,098 areas: build the index once and query in O(n) per keystroke, with no per-feature DOM |
| `site.css` | Design tokens plus one `@media (pointer:coarse)` touch layer | `site.css` is the only stylesheet every page gets, so touch-target policy lives there once |
| `tests/` | `unittest` + `html.parser` (stdlib) over the generated `out/` files | Checks structure and SSOT invariants without a browser. UI metrics are checked with the browser script in phase 5 |

## Phase 0: shared foundation (no visible change)

1. **Add `shared.js`, inlined by `fill()` through a new `/*SHARED_JS*/` placeholder** (`web.py`).
   - `fold`, `greek`, `stem`, `phon`, `key`, `hits`: moved verbatim out of `INDEX_JS`. `INDEX_JS` keeps only DOM wiring.
     `common.js` drops its own `fold` and uses the shared one.
   - `binLabel(lo, hi, fmt)`: one wording for every legend: `κάτω από X`, `X έως Y`, `X και πάνω`.
     The compare legend already uses this wording; `seqLegend` and `devLegend` switch to it.
   - `MOTION = !matchMedia("(prefers-reduced-motion: reduce)").matches`.
   - `mapOptions(extra)` returns `{zoomAnimation: MOTION, fadeAnimation: MOTION, markerZoomAnimation: MOTION, zoomSnap: 0.25, ...extra}`.
2. **Add `<script>/*SHARED_JS*/</script>` to every page template** before the page script: `template.html`,
   `stations_template.html`, `compare_template.html`, the index and coverage pages in `web.py`, and `nikh_report.py`.
   `analysis/nikh_map_template.html` also gets it, but stays local and uncommitted.
3. **Tests.** New `tests/test_pages.py`:
   - No page in `out/` still contains `/*` + `SHARED_JS` or any other placeholder.
   - `fold(` is defined once per page.
   - Every page that creates a map calls `mapOptions(`.

**Done when:** pages render exactly as before, the new tests pass, and `ruff check .` is clean.

## Phase 1: accessibility (Highs first)

### 1.1 Compare map: search and a text alternative (High)

Files: `compare_template.html`, `compare.py`.

- **Search.**
  - Add `<input id="q" type="search" placeholder="Αναζήτηση περιοχής" autocomplete="off">` in `.ctl`, with a visible label.
  - At load, build `INDEX = D.geo.features.map(f => [key-folded words of f.properties.n + u + ep, layer])` once, using the shared `key`.
  - On `input`, show up to 8 matches as `<ul id="hits">` of `<button>`s. A matching town name ranks above a matching municipal unit.
  - The match count goes into the existing `aria-live` `#sub`, or into a new `#hitsN` status element.
  - Choosing a result runs `map.fitBounds(layer.getBounds(), {maxZoom: 11, animate: MOTION})` and then `layer.openTooltip()`.
  - `Enter` with one hit picks it; `Escape` clears.
  - Pattern: a list of buttons, not an ARIA combobox. It is natively accessible, and a combobox adds ARIA state for no gain at this size.
- **Text alternative.**
  - Below the map, add `<details id="ext"><summary>Οι 10 υψηλότερες και οι 10 χαμηλότερες περιοχές</summary>…</details>`.
  - The content comes from a pure function `extremes(rows, value, n)`, reusing the value accessor that colours the map.
  - Each item is a button with the same behaviour as a search result.
  - It is rebuilt in `render()` (Observer), so it follows the party and view selection.
  - It excludes areas under the existing 50-valid-votes threshold, so that tiny villages do not fill the list.
- **Keyboard.**
  - The map region keeps `tabindex="0"`, which gives Leaflet keyboard pan and zoom.
  - Search and the extremes list cover per-area reading. Canvas paths cannot take focus, and we do not switch to SVG for 6,098 paths.
- **Done when:**
  - Keyboard alone reaches any area's tooltip via search.
  - Screen readers hear the hit count.
  - The extremes list changes with party and view.
  - No horizontal scroll at 375px.
  - `compare.html` grows by less than 5 KB.

### 1.2 Touch targets on every page (Medium)

File: `site.css` only, since it is the one stylesheet on every page. Remove the duplicates from `common.css` and the compare/nikh inline CSS.

```css
@media (pointer: coarse) {
  .leaflet-control-zoom a { width: 44px; height: 44px; line-height: 44px; }
  select, input[type=search] { min-height: 44px; }
  .bar .home, .site a { display: inline-flex; align-items: center; min-height: 44px; }  /* replaces padding:12px 0, which gave 38px at 11px text */
}
```

**Done when:** at 375×812 with coarse pointer, every `a, button, select, input` outside the Leaflet attribution and inline prose
measures at least 44px tall on index, compare, a constituency map and a station map.

### 1.3 Reduced motion (Low)

- Replace every `L.map("map", {...})` call with `L.map("map", mapOptions({...}))`. That is 4 templates; the nikh one stays local.
- In compare, `fitBounds` and `flyTo` also take `{animate: MOTION}`.
- **Done when:** with emulated `prefers-reduced-motion: reduce`, zooming jumps without animation.

## Phase 2: conventions

### 2.1 Index: progressive disclosure (High)

File: `web.py` `_write_index` (and `INDEX_CSS`). Split the builder into pure helpers: `card(name, links, top, note) -> str` and `nationwide(nikh, tm, coverage) -> str`.

- **Order.**
  1. Search.
  2. `nationwide()`: Σύγκριση εκλογών, Χάρτες ανά κόμμα, Ανά εκλογικό κατάστημα, Κάλυψη ανά νομό, as a compact link list.
     It replaces the jump links. The full sections it summarized move into it or below the list.
  3. The constituency list.
- **Card.**
  - `h2` name.
  - The "Πρώτος σε σταυρούς" line.
  - The newest election link only (`a.now`, unchanged, so `Enter`-to-open keeps working).
  - `<details class="older"><summary>Παλαιότερες εκλογές (3)</summary>` with the other chips.
  - The Attica "Δήμοι …" note moves inside `details` as well.
- **Search** is untouched: it hides and shows `li`. When a search narrows the list to one card, open its `details`
  (`li.querySelector("details").open = true`).
- **Done when:**
  - The index is at most 9,000px tall at 375px (now 16,166).
  - Every election map is still reachable in at most 2 taps from the card.
  - The search still finds "patra", "Ρόδος" and "Καλλιθέα".
  - `tests/test_pages.py` asserts that every card has a `details.older` unless it has a single election, and that the nationwide block precedes `.eps`.

### 2.2 Theme returns to the system setting (Low)

File: `theme.js`.

- **Transition table.**

  ```js
  // state: "system" | "light" | "dark"; press flips the effective appearance.
  const next = (state, sysDark) => {
    const dark = state === "system" ? sysDark : state === "dark";
    const want = dark ? "light" : "dark";
    return (want === "dark") === sysDark ? "system" : want;  // matching the system = follow it again
  };
  ```

- **Adapter.**
  - `system` removes `localStorage.theme` and `data-theme`.
  - `light` and `dark` store the value and set it.
  - It still dispatches `themechange`.
- `aria-pressed` keeps reflecting the effective dark state.
- **Done when:**
  - Starting from system light, the first press gives dark (stored) and the second gives system (storage empty).
  - With nothing stored, changing the OS appearance changes the page live.

## Phase 3: craft

### 3.1 Constituency map controls truncate at 375px (Medium)

File: `common.css`, phone block, around lines 80–83.

- Under 420px, `#q` and `#cand` each take `flex: 1 1 100%`.
- The placeholder in `template.html` and `stations_template.html` becomes `Αναζήτηση υποψηφίου`. It is short enough at full width and names what is searched.
- **Done when:** no text is clipped in `#q`'s placeholder or in the selected `#cand` option at 375px. Check with `scrollWidth <= clientWidth`.

### 3.2 Legend wording and wrapping (Medium)

Files: `common.js` (`seqLegend`, `devLegend`), `common.css`.

- Each swatch and its label are emitted as one unit, `<span class="k"><i></i><span class="lbl">…</span></span>`, with
  `.legend .k { display: inline-flex; align-items: center; white-space: nowrap; }`.
- The zero class gets an explicit label, passed by the caller: `Κανένας σταυρός` in candidate mode and `Καμία ψήφος` in party mode (`D.mode === "party"`).
- The bins use the shared `binLabel`, so the first non-zero bin reads `έως 49,3%` instead of `0%–49,3%`.
- The compare legend uses the same `binLabel` (SSOT for wording).
- **Done when:**
  - At 375px no swatch sits on a different line from its label.
  - The legend text matches the compare legend's wording pattern.

### 3.3 The cross mark (Medium)

File: `web.py` `CROSS_SVG`.

- Add a ballot-box frame: `<rect x="3" y="3" width="34" height="34" rx="3"/>`. This uses the same stroke and is inside the same `aria-hidden` SVG.
- Size the frame in `INDEX_CSS` (`.x`), so the mark reads as "a cross on a ballot", not as "close".
- The mark is the signature of the site: keep it, and do not add it anywhere else.
- **Done when:** the visual check shows the boxed cross in light and dark. It still has no accessible name, since the text beside it carries the meaning.

## Phase 4: polish

### 4.1 Titles without middle dots (Low)

- **Map pages.** In the page scripts of `template.html` and `stations_template.html`, `#title` becomes
  `Εκλογική περιφέρεια {ep}`, and the subtitle becomes `Σταυροί προτίμησης, βουλευτικές εκλογές Μαΐου 2023, ανά εκλογικό διαμέρισμα`.
  - Build the strings from `config.ELECTIONS` names through the existing payload; do not hard-code election names.
  - `pdfTitle()` keeps its own file-name form; check that it does not change.
- **Index.** In `web.py` `nikh_rows`, `" · "` becomes `", "`.
- **Done when:** `grep -c " · " out/2023-may_45.html` returns 0 for title and subtitle. The Leaflet attribution separator is not ours, so it is excluded.

## Phase 5: build, verify, ship

1. **Rebuild.** Build each election, then the index, compare and the NIKH report:

   ```
   python -I -X utf8 build.py 2019 all
   python -I -X utf8 build.py 2023/may all
   python -I -X utf8 build.py 2023/june all
   python -I -X utf8 build.py 2024/euro all
   python -I -X utf8 build.py index
   python -I -X utf8 compare.py
   python -I -X utf8 nikh_report.py <venues.xls>
   ```

   - Station maps are rebuilt with `stations_map.py` from the geocode cache only.
   - A cached null venue is not re-queried. If any Nominatim request is needed, stay at 1 req/s and stop on HTTP 429.
2. **Tests.** Run `python -I -X utf8 -m unittest discover -s tests`. The coverage regression must be unchanged; this plan does not touch matching.
3. **Lint.** Run `ruff check .`.
4. **Browser check at 375×812 with coarse pointer, light and dark**, on the index, compare, `2023-may_45.html`, one station map and the NIKH report. Re-run the review's measurement script and expect:
   - 0 contrast failures.
   - 0 interactive elements under 44px tall, outside Leaflet attribution and inline prose.
   - 0 text under 11px.
   - `scrollWidth == 375`.
   - Index height at most 9,000px.
   - Compare: search reaches an area and the extremes list follows the selections.
5. **Ship.**
   - One commit per phase (0–4), each with the generated `out/` files it changed.
   - Push after the user approves.
   - Re-check the live site after Pages deploys.

## Risks

- **Index restructure** may break the existing jump anchors (`#ep-N` is kept, the jump links are replaced). Check inbound links in the README before removing any anchor.
- **`shared.js` inlining** adds about 2 KB to each of the ~255 pages. That is acceptable; the pages are 100–5,000 KB.
- **Compare search on 6,098 features**: the precomputed index keeps a keystroke under 5 ms. Debounce only if measurement shows otherwise.
- **`analysis/nikh_map_template.html`** gets the same edits locally but stays uncommitted under the analysis/* rule. Its live page (`out/nikh_2023-2024.html`) is generated and committed as usual.
