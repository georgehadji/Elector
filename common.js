// Shared by template.html and stations_template.html; inlined at build time before the page script.
// The page script defines `map` and fills `layers` (index = table row data-i).
const $ = id => document.getElementById(id);
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt = n => n.toLocaleString("el-GR");
const pct = x => (x * 100).toLocaleString("el-GR", {maximumFractionDigits: 1}) + "%";
const HOVER = matchMedia("(hover: hover)").matches;
const TOUCH = matchMedia("(pointer: coarse)").matches;
const seq = () => ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"].map(css);

function breaks(vals) {  // quantile breaks over the non-zero values
  const nz = vals.filter(v => v > 0).sort((a, b) => a - b);
  return nz.length ? [1, 2, 3, 4, 5].map(i => nz[Math.floor(i * nz.length / 6)]) : [];
}
function colorFor(x, br) {
  if (x <= 0) return css("--s0");
  let i = 0; while (i < br.length && x > br[i]) i++; return seq()[i];
}
// One swatch and its label travel together, so a legend never wraps between them.
const swatch = (col, label) => `<span class="k"><i style="background:${col}"></i><span class="lbl">${label}</span></span>`;
const zeroLabel = () => D.mode === "party" ? "Καμία ψήφος" : "Κανένας σταυρός";
function seqLegend(br, show) {
  let h = swatch(css("--s0"), zeroLabel());
  const edges = [-Infinity, ...br];  // the first non-zero class is open below, the last open above
  seq().forEach((col, i) => { if (br.length && i <= br.length) h += swatch(col, binLabel(edges[i], br[i], show)); });
  return h;
}

// Deviation = local share / overall share (1 = average). Fixed, symmetric-in-ratio steps.
const DEV_BR = [0.5, 0.75, 0.9, 1.1, 1.33, 2];
const devPct = r => { const d = Math.round((r - 1) * 100); return (d > 0 ? "+" : d < 0 ? "−" : "±") + Math.abs(d) + "%"; };
const DEV_EDGES = [-Infinity, ...DEV_BR];
const DEV_LBL = DEV_EDGES.map((lo, i) => binLabel(lo, DEV_BR[i], devPct));
const divSteps = () => ["--d-3", "--d-2", "--d-1", "--d0", "--d1", "--d2", "--d3"].map(css);
function devColor(r) { let i = 0; while (i < DEV_BR.length && r >= DEV_BR[i]) i++; return divSteps()[i]; }
const devFmt = devPct;
const devLegend = () => `<span class="lbl" style="margin-left:0">Σε σχέση με τον μέσο όρο:</span>` +
  divSteps().map((c, i) => swatch(c, DEV_LBL[i])).join("");

// Links to the other maps of this constituency, and to the index of all maps.
$("views").innerHTML = (D.links || []).map(l => `<a href="${encodeURI(l.href)}">${l.label}</a>`).join("");

// OpenStreetMap base tiles, faded under the data. `attribution` names the page's own sources.
const baseTiles = (m, attribution, maxZoom) => (m.getContainer().classList.add("muted"), L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap · " + attribution, maxZoom, opacity: 0.6
}).addTo(m));
// (the .muted class greys the tiles, see common.css)

// No base map at all: the choropleth is the only colour on the paper-coloured #map. Used by the pages that map areas
// (polling-venue pages keep grey tiles: dots need streets to mean anything). Returns null: there are no tiles to wait for.
const blankBase = (m, attribution) => { m.attributionControl.addAttribution(attribution); return null; };

// PDF export: refit the map to the A4 print width, wait for its tiles, then open the print dialog.
// pdfTitle() becomes the document title, i.e. the suggested file name. Returns the PDF button's handler.
function printSetup(m, tiles, bounds, pdfTitle) {
  const screenTitle = document.title;
  let saved;
  const fit = () => {
    document.title = pdfTitle();
    saved = saved || [m.getCenter(), m.getZoom()];
    document.body.classList.add("printing");
    m.invalidateSize();
    m.fitBounds(bounds(), {padding: [8, 8]});
  };
  addEventListener("beforeprint", fit);  // also covers Ctrl+P
  addEventListener("afterprint", () => {
    document.body.classList.remove("printing");
    document.title = screenTitle;
    m.invalidateSize();
    if (saved) m.setView(...saved);
    saved = null;
  });
  return () => {
    fit();
    let done = false;
    const go = () => { if (!done) { done = true; window.print(); } };
    if (tiles) tiles.once("load", go);
    setTimeout(go, tiles ? 1500 : 0);
  };
}

// The first fit waits for a real container size: a page opened in a hidden tab or pane lays out at 0×0,
// where fitBounds falls back to zoom 0 (the whole world). onFit runs once, right after that fit.
function fitOnceSized(m, bounds, opts, onFit) {
  let done = false;
  const fit = () => {
    const el = m.getContainer();
    if (done || el.clientWidth < 50 || el.clientHeight < 50) return;
    done = true;
    // invalidateSize is a no-op until the map has a view, and getSize() caches the 0×0 size.
    if (m.getZoom() === undefined) m.setView([0, 0], 0, {animate: false});
    m.invalidateSize({animate: false});
    m.fitBounds(bounds(), opts);
    if (onFit) onFit();
  };
  new ResizeObserver(fit).observe(m.getContainer());
  addEventListener("resize", fit);
  document.addEventListener("visibilitychange", fit);  // hidden pages may skip ResizeObserver callbacks
  fit();
}

// Touch: one finger scrolls the page, two fingers move/zoom the map (Leaflet's pinch also pans).
function touchMap(m) {
  if (!TOUCH) return;
  m.dragging.disable();
  const hint = $("hint");
  let t;
  m.getContainer().addEventListener("touchmove", e => {
    if (e.touches.length !== 1) return hint.classList.remove("on");
    hint.classList.add("on"); clearTimeout(t); t = setTimeout(() => hint.classList.remove("on"), 1200);
  }, {passive: true});
}

// Details panel: tap/click on the map or a table row. Hover devices also get the tooltip.
const panel = document.body.appendChild(document.createElement("aside"));
panel.id = "panel"; panel.hidden = true; panel.setAttribute("aria-label", "Λεπτομέρειες");
panel.setAttribute("aria-live", "polite");
let layers = [], picked = null, opener = null;
function bindFeature(l, html) {
  l.html = html; l._b = {color: l.options.color, weight: l.options.weight};
  if (HOVER) l.bindTooltip(html, {sticky: true});
  l.on({
    mouseover: () => l !== picked && l.setStyle({color: css("--ink"), weight: 2}),
    mouseout: () => l !== picked && l.setStyle(l._b),
    click: () => pick(l),
  });
}
function pick(l, fly) {
  if (picked) picked.setStyle(picked._b);
  picked = l;
  document.querySelectorAll("tr.sel").forEach(r => r.classList.remove("sel"));
  if (!l) { const back = panel.contains(document.activeElement); panel.hidden = true; if (back) opener?.focus(); return; }
  l.setStyle({color: css("--ink"), weight: 3}); l.bringToFront();
  document.querySelector(`tr[data-i="${l.i}"]`)?.classList.add("sel");
  l.closeTooltip?.();
  panel.innerHTML = `<button type="button" class="close" aria-label="Κλείσιμο">×</button>${l.html}`;
  panel.hidden = false;
  panel.firstChild.onclick = () => pick(null);
  if (fly) {
    opener = document.activeElement;
    if (l.getLatLng) map.setView(l.getLatLng(), Math.max(map.getZoom(), 15));
    else map.fitBounds(l.getBounds(), {maxZoom: 14, padding: [24, 24]});
    $("map").scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center"});
    panel.firstChild.focus({preventScroll: true});
  }
}
function repick() { const i = picked?.i; picked = null; if (i != null && layers[i]) pick(layers[i]); else panel.hidden = true; }
addEventListener("keydown", e => e.key === "Escape" && picked && pick(null));

// Sortable table: numeric cells carry data-v. Sort state survives re-renders unless reset (tbl._sort = null).
function sortable(tbl, col, dir) {
  const st = tbl._sort ||= {col, dir};
  const ths = [...tbl.tHead.rows[0].cells];
  const apply = () => {
    ths.forEach((th, i) => i === st.col ? th.setAttribute("aria-sort", st.dir) : th.removeAttribute("aria-sort"));
    const key = r => { const td = r.cells[st.col]; return td.dataset.v != null ? +td.dataset.v : td.textContent; };
    const s = st.dir === "ascending" ? 1 : -1;
    const rows = [...tbl.tBodies[0].rows].sort((a, b) => {
      const x = key(a), y = key(b);
      return s * (typeof x === "number" ? x - y : x.localeCompare(y, "el", {numeric: true}));
    });
    tbl.tBodies[0].append(...rows);
  };
  ths.forEach((th, i) => {
    th.innerHTML = `<button type="button">${th.innerHTML}</button>`;
    th.firstChild.onclick = () => {
      st.dir = st.col === i ? (st.dir === "ascending" ? "descending" : "ascending") : th.classList.contains("n") ? "descending" : "ascending";
      st.col = i; apply();
    };
  });
  tbl.onclick = e => { const b = e.target.closest(".rowlink"); if (b) pick(layers[+b.dataset.i], true); };
  apply();
}
