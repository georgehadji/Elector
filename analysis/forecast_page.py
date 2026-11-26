"""National election forecast -> out/forecast.html, from analysis/forecast.json (run analysis/forecast.py with the database
first; this script needs no simulation, but it does read the database, for the outlines of the constituency map).

Shown for an election today and in 180 days (radio buttons, CSS :has()): who reaches 151 seats, each party's
share (median and 80% range, with P(>= 3%); parties under 3% today folded away), expected seats as one 300-seat bar and
per coalition, seat ranges with and without the bonus, the histograms of ND's seats alone and with PASOK or ELAS, and the
expected seats per constituency as a map (one party at a time, radio buttons again) and a table. The map's outlines are the
ELSTAT 2021 municipal units of each constituency's polling stations in June 2023, read from the database (data/stavroi.sqlite);
the rest comes from forecast.json. Then how close each polling firm fell at the last three elections (pollster_record.py; a
table, and a check that counting the better firms a bit more would not change the shares). If analysis/samaras.json exists
(samaras_scenarios.py), a scenario section: a Samaras party at 10, 11 or 12%, elections today; it goes once the party has
polls and is in forecast.json as a party like the others. Charts are HTML/SVG built here (no
chart library); the histograms have a wide and a narrow drawing, the CSS shows one.
Party colours: the reference palette of the dataviz skill in its validated order (adjacent pairs in the seat bar pass the
colour-vision checks in both themes, against INDEX_LIGHT/INDEX_DARK paper); parties past the eighth are grey.

  python -I -X utf8 analysis/forecast_page.py
"""
import csv
import html
import json
import sqlite3
import sys
import math
import unicodedata
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast as F
import pollster_record as PR
import seats_law as LAW

MAJ, SEATS, THR, STATE = LAW.MAJORITY, LAW.SEATS, LAW.THRESHOLD, LAW.STATE  # the law's figures: never typed here

from config import DB, FORECAST_COLOURS, HERE, slug
from geo import boundary, frame, path
from matching import boundaries, centroid, match_units
from web import INDEX_DARK, INDEX_LIGHT, fill, meta, secure

OUT = HERE / "out" / "forecast.html"  # its folder is where the maps are looked up
H180_NOTE = ('<p class="note h180">Σε έξι μήνες οι δημοσκοπήσεις μπορεί να έχουν κινηθεί, οπότε όλα τα εύρη ανοίγουν. Γι’ αυτό ό,τι σήμερα είναι απίθανο γίνεται λίγο πιθανότερο, και ό,τι είναι σχεδόν βέβαιο λίγο λιγότερο.</p>')
MAP_ELECTION = "2023/june"  # per-constituency rows link to this election's maps
WIKI = "https://en.wikipedia.org/wiki/Opinion_polling_for_the_next_Greek_legislative_election"
COLOURS = FORECAST_COLOURS  # party: (light, dark); dict order = slot order = order in the seat bar
MUTE = ("#9a988f", "#6f6d66")
MONTHS = ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μαΐ", "Ιουν", "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"]
WHEN = {"0": "σήμερα", "180": "σε έξι μήνες"}


def num(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def thousands(n):
    return f"{n:,}".replace(",", ".")


def pct(p):
    """A probability as a percentage: one decimal under 10% and over 90% (so 0,997 is 99,7%, not 100%), none between;
    the ends say so instead of 0% or 100%."""
    if p < 0.001:
        return "<0,1%"
    if p > 0.999:
        return ">99,9%"
    return f"{num(100 * p, 1 if p < 0.1 or p > 0.9 else 0)}%"


def day(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def mean_seats(dist):
    """Mean of {seats: frequency} as read back from forecast.json (keys are strings there)."""
    return sum(int(k) * f for k, f in dist.items())


HATCHED = set()  # parties past the eighth colour that win seats in the median case; main() fills it


def colour(p):
    """A party's fill: its slot colour, grey with lines for a ninth party with seats (no ninth hue), plain grey else."""
    return f"var(--p-{p})" if p in COLOURS else "var(--hatch)" if p in HATCHED else "var(--mute)"


def expected(r):
    """{party: expected seats}, the mean over the simulations, rounded to 300 by largest remainder."""
    mean = {}
    for e in r["eps"].values():
        for p, dist in e["dist"].items():
            mean[p] = mean.get(p, 0) + mean_seats(dist)
    whole = {p: int(m) for p, m in mean.items()}
    for p in sorted(mean, key=lambda p: whole[p] - mean[p])[:SEATS - sum(whole.values())]:
        whole[p] += 1
    assert sum(whole.values()) == SEATS, whole
    return whole


def often(p):
    """A probability in words, as a share of the simulations: 'περίπου 1 στις 120', 'περίπου 7 στις 10'."""
    one_in = lambda q: thousands(int(round(1 / q, 2 - len(str(round(1 / q))))))  # two significant digits: 278 -> 280
    if p < 0.001:
        return "λιγότερο από 1 στις 1.000"
    if p < 0.095:
        return f"περίπου 1 στις {one_in(p)}"
    if p <= 0.95:
        return f"περίπου {round(10 * p)} στις 10"
    if p <= 0.999:
        return f"όλες εκτός από περίπου 1 στις {one_in(1 - p)}"
    return "σχεδόν όλες"


def in_sims(p):
    """often(p) as a phrase of the lead, with the percentage: 'σε περίπου 1 στις 120 προσομοιώσεις (0,8%)'."""
    w = often(p)
    if w == "σχεδόν όλες":
        return "σχεδόν σε όλες τις προσομοιώσεις"
    if w.startswith("όλες "):
        return f"σε όλες τις προσομοιώσεις {w.removeprefix('όλες ')} ({pct(p)})"
    return f"σε {w} προσομοιώσεις ({pct(p)})"


def lead(r, key):
    """The answer first, at display size: how often ND alone, and ND with PASOK or with ELAS, reach 151 seats (the 151
    list's order); then one sentence on ND's share and seats."""
    nd = r["parties"]["ND"]
    figs = "".join(f'<p><b>{pct(r[k])}</b><span class="t"><strong>{t}</strong><small>{MAJ} έδρες {in_sims(r[k]).replace(f" ({pct(r[k])})", "")}</small>'
                   '</span></p>' for t, k in (("ΝΔ μόνη της", "p_nd_majority"), ("ΝΔ και ΠΑΣΟΚ", "p_nd_pasok_151"),
                                              ('ΝΔ και <abbr title="Ελληνική Αριστερή Συμπαράταξη">ΕΛΑΣ</abbr>', "p_nd_elas_151")))
    return (f'<div class="hero h{key}">{figs}</div>'
            f'<p class="lead h{key}">Αν οι εκλογές γίνονταν {WHEN[key]}, η ΝΔ θα ήταν πρώτη {in_sims(nd["p_first"])}, '
            f'με {num(nd["share"][1])}% και {nd["seats"][1]} έδρες (μεσαία τιμή).</p>')


def hist_range(h):
    """[10%, median, 90%] of a {seats: count} histogram, the same quantiles as forecast.q()."""
    h = sorted((int(k), v) for k, v in h.items())
    n = sum(v for _, v in h)
    out = []
    for f in (.1, .5, .9):
        i, c = min(n - 1, int(f * n)), 0
        for seats, v in h:
            c += v
            if c > i:
                out.append(seats)
                break
    return out


# who reaches 151: label and row class of each of forecast.COALITIONS (its keys come from forecast.p_key / h_key)
GROUPS = {("ND",): ("ΝΔ μόνη της (αυτοδυναμία)", ' class="nd"'), ("ND", "PASOK"): ("ΝΔ και ΠΑΣΟΚ", ""),
          ("ND", "ELAS"): ("ΝΔ και ΕΛΑΣ", ""), ("PASOK", "ELAS"): ("ΠΑΣΟΚ και ΕΛΑΣ", ""),
          ("ND", "PASOK", "ELAS"): ("ΝΔ, ΠΑΣΟΚ και ΕΛΑΣ", ' class="far"')}
assert set(GROUPS) == set(F.COALITIONS), "a coalition of forecast.COALITIONS has no label here"


def odds(r, key):
    """One row per group: its seats (median and 80% range of the summed seats, as in the seat table) drawn against the
    151 line, and how often it reaches 151. The three-party sum is near certain by arithmetic alone, so it is quieter.
    The bar's segments are the parties' mean seats, the widths of the seat bar below."""
    seats = expected(r)
    items = []
    for ps in F.COALITIONS:
        title, c = GROUPS[ps]
        p, (lo, mid, hi) = r[F.p_key(ps)], hist_range(r[F.h_key(ps)])
        ps = sorted(ps, key=list(COLOURS).index)
        n = sum(seats.get(x, 0) for x in ps)
        spans = ("".join(f'<span style="--c:{colour(x)};flex:{seats.get(x, 0)}"></span>' for x in ps)
                 + f'<span class="rest" style="flex:{SEATS - n}"></span>')
        items.append(f'<li{c}><span class="lb"><span>{title.replace("ΕΛΑΣ", '<abbr title="Ελληνική Αριστερή Συμπαράταξη">ΕΛΑΣ</abbr>')}</span><small>{mid} έδρες ({lo}–{hi}) · {often(p)}</small></span>'
                     f'<div class="seatbar mini" role="img" aria-label="{title}: {mid} έδρες, στις 8 από τις 10 από {lo} '
                     f'έως {hi}">{spans}<i></i></div><b>{pct(p)}</b></li>')
    return (f'<h2>Ποιοι φτάνουν τις {MAJ} έδρες</h2>'
            '<p class="note">Οι έδρες του κόμματος, ή των κομμάτων μαζί: η μεσαία τιμή και, σε παρένθεση, το εύρος όπου '
            f'πέφτουν στις 8 από τις 10. Δεξιά, σε τι ποσοστό των προσομοιώσεων φτάνουν τις {MAJ}. Η γραμμή στη μπάρα είναι '
            f'οι {MAJ}. Είναι αθροίσματα εδρών, όχι πρόβλεψη για το ποια κυβέρνηση θα σχηματιστεί.</p>'
            f'<ul class="odds">{"".join(items)}</ul>')


def shares(r, order, names, small):
    """One row per party; the parties in `small` (under 3% today, the same at both horizons) go in a closed <details>
    below, with their own copy of the header and axis on the same scale."""
    top = max(r["parties"][p]["share"][2] for p in order)
    scale = 5 * (int(top) // 5 + 1)
    x = lambda v: f"{100 * v / scale:.2f}%"
    step = 10 if scale > 20 else 5  # no 0% tick: it would crowd the 3% label beside it
    ticks = "".join(f'<span style="left:{x(v)}">{v}%</span>' for v in range(step, scale + 1, step))
    grid = "".join(f'<span class="gl" style="left:{x(v)}"></span>' for v in range(step, scale + 1, step))  # scale on every row
    head = ('<div class="sh"><span class="hd l">κόμμα</span><span class="hd tk"></span>'
            '<span class="hd">ποσοστό</span><span class="hd">περνά το 3%</span>'
            f'<span></span><span class="trk ax">{ticks}<span style="left:{x(THR)}">{THR:g}%</span></span><span></span><span></span>')
    rows = {}
    for p in order:
        lo, mid, hi = r["parties"][p]["share"]
        d = 1 if hi < 10 else 0
        p_in = "—" if p == F.OTHER else pct(r["parties"][p]["p_in"])  # many small parties together: no threshold
        tip = f"{names[p]}: {num(mid)}% (80%: {num(lo)}–{num(hi)}%)" + ("" if p == F.OTHER else f", πιθανότητα να περάσει το 3%: {p_in}")
        rows[p] = (f'<span class="nm">{html.escape(names[p])}</span>'
                   f'<span class="trk" title="{html.escape(tip, quote=True)}" style="--c:{colour(p)}">'
                   f'{grid}<span class="thr" style="left:{x(THR)}"></span>'
                   f'<span class="rng" style="left:{x(lo)};width:{100 * (hi - lo) / scale:.2f}%"></span>'
                   f'<span class="dot" style="left:{x(mid)}"></span></span>'
                   f'<span class="v">{num(mid)}%<small>{num(lo, d)}–{num(hi, d)}</small></span><span class="v">{p_in}</span>')
    big = [p for p in order if p not in small]
    return ('<p class="note">Κουκκίδα: το μεσαίο ποσοστό των προσομοιώσεων. Γραμμή, και αριθμοί κάτω από το ποσοστό: το '
            'εύρος όπου πέφτει στις 8 από τις 10. Διακεκομμένη γραμμή: το όριο του 3%.</p>'
            + head + "".join(rows[p] for p in big) + "</div>"
            + (f'<details><summary>Άλλα {len(small)} κόμματα, κάτω από 3% σήμερα</summary>'
               + head + "".join(rows[p] for p in order if p in small) + "</div></details>" if small else ""))


def seatbar(order, names, r):
    """The 300 seats as one bar of the parties' mean seats (means add up to 300, medians do not), coloured parties in
    slot order, then hatched ones, the rest folded into one grey segment. No numbers here: the seat table below holds
    them, as medians, so the page quotes one figure per party."""
    seats = expected(r)
    rest = [p for p in order if p not in COLOURS and p not in HATCHED and seats.get(p)]
    parts = [(colour(p), names[p], seats[p], "") for p in [*COLOURS, *(p for p in order if p in HATCHED)] if seats.get(p)]
    if rest:
        parts.append(("var(--mute)", "Άλλα κόμματα", sum(seats[p] for p in rest), " (" + ", ".join(names[p] for p in rest) + ")"))
    spans = "".join(f'<span style="--c:{c};flex:{n}" title="{html.escape(t + x, quote=True)}"></span>' for c, t, n, x in parts)
    legend = "".join(f'<li><i style="--c:{c}"></i>{html.escape(t + x)}</li>' for c, t, _, x in parts)
    label = ", ".join(t + x for _, t, _, x in parts)
    return (f'<div class="seatbar" role="img" aria-label="Οι {SEATS} έδρες, από αριστερά: {html.escape(label, quote=True)}">'
            f'{spans}<i></i></div>'
            f'<div class="trk ax"><span style="left:0;transform:none">0</span><span style="left:{100 * MAJ / SEATS:.2f}%">{MAJ}</span>'
            f'<span style="right:0;transform:none">{SEATS}</span></div>'
            f'<ul class="legend">{legend}</ul>')


def fold(title, table):
    """The table behind a diagram: closed until the reader asks for the numbers."""
    return f'<details><summary>{title}</summary>{table}</details>'


def seats_range(x):
    """[10%, median, 90%] as '117 (100–134)'; one number when the range is a single value."""
    return "—" if not x else str(x[1]) if x[0] == x[2] else f"{x[1]} <small>({x[0]}–{x[2]})</small>"


def seat_table(r, order, names):
    rows = []
    for p in order:
        d = r["parties"][p]
        if "seats" not in d or d["seats"][2] == 0:  # OTHER has no seats
            continue
        rows.append(f'<tr><td><span class="sw" style="--c:{colour(p)}"></span>{html.escape(names[p])}</td>'
                    f'<td class="n pf">{pct(d["p_first"])}</td><td class="n">{seats_range(d["seats"])}</td>'
                    f'<td class="n">{seats_range(d["seats_bonus"])}</td><td class="n">{seats_range(d["seats_nobonus"])}</td></tr>')
    return (fold('Οι έδρες κάθε κόμματος σε πίνακα', '<div class="wrap"><table><thead><tr><th>κόμμα</th><th class="n pf">βγαίνει πρώτο</th><th class="n">έδρες</th>'
            '<th class="n">αν υπάρχει μπόνους</th><th class="n">χωρίς μπόνους</th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table></div>') +
            '<p class="note">Έδρες: η μεσαία τιμή των προσομοιώσεων και, σε παρένθεση, το εύρος όπου πέφτει στις 8 από τις 10. '
            '«Αν υπάρχει μπόνους»: μόνο οι προσομοιώσεις όπου το '
            f'πρώτο κόμμα πήρε 25% και πάνω, δηλαδή {pct(r["p_bonus"])} του συνόλου.</p>')


def hist(h, w, hgt, fs, every):
    """SVG histogram of {seats: count}: one bar per seat number, 151 and above in the accent colour."""
    h = {int(k): v for k, v in h.items()}
    total = sum(h.values())
    lo, hi = min(min(h), 140) - 1, max(max(h), 160) + 1
    top = max(h.values()) / total
    step = next(s for s in (0.005, 0.01, 0.02, 0.05) if top / s <= 5)
    ymax = step * (int(top / step) + 1)
    left, right, tp, bottom = 3 * fs, 0.6 * fs, 1.4 * fs, 2 * fs
    bw = (w - left - right) / (hi - lo)
    X = lambda s: left + (s - lo) * bw
    Y = lambda v: tp + (hgt - tp - bottom) * (1 - v / ymax)
    out = [f'<svg viewBox="0 0 {w} {hgt}" style="font-size:{fs}px" aria-hidden="true">']
    k = 0
    while k * step <= ymax + 1e-9:
        v = k * step
        out.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                   f'<text class="ax-l" x="{left - 0.4 * fs}" y="{Y(v) + 0.35 * fs:.1f}" text-anchor="end">{num(100 * v, 0 if step >= 0.01 else 1)}%</text>')
        k += 1
    for s in range(lo + 1, hi):
        if s % every == 0:
            out.append(f'<text class="ax-l" x="{X(s) + bw / 2:.1f}" y="{hgt - bottom + 1.3 * fs:.1f}" text-anchor="middle">{s}</text>')
    gap = 0.5 if bw > 3 else 0.2
    for s, c in sorted(h.items()):
        f = c / total
        out.append(f'<rect class="bar{" win" if s >= MAJ else ""}" x="{X(s) + gap / 2:.2f}" y="{Y(f):.1f}" '
                   f'width="{max(bw - gap, 0.4):.2f}" height="{Y(0) - Y(f):.1f}"><title>{s} έδρες: {pct(f)}</title></rect>')
    out.append(f'<line class="base" x1="{left}" x2="{w - right}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/>'
               f'<line class="m151" x1="{X(MAJ):.1f}" x2="{X(MAJ):.1f}" y1="{tp - 0.6 * fs:.1f}" y2="{Y(0):.1f}"/>'
               f'<text class="m151-l" x="{X(MAJ) + 0.3 * fs:.1f}" y="{tp - 0.2 * fs:.1f}">{MAJ}</text>')
    return "\n".join(out) + "</svg>"


def histograms(r):
    out = []
    no_bonus = 1 - r["p_bonus"]
    hump = ("" if no_bonus < 0.005 else  # the low values on the left: no party reached 25%, so no bonus seats
            f" Οι χαμηλές τιμές αριστερά είναι κυρίως οι προσομοιώσεις χωρίς μπόνους ({pct(no_bonus)}), όπου κανένα "
            "κόμμα δεν έφτασε το 25%.")
    for key, title, p in (("hist_nd", "Έδρες της ΝΔ", r["p_nd_majority"]),
                          ("hist_nd_pasok", "Έδρες ΝΔ και ΠΑΣΟΚ μαζί", r["p_nd_pasok_151"]),
                          ("hist_nd_elas", "Έδρες ΝΔ και ΕΛΑΣ μαζί", r["p_nd_elas_151"]),
                          ("hist_pasok_elas", "Έδρες ΠΑΣΟΚ και ΕΛΑΣ μαζί", r["p_pasok_elas_151"])):
        out.append(f'<figure><h3>{title}</h3><div class="wide">{hist(r[key], 440, 210, 12, 20)}</div>'
                   f'<div class="narrow">{hist(r[key], 360, 210, 12, 20)}</div>'
                   f'<figcaption>{MAJ} ή περισσότερες: {pct(p)}.</figcaption></figure>')
    return ('<details><summary>Πώς κατανέμονται οι έδρες στις προσομοιώσεις</summary>'
            f'<p class="note">Ποσοστό των προσομοιώσεων ανά αριθμό εδρών· η διακεκομμένη γραμμή είναι οι {MAJ}.{hump}</p>'
            '<div class="two">' + "".join(out) + "</div></details>")


def partners_html(r, names):
    """§4, third partner: when ND alone, or ND and PASOK, fall short of 151, how often one more party is enough (a share of
    those simulations; forecast.partners). Seat sums only."""
    cols = []
    for base, title in (("ND", "Όταν η ΝΔ μόνη της δεν φτάνει"), ("ND_PASOK", "Όταν ΝΔ και ΠΑΣΟΚ δεν φτάνουν")):
        d = r["partners"][base]
        if not d["n_short"]:
            continue
        rows = "".join(f'<li><span class="sw" style="--c:{colour(x)}"></span>{html.escape(names[x])}<b>{pct(p)}</b></li>'
                       for x, p in d["p"].items() if p >= 0.005)
        cols.append(f'<div><h3>{title}</h3><p class="note">Συμβαίνει {in_sims(d["n_short"] / r["n"])}. Τότε, πόσο συχνά '
                    f'φτάνει τις {MAJ} με ένα ακόμη κόμμα:</p><ul class="pl">{rows or "<li>με κανένα</li>"}</ul></div>')
    if not cols:
        return ""
    return (f'<h3 class="sub">Ποιο κόμμα αρκεί, όταν δεν φτάνουν</h3><div class="two">{"".join(cols)}</div>'
            '<p class="note">Αθροίσματα εδρών, όχι πρόβλεψη για το ποιος θα συνεργαζόταν με ποιον.</p>')


def gap_svg(h, step, a, b, w, hgt, fs):
    """SVG histogram of {gap bin: count} (share(a) - share(b), points): bars right of 0 in a's colour, left in b's."""
    h = {float(k): v for k, v in h.items()}
    total = sum(h.values())
    top = max(h.values()) / total
    lo, hi = min(min(h), -2 * step), max(max(h), 2 * step) + step
    tick = next((t for t in (0.005, 0.01, 0.02, 0.05, 0.1) if top / t <= 4), 0.2)
    ymax = tick * (int(top / tick) + 1)
    left, right, tp, bottom = 3 * fs, 0.6 * fs, 0.8 * fs, 2 * fs
    X = lambda v: left + (v - lo) / (hi - lo) * (w - left - right)
    Y = lambda v: tp + (hgt - tp - bottom) * (1 - v / ymax)
    out = [f'<svg viewBox="0 0 {w} {hgt}" style="font-size:{fs}px" aria-hidden="true">']
    k = 0
    while k * tick <= ymax + 1e-9:
        out.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{Y(k * tick):.1f}" y2="{Y(k * tick):.1f}"/>'
                   f'<text class="ax-l" x="{left - 0.4 * fs}" y="{Y(k * tick) + 0.35 * fs:.1f}" text-anchor="end">'
                   f'{num(100 * k * tick, 0 if tick >= 0.01 else 1)}%</text>')
        k += 1
    every = 2 if hi - lo <= 24 else 4
    for v in range(int(lo) - int(lo) % every, int(hi) + 1, every):
        if lo <= v <= hi:
            out.append(f'<text class="ax-l" x="{X(v):.1f}" y="{hgt - bottom + 1.3 * fs:.1f}" text-anchor="middle">'
                       f'{"+" if v > 0 else ""}{v}</text>')
    bw = X(lo + step) - X(lo)
    for v, c in sorted(h.items()):
        f = c / total
        out.append(f'<rect x="{X(v) + 0.3:.2f}" y="{Y(f):.1f}" width="{max(bw - 0.6, 0.4):.2f}" height="{Y(0) - Y(f):.1f}" '
                   f'style="fill:{colour(a if v >= 0 else b)}"><title>{num(v)} έως {num(v + step)} μονάδες: {pct(f)}</title></rect>')
    out.append(f'<line class="base" x1="{left}" x2="{w - right}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/>'
               f'<line class="m151" x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{tp:.1f}" y2="{Y(0):.1f}"/>')
    return "".join(out) + "</svg>"


def second_html(r, key, names):
    """§3, second place: how often each of the two contenders comes second, and the gap between them in the simulations."""
    a, b = r["second"]["pair"]
    pa, pb = (r["parties"][x]["p_second"] for x in (a, b))
    figs = "".join(f'<p><b>{pct(p)}</b><span class="t"><strong><span class="sw" style="--c:{colour(x)}"></span>'
                   f'{html.escape(names[x])}</strong><small>δεύτερο κόμμα</small></span></p>' for x, p in ((a, pa), (b, pb)))
    rest = 1 - pa - pb
    other = f" Άλλο κόμμα δεύτερο: {pct(rest)}." if rest >= 0.001 else ""
    g = r["second"]
    na, nb = html.escape(names[a]), html.escape(names[b])
    cap = f'Ποσοστό {na} μείον ποσοστό {nb}, σε μονάδες, στις προσομοιώσεις. Δεξιά από το 0 μπροστά είναι {na}, αριστερά {nb}.'
    return (f'<h2>Ποιος έρχεται δεύτερος</h2>'
            f'<div class="hero duo">{figs}</div>'
            f'<p class="note">Πόσο συχνά βγαίνει δεύτερο το κάθε κόμμα στις προσομοιώσεις.{other}</p>'
            f'<figure><div class="wide">{gap_svg(g["gap"], g["step"], a, b, 640, 180, 12)}</div>'
            f'<div class="narrow">{gap_svg(g["gap"], g["step"], a, b, 360, 180, 12)}</div><figcaption>{cap}</figcaption></figure>')


# left to right in the hemicycle [judgement: where each party sits; display only]; parties not listed go after them
SEAT_ORDER = ("KKE", "MERA25", "NEA_ARISTERA", "PE", "SYRIZA", "ELAS", "DIMOKRATES", "PASOK", "ELPIDA", "ND", "FL", "SE", "EL",
              "NIKI", "SPARTIATES")
ROWS = 9


def hemicycle(parl, label):
    """SVG of the 300 seats of {party: seats} in ROWS arcs, parties from left to right in SEAT_ORDER, a line in the middle."""
    r0, r1, R = 46.0, 100.0, 104.0
    radii = [r0 + i * (r1 - r0) / (ROWS - 1) for i in range(ROWS)]
    per = LAW.hare(dict(enumerate(radii)), LAW.LAWS[LAW.CURRENT]["seats"])  # seats per arc in proportion to its length
    pos = []
    for i, rr in enumerate(radii):
        for j in range(per[i]):
            t = math.pi * (1 - j / (per[i] - 1))
            pos.append((-t, rr, R + rr * math.cos(t), R - rr * math.sin(t)))
    pos.sort()  # by angle from the left, then from the inner arc out
    order = [p for p in SEAT_ORDER if parl.get(p)] + [p for p in parl if p not in SEAT_ORDER and parl[p]]
    seq = [p for p in order for _ in range(parl[p])]
    dot = 0.42 * (r1 - r0) / (ROWS - 1)
    out = [f'<svg viewBox="0 0 {2 * R} {R + 4}" role="img" aria-label="{html.escape(label, quote=True)}">']
    for (_, _, x, y), p in zip(pos, seq, strict=True):
        fill = 'var(--mute)' if p in HATCHED else colour(p)  # a pattern fill would not tile on a dot
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{dot:.2f}" style="fill:{fill}"/>')
    out.append(f'<line class="m151" x1="{R}" x2="{R}" y1="{R - r1 - 4}" y2="{R - r0 + 6}"/></svg>')
    return "".join(out)


def bonus_html(r, key, names):
    """§5, the 25% threshold: how often no party reaches 25% (no bonus), how often ND alone or with a partner reaches 151 in
    each case, and the median parliament of each; a worked example of the bonus from seats_law."""
    sc, p_no = r["scenarios"], 1 - r["p_bonus"]
    b = LAW.LAWS[LAW.CURRENT]["bonus"]
    x = r["parties"]["ND"]["share"][1]
    seats = LAW.bonus_seats(x)
    example = (f'Με τη ΝΔ στο {num(x)}% (μεσαία τιμή), το μπόνους θα ήταν {b["base"]} + {seats - b["base"]} = {seats} έδρες: '
               f'{b["base"]} στο {num(b["from"], 0)}% και μία ακόμη για κάθε ολόκληρη μισή μονάδα πάνω από αυτό, έως {b["cap"]}.'
               if seats else f'Με τη ΝΔ στο {num(x)}% (μεσαία τιμή), κάτω από {num(b["from"], 0)}%, δεν θα υπήρχε μπόνους.')
    head = (f'<tr><th></th><th class="n">πόσο συχνά</th><th class="n">έδρες ΝΔ</th><th class="n">ΝΔ μόνη {MAJ}</th>'
            f'<th class="n">ΝΔ και ΠΑΣΟΚ {MAJ}</th><th class="n">ΝΔ και ΕΛΑΣ {MAJ}</th></tr>')
    rows, figs = [], []
    for k, title in (("bonus", "με μπόνους"), ("nobonus", "χωρίς μπόνους")):
        s = sc[k]
        if not s["n"]:
            continue
        lo, mid, hi = hist_range(s["hist_nd"])
        rr = s["rates"]
        rows.append(f'<tr><th scope="row">{title}</th><td class="n">{pct(s["n"] / r["n"])}</td><td class="n">{mid} <small>({lo}–{hi})</small></td>'
                    f'<td class="n">{pct(rr["p_nd_majority"])}</td><td class="n">{pct(rr["p_nd_pasok_151"])}</td>'
                    f'<td class="n">{pct(rr["p_nd_elas_151"])}</td></tr>')
        if s["n"] / r["n"] >= 0.01:  # a parliament is drawn only for a case that happens at least once in 100
            parl = sorted(((p, v) for p, v in s["parliament"].items() if v), key=lambda kv: -kv[1])
            label = f'Βουλή {title}, μεσαίες έδρες: ' + ", ".join(f'{names[p]} {v}' for p, v in parl)
            key_ = "".join(f'<li><i style="--c:{colour(p)}"></i>{html.escape(names[p])} <b>{v}</b></li>' for p, v in parl)
            figs.append(f'<figure><h3>Η Βουλή {title}</h3>{hemicycle(dict(parl), label)}<ul class="legend">{key_}</ul></figure>')
    return (f'<h2>Το όριο του 25%</h2>'
            f'<p class="note">Αν το πρώτο κόμμα μείνει κάτω από {num(b["from"], 0)}%, δεν παίρνει μπόνους και οι {SEATS} έδρες '
            f'μοιράζονται αναλογικά. Αυτό συμβαίνει {in_sims(p_no)}. {example}</p>'
            + fold('Ο πίνακας με τους αριθμούς', f'<div class="wrap"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>')
            + ('<p class="note">Κάθε Βουλή: η μεσαία τιμή των εδρών κάθε κόμματος στις προσομοιώσεις αυτής της περίπτωσης, '
               f'στρογγυλεμένη ώστε να αθροίζει {SEATS}. Η γραμμή στη μέση χωρίζει τις {SEATS // 2} από τις {SEATS // 2}.</p>'
               f'<div class="two">{"".join(figs)}</div>' if figs else ""))


# share of the simulations a seat is won in, from the most sure down; the toss-up map uses the floor of "με κλίση"
TIERS = ((0.95, "ασφαλείς"), (0.75, "πιθανές"), (0.65, "με κλίση"), (0.35, "αμφίρροπες"), (0.05, "δύσκολες"))
TIER_ALPHA = (1, .72, .52, .32, .16)
BLOC_NAMES = {"right": "Κεντροδεξιά και δεξιά", "left": "Κεντροαριστερά και αριστερά"}
assert set(BLOC_NAMES) == set(F.BLOCS), "a side of forecast.BLOCS has no name here"


def ladder(h):
    """Seats per tier from {seats: count}: the k-th seat goes to the first tier whose floor P(seats >= k) reaches."""
    h = {int(k): v for k, v in h.items()}
    n = sum(h.values())
    out = [0] * len(TIERS)
    for k in range(1, max(h) + 1):
        p = sum(v for s, v in h.items() if s >= k) / n
        i = next((i for i, (f, _) in enumerate(TIERS) if p >= f), None)
        if i is not None:
            out[i] += 1
    return out


def ladder_html(r, key, names):
    """§6, safe and toss-up seats: for the three largest parties and the two sides of parliament, how many seats each wins
    in 95+ of 100 simulations, 75-95, 65-75, 35-65 and 5-35, as one bar on the 300 seats with the 151 line."""
    big = sorted(F.PARTIES, key=lambda p: -r["parties"][p]["seats"][1])[:3]
    rows = [(names[p], colour(p), r["seat_hist"][p], None) for p in big]
    for k, d in r["blocs"].items():
        known = [p for p in d["parties"] if p in r["parties"]]
        lead_ = max(known, key=lambda p: r["parties"][p]["seats"][1])
        rows.append((BLOC_NAMES[k], colour(lead_), d["hist"], d["p_151"]))
    items = []
    for title, c, h, p151 in rows:
        t = ladder(h)
        spans = "".join(f'<span style="--c:{c};flex:{n};opacity:{a}"></span>' for n, a in zip(t, TIER_ALPHA, strict=True) if n)
        spans += f'<span class="rest" style="flex:{LAW.LAWS[LAW.CURRENT]["seats"] - sum(t)}"></span>'
        words = " · ".join(f'{"" if i == 0 else "+"}{n} {w}' for i, (n, (_, w)) in enumerate(zip(t, TIERS, strict=True)) if n or i == 0)
        extra = f' · {MAJ} και πάνω: {pct(p151)}' if p151 is not None else ""
        items.append(f'<li><span class="lb"><span>{html.escape(title)}</span><small>{words}{extra}</small></span>'
                     f'<div class="seatbar mini" role="img" aria-label="{html.escape(title + ": " + words, quote=True)}">{spans}<i></i></div></li>')
    sides = "· ".join(f'{BLOC_NAMES[k].lower()}: ' + ", ".join(names[p] for p in ps if p in names) for k, ps in F.BLOCS.items())
    return (f'<h2>Ασφαλείς και αμφίρροπες έδρες</h2>'
            '<p class="note">Κάθε έδρα με τη σειρά, η 1η, η 2η και ούτω καθεξής, και σε πόσες από τις 100 προσομοιώσεις τη φτάνει '
            'το κόμμα. Ασφαλείς: 95 ή περισσότερες. Πιθανές: 75 έως 95. Με κλίση: 65 έως 75. Αμφίρροπες: 35 έως 65. '
            f'Δύσκολες: 5 έως 35. Όσο πιο αχνό το χρώμα, τόσο πιο αβέβαιη η έδρα. Η γραμμή είναι οι {MAJ}.</p>'
            f'<ul class="odds ladder">{"".join(items)}</ul>'
            '<p class="note">Οι πλευρές είναι αθροίσματα εδρών κατά τη θέση των κομμάτων στη Βουλή, όχι πρόβλεψη για το ποιος θα '
            f'συνεργαζόταν με ποιον ({sides}· η Ελπίδα και τα μικρότερα κόμματα σε καμία). Τα λάθη των κομμάτων κληρώνονται '
            'ανεξάρτητα, οπότε τα εύρη των πλευρών είναι μάλλον στενότερα από όσο θα έπρεπε.</p>')


def per_ep(r, order, names):
    seats = expected(r)
    cols = [p for p in order if seats.get(p)]
    head = "".join(f'<th class="n"><span class="sw" style="--c:{colour(p)}"></span>{html.escape(names[p])}</th>' for p in cols)
    rows = []
    for ep, e in r["eps"].items():
        means = {p: mean_seats(d) for p, d in e["dist"].items()}
        cells = "".join(f'<td class="n{" z" if means.get(p, 0) < 0.05 else ""}">'
                        f'{num(means[p]) if means.get(p, 0) >= 0.05 else "·"}</td>' for p in cols)
        cls = ' class="state"' if ep == "state" else ""
        name = html.escape(e["name"])
        page = f"{slug(MAP_ELECTION)}_{ep}.html"  # the constituency's map of the last national election
        if (OUT.parent / page).exists():
            name = f'<a href="{page}">{name}</a>'
        rows.append(f"<tr{cls}><td>{name}</td><td class=\"n\">{e['seats']}</td>{cells}</tr>")
    return ('<details><summary>Αναμενόμενες έδρες ανά εκλογική περιφέρεια</summary>'
            '<p class="note">Μέσος όρος των προσομοιώσεων, γι’ αυτό έχει δεκαδικά: 0,4 σημαίνει ότι το κόμμα παίρνει έδρα εκεί '
            'περίπου σε 4 από τις 10. «·»: κάτω από 0,05. Η κατανομή ανά περιφέρεια στηρίζεται σε υποθέσεις (βλ. παρακάτω).'
            '<span class="swipe"> Σύρε τον πίνακα πλάγια για όλα τα κόμματα.</span></p>'
            f'<div class="wrap"><table><thead><tr><th>περιφέρεια</th><th class="n">έδρες</th>{head}</tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div></details>")


def record_chart(rows, bench):
    """One row per firm on a 0-4 points scale: a dot for the miss at each election (colour = election), a diamond for the firm's
    average, a dashed tick at the average of all firms. Decoration for the table beside it, which carries the same numbers."""
    top = 4.0
    at = lambda v: f"{100 * v / top:.2f}%"
    css = {"2019": "e19", "2023/may": "e23m", "2023/june": "e23j"}
    lines = []
    for r in sorted(rows, key=lambda r: r["avg"]):
        vs = list(r["by"].values())
        dots = "".join(f'<i class="d {css[e]}" style="left:{at(v)}" title="{PR.LABEL[e]}: {num(v)}"></i>' for e, v in r["by"].items())
        span = f'<b class="rg" style="left:{at(min(vs))};width:{100 * (max(vs) - min(vs)) / top:.2f}%"></b>' if len(vs) > 1 else ""
        lines.append(f'<li><span class="lb">{html.escape(r["firm"])}</span><span class="tk">{span}'
                     f'<em class="bn" style="left:{at(bench)}"></em>{dots}<u class="m" style="left:{at(r["avg"])}"></u></span></li>')
    axis = "".join(f'<span style="left:{at(g)}">{g}</span>' for g in range(int(top) + 1))
    legend = "".join(f'<span><i class="d {css[e]}"></i>{PR.LABEL[e]}</span>' for e in PR.ELECTIONS)
    return ('<figure class="frec"><div class="fl" aria-hidden="true">' + legend + '<span><u class="m"></u>μέσος όρος εταιρείας</span>'
            f'<span><em class="bn"></em>μέσος όρος όλων ({num(bench)})</span></div>'
            f'<ul class="fr" aria-hidden="true">{"".join(lines)}<li class="ax"><span class="lb"></span><span class="tk">{axis}</span></li></ul>'
            '<figcaption>Μονάδες απόστασης από το αποτέλεσμα: κάθε κουκκίδα είναι η τελευταία δημοσκόπηση πριν από μία κάλπη. '
            'Οι ίδιοι αριθμοί είναι στον πίνακα από κάτω.</figcaption></figure>')


def record():
    """How close each firm fell at 2019, May 2023 and June 2023 (pollster_record.py), and whether weights would move the shares."""
    rows, bench = PR.table()
    may = [r["by"]["2023/may"] for r in rows if "2023/may" in r["by"]]
    other = [e for r in rows for k, e in r["by"].items() if k != "2023/may"]
    a, b = F.levels(), F.levels(weighted=True)
    shift = max(abs(b[p][0] - a[p][0]) for p in a)
    # said only while the data show it: every firm that polled before May 2023 was further off then than at any other election
    spread = (f"Είναι λίγες εκλογές, και στον Μάιο 2023 όλες οι εταιρείες που είχαν δημοσκόπηση απείχαν πολύ ({num(min(may))} έως "
              f"{num(max(may))} μονάδες), οπότε ο μέσος όρος κάθε εταιρείας εξαρτάται κυρίως από εκείνη τη μία φορά. "
              if may and other and min(may) > max(other) else
              "Είναι λίγες εκλογές, οπότε ο μέσος όρος κάθε εταιρείας στηρίζεται σε ελάχιστες μετρήσεις. ")
    tested = (f"το ποσοστό κανενός κόμματος δεν άλλαζε πάνω από {num(shift, 2)} μονάδες, οπότε δεν άξιζε να το προσθέσουμε."
              if shift < 0.1 else f"το ποσοστό κάποιου κόμματος άλλαζε έως {num(shift, 2)} μονάδες.")
    head = "".join(f'<th class="n">{PR.LABEL[e]}</th>' for e in PR.ELECTIONS)
    body_rows = []
    for r in rows:
        cells = "".join(f'<td class="n">{num(r["by"][e]) if e in r["by"] else "·"}</td>' for e in PR.ELECTIONS)
        body_rows.append(f'<tr><td>{html.escape(r["firm"])}</td><td class="n">{len(r["by"])}</td>'
                         f'<td class="n">{num(r["avg"])}</td>{cells}</tr>')
    return ('<section class="rec" aria-labelledby="rh"><h2 id="rh">Δημοσκοπήσεις και αποτέλεσμα ανά εταιρεία</h2>'
            '<p class="note">Για κάθε εταιρεία που δημοσκοπεί σήμερα: πόσο απείχε η τελευταία της δημοσκόπηση πριν την κάλπη '
            '(έως 21 ημέρες πριν) από το αποτέλεσμα, στις εκλογές του 2019, του Μαΐου 2023 και του Ιουνίου 2023. Η τιμή είναι η '
            'μέση διαφορά ανά κόμμα με 3% και πάνω, σε ποσοστιαίες μονάδες. Μικρότερη σημαίνει πιο κοντά. «·»: η εταιρεία '
            f'δεν είχε τότε δημοσκόπηση στο διάστημα αυτό. Όλες οι δημοσκοπήσεις μαζί απείχαν κατά μέσο όρο {num(bench)} μονάδες.</p>'
            f'<p class="note">{spread}Οι διαφορές '
            'ανάμεσα στις περισσότερες εταιρείες είναι μικρότερες από τις διακυμάνσεις από εκλογή σε εκλογή: ο πίνακας δείχνει πόσο '
            'κοντά έπεσαν, όχι πόσο κοντά θα πέσουν, και δεν είναι κατάταξη.</p>'
            + record_chart(rows, bench) +
            fold('Οι αριθμοί σε πίνακα', '<div class="wrap"><table class="rec"><thead><tr><th>εταιρεία</th><th class="n">εκλογές</th><th class="n">μέσος όρος</th>'
            f'{head}</tr></thead><tbody>' + "".join(body_rows) + '</tbody></table></div>') +
            '<p class="note">Στο μέσο όρο που βγάζουμε, όλες οι εταιρείες μετράνε το ίδιο. Δοκιμάσαμε να '
            f'μετράνε λίγο περισσότερο οι πιο κοντινές: {tested}</p></section>')


MODELS_JSON = HERE / "analysis" / "forecast_models.json"
METHOD_EL = {"CATI": "τηλέφωνο", "MIXED": "τηλέφωνο και διαδίκτυο", "CAWI": "διαδίκτυο", "IVR": "αυτόματες κλήσεις",
             "UNKNOWN": "μέθοδος άγνωστη"}


def _vframe(ps, names, w, hgt, fs, lo, hi, ticks, fmt, left=3.2, right=0.6, top=0.8, bottom=8.5):
    """Frame of the two dot charts: parties along the bottom (names turned 45 degrees), values up the side.
    Returns (svg head, X(i) centre of party i, Y(value), column width)."""
    L, R, T, B = left * fs, right * fs, (top if w > 400 else top + 2.5) * fs, (bottom if w > 400 else bottom + 2.5) * fs  # upright names on a phone are taller
    X = lambda i: L + (i + 0.5) * (w - L - R) / len(ps)
    Y = lambda v: T + (hgt - T - B) * (1 - (v - lo) / (hi - lo))
    out = [f'<svg viewBox="0 0 {w} {hgt}" style="font-size:{fs}px" aria-hidden="true">']
    for t in ticks:
        out.append(f'<line class="grid" x1="{L:.1f}" x2="{w - R:.1f}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
                   f'<text class="ax-l" x="{L - 0.4 * fs:.1f}" y="{Y(t) + 0.35 * fs:.1f}" text-anchor="end">{fmt(t)}</text>')
    for i, p in enumerate(ps):
        rot = -45 if w > 400 else -90  # on a phone the columns are too close for slanted names, so they stand upright
        x, y = X(i) + (0 if rot == -45 else 0.35 * fs), hgt - B + 0.9 * fs
        out.append(f'<text class="ax-l" transform="rotate({rot} {x:.1f} {y:.1f})" x="{x:.1f}" y="{y:.1f}" text-anchor="end">{html.escape(names[p])}</text>')
    return out, X, Y, (w - L - R) / len(ps)


def models_shares_svg(M, names, order, w, fs=12):
    """Three bars per party: the forecast, the share with the correction (A) and the share with the weights (B), each with its value above."""
    ps = [p for p in order if p in M["base"]["shares"]]
    ks = ("base", "coef", "weights")
    top = 5 * (int(max(M[k]["shares"][p][1] for k in ks for p in ps) / 5) + 1)
    hgt = (22 if w > 400 else 27) * fs
    out, X, Y, cw = _vframe(ps, names, w, hgt, fs, 0, top, range(0, top + 1, 5), lambda t: f"{t}%", top=4.5)
    bw, lf = min(1.1 * fs, cw * 0.3), (0.8 * fs if w > 400 else 0.9 * fs)  # on a phone only the forecast is written; the other two are in the table
    for i, p in enumerate(ps):
        c = colour(p)
        tip = f'{names[p]}: πρόβλεψη {num(M["base"]["shares"][p][1])}%, Α {num(M["coef"]["shares"][p][1])}%, Β {num(M["weights"]["shares"][p][1])}%'
        out.append(f'<g><title>{html.escape(tip)}</title>')
        for j, (k, op) in enumerate(zip(ks, (1, 0.6, 0.3))):
            v, x = M[k]["shares"][p][1], X(i) + (j - 1) * bw * 1.05
            out.append(f'<rect x="{x - bw / 2:.1f}" y="{Y(v):.1f}" width="{bw:.1f}" height="{Y(0) - Y(v):.1f}" style="fill:{c};opacity:{op}"/>'
                       + (f'<text class="ax-l" style="fill:var(--ink);font-size:{lf:.1f}px" transform="rotate(-90 {x + 0.33 * lf:.1f} {Y(v) - 0.4 * fs:.1f})" '
                          f'x="{x + 0.33 * lf:.1f}" y="{Y(v) - 0.4 * fs:.1f}">{num(v)}%</text>' if w > 400 or j == 0 else ""))
        out.append("</g>")
    return "".join(out) + "</svg>"


def models_coef_svg(d, shown, names, w, fs=12):
    """Strip chart: one column per party, one dot per firm at the party's coefficient (1 = the firm was right on average)."""
    firms = sorted(d["coef"][shown[0]])
    vals = [d["coef"][p][f] for p in shown for f in firms]
    lo, hi = min(min(vals), 0.9), max(max(vals), 1.1)
    lo, hi = int(lo * 10) / 10, -int(-hi * 10) / 10
    ticks = [round(lo + 0.1 * k, 1) for k in range(int(round((hi - lo) / 0.1)) + 1)]
    out, X, Y, cw = _vframe(shown, names, w, (20 if w > 400 else 25) * fs, fs, lo, hi, ticks, num)
    out.append(f'<line class="m151" x1="{X(0) - cw / 2:.1f}" x2="{X(len(shown) - 1) + cw / 2:.1f}" y1="{Y(1):.1f}" y2="{Y(1):.1f}"/>')
    for i, p in enumerate(shown):
        for k, f in enumerate(firms):
            v = d["coef"][p][f]
            dx = ((k % 3) - 1) * min(0.45 * fs, cw / 4)  # three lanes, so firms with the same value do not hide each other
            out.append(f'<circle cx="{X(i) + dx:.1f}" cy="{Y(v):.1f}" r="{0.3 * fs:.1f}" style="fill:{colour(p)};opacity:.6"><title>'
                       f'{html.escape(names[p])}, {html.escape(f.split("|")[0])}: {num(v, 2)}</title></circle>')
    return "".join(out) + "</svg>"


def models_prob_svg(M, probs, w, fs=12):
    """Three bars per question (forecast, A, B), each as long as its probability."""
    left, right, top, bottom = 0.6 * fs, 4 * fs, 0.2 * fs, 0.4 * fs
    bh, gap, head = 0.9 * fs, 0.2 * fs, 1.5 * fs
    grp = head + 3 * bh + 2 * gap + 0.9 * fs
    hgt = top + grp * len(probs) + bottom
    X = lambda v: left + v * (w - left - right)
    out = [f'<svg viewBox="0 0 {w} {hgt:.0f}" style="font-size:{fs}px" aria-hidden="true">']
    for t in (0, 0.5, 1):
        out.append(f'<line class="grid" x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{top:.1f}" y2="{hgt - bottom:.1f}"/>')
    for i, (key, lab) in enumerate(probs):
        y0 = top + grp * i
        out.append(f'<text style="fill:var(--ink)" x="{left:.1f}" y="{y0 + 1.1 * fs:.1f}">{html.escape(lab)}</text>')
        for j, (k, col) in enumerate((("base", "var(--mute)"), ("coef", "var(--ink-2)"), ("weights", "var(--ink)"))):
            v, y = M[k]["rates"][key], y0 + head + j * (bh + gap)
            out.append(f'<rect x="{X(0):.1f}" y="{y:.1f}" width="{max(X(v) - X(0), 1):.1f}" height="{bh:.1f}" rx="2" style="fill:{col}"/>'
                       f'<text class="ax-l" x="{X(v) + 0.4 * fs:.1f}" y="{y + 0.78 * fs:.1f}">{pct(v)}</text>')
    return "".join(out) + "</svg>"


def two_sizes(fn, cap, *a):
    """A figure drawn twice, wide for a desktop and narrow for a phone (the template shows one of them)."""
    return f'<figure><div class="wide">{fn(*a, 640)}</div><div class="narrow">{fn(*a, 360)}</div><figcaption>{cap}</figcaption></figure>'


MODEL_KEY = ('<ul class="legend"><li><i style="--c:var(--ink)"></i>πρόβλεψη</li><li><i style="--c:var(--ink);opacity:.6"></i>Α. διόρθωση</li>'
             '<li><i style="--c:var(--ink);opacity:.3"></i>Β. βάρη</li></ul>')
PROB_KEY = ('<ul class="legend"><li><i style="--c:var(--mute)"></i>πρόβλεψη</li><li><i style="--c:var(--ink-2)"></i>Α. διόρθωση</li>'
            '<li><i style="--c:var(--ink)"></i>Β. βάρη</li></ul>')


def models(names, order):
    """Chapter of the two other forecasts (forecast_models.py): polls corrected by each firm's, method's and party's past
    ballot / poll coefficient (A), and polls weighted by how close that firm and method fell for that party (B), beside the
    forecast. Empty if the file is missing."""
    if not MODELS_JSON.exists():
        return ""
    d = json.loads(MODELS_JSON.read_text(encoding="utf-8"))
    M = d["models"]
    keys = ("base", "coef", "weights")
    head = ('<thead><tr><th>κόμμα</th><th class="n">πρόβλεψη</th><th class="n">Α. διόρθωση</th>'
            '<th class="n">Β. βάρη</th></tr></thead>')
    span = lambda s: f'{num(s[1])}% <span class="pf">({num(s[0])}–{num(s[2])})</span>'
    rows = "".join(f'<tr><td>{html.escape(names[p])}</td>' + "".join(f'<td class="n">{span(M[k]["shares"][p])}</td>' for k in keys)
                   + "</tr>" for p in order if p in M["base"]["shares"])
    seat_rows = "".join(f'<tr><td>{html.escape(names[p])}</td>' + "".join(f'<td class="n">{M[k]["seats"].get(p, 0)}</td>' for k in keys)
                        + "</tr>" for p in order if any(M[k]["seats"].get(p) for k in keys))
    probs = (("p_nd_majority", "ΝΔ μόνη της 151 έδρες"), ("p_nd_pasok_151", "ΝΔ και ΠΑΣΟΚ μαζί 151"),
             ("p_nd_elas_151", "ΝΔ και ΕΛΑΣ μαζί 151"), ("p_bonus", "πρώτο κόμμα με 25% και πάνω (μπόνους)"))
    prob_rows = "".join(f'<tr><td>{lab}</td>' + "".join(f'<td class="n">{pct(M[k]["rates"][key])}</td>' for k in keys) + "</tr>"
                        for key, lab in probs)
    shown = [p for p in order if p in d["coef"] and any(abs(v - 1) > 0.005 for v in d["coef"][p].values())][:9]
    firms = sorted(next(iter(d["coef"].values())))
    k_rows = "".join(f'<tr><td>{html.escape(f.split("|")[0])} <span class="pf">({METHOD_EL[f.split("|")[1]]})</span></td>'
                     + "".join(f'<td class="n">{num(d["coef"][p][f], 2)} / {num(d["weight"][p][f], 2)}</td>' for p in shown) + "</tr>"
                     for f in firms)
    # which parties the correction moves by half a point or more, said from the data so the words follow the polls
    delta = {p: M["coef"]["shares"][p][1] - M["base"]["shares"][p][1] for p in order if p in M["base"]["shares"]}
    nm = lambda ps: ", ".join(names[p] for p in ps[:-1]) + " και " + names[ps[-1]] if len(ps) > 1 else names[ps[0]]
    up, down = [p for p in delta if delta[p] >= 0.5], [p for p in delta if delta[p] <= -0.5]
    moved = "".join(f"Η διόρθωση {verb} {'τα κόμματα' if len(ps) > 1 else 'το κόμμα'} {nm(ps)} μισή μονάδα ή περισσότερο. "
                    for verb, ps in (("ανεβάζει", up), ("κατεβάζει", down)) if ps)
    k_head = "<thead><tr><th>εταιρεία (μέθοδος)</th>" + "".join(f'<th class="n">{html.escape(names[p])}</th>' for p in shown) + "</tr></thead>"
    return ('<h2>Δύο άλλοι τρόποι να μετρήσουμε τις δημοσκοπήσεις</h2>'
            '<p class="note">Η πρόβλεψη βγαίνει από τον μέσο όρο των δημοσκοπήσεων και κάθε δημοσκόπηση μετράει το ίδιο. Εδώ '
            'δοκιμάζουμε δύο άλλους τρόπους με τα ίδια δεδομένα. Και οι δύο στηρίζονται στο πόσο απείχαν οι δημοσκοπήσεις κάθε '
            'εταιρείας από το αποτέλεσμα στις εθνικές εκλογές από το 2007 έως το 2023, χωριστά για κάθε κόμμα και για κάθε μέθοδο '
            'έρευνας: με τηλέφωνο, με τηλέφωνο και διαδίκτυο μαζί, ή μόνο με διαδίκτυο.</p>'
            '<p class="note"><b>Α. Διόρθωση.</b> Κάθε δημοσκόπηση πολλαπλασιάζεται με έναν συντελεστή: το αποτέλεσμα που πήρε το '
            'κόμμα διά το ποσοστό που του έδινε η εταιρεία με την ίδια μέθοδο. Συντελεστής 1,10 σημαίνει ότι το κόμμα πήρε στην '
            'κάλπη 10% περισσότερο από όσο έδειχνε η εταιρεία. <b>Β. Βάρη.</b> Οι αριθμοί μένουν όπως δημοσιεύτηκαν, αλλά στον μέσο όρο '
            'μετράνε περισσότερο οι εταιρείες που για εκείνο το κόμμα έπεσαν πιο κοντά από τις άλλες στις ίδιες εκλογές. Βάρος 2 '
            'σημαίνει ότι η δημοσκόπηση μετράει διπλά, βάρος 0,5 μισή.</p>'
            '<h3>Ποσοστά</h3><p class="note">Το πιθανότερο ποσοστό και, σε παρένθεση, το εύρος όπου πέφτει 8 φορές στις 10, '
            'για εκλογές σήμερα.</p>'
            + two_sizes(models_shares_svg, 'Κάθε κόμμα έχει τρεις στήλες: την πρόβλεψη, το ποσοστό με τη διόρθωση και το ποσοστό με τα βάρη. Πάνω από τις στήλες είναι το ποσοστό (στο κινητό μόνο της πρόβλεψης).', M, names, [p for p in order if p in M["base"]["shares"]])
            + MODEL_KEY
            + f'<div class="wrap"><table>{head}<tbody>{rows}</tbody></table></div>'
            '<h3>Έδρες και πιθανότητες</h3>' + two_sizes(models_prob_svg, 'Η πιθανότητα κάθε ενδεχομένου, για εκλογές σήμερα.', M, probs) + PROB_KEY
            + f'<div class="wrap"><table>{head}<tbody>{seat_rows}{prob_rows}</tbody></table></div>'
            f'<p class="note">Οι διαφορές από την πρόβλεψη είναι μικρές μπροστά στα εύρη. {moved}Η μέθοδος έρευνας αλλάζει '
            'τους συντελεστές λίγο: για τα μεγάλα κόμματα έως 2% πάνω ή κάτω, για μερικά μικρότερα έως 8%. Τα κόμματα '
            'χωρίς προηγούμενες εκλογές (ΕΛΑΣ, Ελπίδα, Συμμαχία Ελλήνων) μένουν όπως στην πρόβλεψη. Η διόρθωση φέρνει μαζί και λάθη '
            'που έκαναν όλες οι εταιρείες μαζί σε μία εκλογή και δεν είναι βέβαιο ότι θα ξαναγίνουν. Δεν μετράμε τις ευρωεκλογές: '
            'και στις τρεις (2014, 2019, 2024) το κόμμα της κυβέρνησης πήρε λιγότερα από τις δημοσκοπήσεις, ενώ στις εθνικές '
            'εκλογές αυτό δεν έγινε σταθερά. Οι έδρες είναι οι εθνικές, χωρίς κατανομή στις περιφέρειες.</p>'
            + '<h3>Πόσο έπεσαν έξω οι εταιρείες</h3>' + two_sizes(models_coef_svg, 'Κάθε τελεία είναι μια εταιρεία. Στο 1 η εταιρεία έπεσε μέσα κατά μέσο όρο· πάνω από το 1 το κόμμα πήρε στην κάλπη περισσότερα από όσα έδειχνε, κάτω από το 1 λιγότερα.', d, shown, names)
            + fold('Συντελεστής / βάρος κάθε εταιρείας που δημοσκοπεί σήμερα',
                   '<p class="note">Με τη μέθοδο της τελευταίας της δημοσκόπησης. Πρώτος αριθμός ο συντελεστής της διόρθωσης, δεύτερος '
                   'το βάρος.</p>' f'<div class="wrap"><table>{k_head}<tbody>{k_rows}</tbody></table></div>'))


SAM_JSON = HERE / "analysis" / "samaras.json"


def dash(a, b):
    """'1,0–7,0%' from '1,0%' and '7,0%'; both kept whole when either is '<0,1%' or '>99,9%', or when they are equal."""
    return a if a == b else f"{a[:-1]}–{b}" if a[-1] == b[-1] == "%" and a[0].isdigit() and b[0].isdigit() else f"{a}–{b}"


def samaras(names):
    """Scenario chapter from analysis/samaras.json (samaras_scenarios.py): a new party of Antonis Samaras at exactly the share
    picked, 4 to 14%, elections today. One panel per level, shown for the checked radio chip (#sam=<level> in the address): the
    answer first, the seats and who reaches 151 beside the forecast without it, the seat table. The two assumptions follow in
    words with how much the alternatives move the result. Empty if the file is missing or once the party is in the forecast
    itself (forecast.NEW: it has polls), so a stale scenario never stands beside the real figures."""
    if not SAM_JSON.exists() or "SAM" in names:
        return "", ""
    d = json.loads(SAM_JSON.read_text(encoding="utf-8"))
    nm = names | {"SAM": "κόμμα Σαμαρά", F.OTHER: "μικρότερα κόμματα"}
    B, levels, alt = d["base"], d["levels"], d["alt_levels"]
    by = {L: d["by_level"][str(L)] for L in levels}
    join = lambda ps: nm[ps[0]] if len(ps) == 1 else ", ".join(nm[p] for p in ps[:-1]) + " και " + nm[ps[-1]]
    co = {L: {tuple(c): hit for c, _, hit in by[L]["coalitions"]} for L in levels}
    top = lambda c: max(co[L].get(c, 0) for L in levels)
    # rows of "who reaches 151": the fixed ones, then every three-party group that gets there in >= 20% at some level
    groups = [(("ND",), "nd"), (("ND", "PASOK"), "nd_pasok"), (("ND", "ELAS"), "nd_elas"), (("ND", "PASOK", "ELAS"), "nd_pasok_elas"),
              (("ND", "SAM"), "nd_sam")]
    fixed = {g for g, _ in groups}
    for c in sorted({c for L in levels for c in co[L] if c not in fixed and top(c) >= 0.2}, key=lambda c: -top(c)):
        groups.append((c, c))
    val = lambda L, k: by[L][k] if isinstance(k, str) else co[L].get(k, 0)
    base = lambda k: B[k] if isinstance(k, str) and k != "nd_sam" else None  # no baseline for a coalition with the Samaras party
    seated = [p for p in ("ND", "SAM", *(p for p in B["seats"] if p not in ("ND", "SAM")))
              if any(s["seats"].get(p, [0, 0, 0])[1] for s in (B, *by.values()))]
    first = 10 if 10 in levels else levels[0]
    chips = "".join(f'<label><input type="radio" name="sam" id="sam-{L}"{" checked" if L == first else ""}>{L}%</label>' for L in levels)
    panels = []
    for L in levels:
        s = by[L]
        rows = []
        for ps, k in groups:
            v, b0 = val(L, k), base(k)
            was = f"χωρίς κόμμα Σαμαρά: {pct(b0)}" if b0 is not None else "δεν υπάρχει χωρίς κόμμα Σαμαρά"
            tick = f'<em style="left:{100 * b0:.1f}%"></em>' if b0 is not None else ""
            rows.append(f'<li><span class="lb"><span>{html.escape(join(ps))}</span><small>{was}</small></span>'
                        f'<span class="pb" aria-hidden="true"><i style="width:{100 * v:.1f}%"></i>{tick}</span><b>{pct(v)}</b></li>')
        ps_best, _, v_best = max(((ps, k, val(L, k)) for ps, k in groups if len(ps) > 1), key=lambda x: x[2])
        no_bonus = s["bonus"] < 0.5 <= B["bonus"]
        lead = (f'Στο {L}% η ΝΔ πέφτει από {num(B["share"]["ND"][1])}% σε {num(s["share"]["ND"][1])}% και από {B["seats"]["ND"][1]} '
                f'σε {s["seats"]["ND"][1]} έδρες' + (", κυρίως γιατί κάτω από 25% χάνει το μπόνους" if no_bonus else "")
                + f'. Η πιο πιθανή πλειοψηφία: {html.escape(join(ps_best))}, σε {pct(v_best)} των προσομοιώσεων.')
        sam_lo, sam_mid, sam_hi = s["seats"]["SAM"]
        stat = lambda big, what, small: f'<p><b>{big}</b><span class="t"><strong>{what}</strong><small>{small}</small></span></p>'
        hero = ('<div class="hero">'
                + stat(s["seats"]["ND"][1], "έδρες της ΝΔ", f'χωρίς κόμμα Σαμαρά: {B["seats"]["ND"][1]}')
                + stat(sam_mid, "έδρες του κόμματος Σαμαρά", f"στις 8 από τις 10: {sam_lo}–{sam_hi}")
                + stat(pct(s["bonus"]), "πιθανότητα μπόνους", f'χωρίς κόμμα Σαμαρά: {pct(B["bonus"])}') + "</div>")
        srows = "".join(f'<tr><th scope="row"><span class="sw" style="--c:{colour(p)}"></span>{html.escape(nm[p])}</th>'
                        f'<td class="n">{"—" if p == "SAM" else seats_range(B["seats"][p])}</td><td class="n">{seats_range(s["seats"][p])}</td></tr>'
                        for p in seated if s["seats"].get(p, [0, 0, 0])[1] or B["seats"].get(p, [0, 0, 0])[1])
        panels.append(f'<div class="slv sl-{L}"><p class="lead">{lead}</p>{hero}'
                      f'<h3>Ποιοι φτάνουν τις {MAJ} έδρες</h3>'
                      f'<ul class="po">{"".join(rows)}</ul>'
                      f'<p class="note">Ποσοστό των προσομοιώσεων όπου τα κόμματα μαζί έχουν {MAJ} έδρες ή περισσότερες. Η γραμμή στη μπάρα '
                      'είναι το ποσοστό χωρίς κόμμα Σαμαρά. Είναι αθροίσματα εδρών, όχι πρόβλεψη για το ποια κυβέρνηση θα σχηματιστεί.</p>'
                      f'<details><summary>Οι έδρες κάθε κόμματος στο {L}%</summary><div class="wrap"><table><thead><tr><th></th>'
                      f'<th class="n">χωρίς</th><th class="n">{L}%</th></tr></thead><tbody>{srows}</tbody></table></div>'
                      '<p class="note">Μεσαία τιμή και, σε παρένθεση, το εύρος όπου πέφτουν στις 8 από τις 10 προσομοιώσεις. «Χωρίς»: '
                      'η πρόβλεψη της σελίδας, χωρίς κόμμα Σαμαρά.</p></details></div>')
    css = ".slv{display:none}" + "".join(f"main:has(#sam-{L}:checked) .sl-{L}{{display:block}}" for L in levels)

    from_ = lambda sp: ", ".join(f"{nm[p]} {num(100 * w, 0)}%" for p, w in sp.items())
    lo_hi = f"{alt[0]}–{alt[-1]}%"
    alts = []
    for k, v in list(d["splits"].items())[1:]:  # the first is the main split, the one the panels show
        ss = [v[str(L)] for L in alt]
        rng = lambda f, fmt=pct: dash(fmt(min(f(s) for s in ss)), fmt(max(f(s) for s in ss)))
        alts.append(f"<b>{html.escape(k)}</b> ({from_(v['split'])}): "
                    f"η ΝΔ {rng(lambda s: s['seats']['ND'][1], str)} έδρες, ΝΔ και ΕΛΑΣ στις {MAJ} σε {rng(lambda s: s['nd_elas'])}, "
                    f"μπόνους σε {rng(lambda s: s['bonus'])}")
    geo = [g for v in d["geo"].values() for g in v.values()]
    moved = max(g["moved_sam"] for g in geo)
    differ, worst = max(g["differ"] for g in geo), max(g["max_diff"] for g in geo)
    return css, ('<section aria-labelledby="sh"><h2 id="sh">Σενάριο σήμερα: κόμμα Σαμαρά από 4% έως 14%</h2>'
            '<p class="note">Τι θα γινόταν αν ένα νέο κόμμα του Αντώνη Σαμαρά έπαιρνε ακριβώς το ποσοστό που διαλέγεις. '
            'Δεν λέμε ότι θα το πάρει: το κόμμα δεν έχει δημοσκοπήσεις ούτε εκλογές πίσω του. Είναι οι ίδιες '
            f'{thousands(d["n"])} προσομοιώσεις με παραπάνω, όπου οι ψήφοι του αφαιρούνται από τα άλλα κόμματα. Σενάριο, όχι πρόβλεψη.</p>'
            f'<fieldset class="pick chips"><legend>Κόμμα Σαμαρά:</legend>{chips}</fieldset>' + "".join(panels)
            + '<details><summary>Οι υποθέσεις και πόσο αλλάζουν τα αποτελέσματα</summary>'
            f'<p class="note"><b>Από πού έρχονται οι ψήφοι του.</b> Υπόθεση: από τις ψήφους του, {from_(d["main_split"])}. Από αυτό εξαρτάται κυρίως '
            f'πόσες έδρες κρατά η ΝΔ. Με άλλες υποθέσεις, στο {lo_hi}: ' + "· ".join(alts) + ".</p>"
            '<p class="note"><b>Πού είναι δυνατό.</b> Υπόθεση: όπου ήταν δυνατή η ΝΔ τον Ιούνιο 2023. Δοκιμάσαμε και τρεις άλλες: '
            'το ίδιο με διπλάσιο ποσοστό στη Μεσσηνία, την εκλογική περιφέρεια του Σαμαρά· όπου ήταν δυνατή η Ελληνική Λύση στις '
            'Ευρωεκλογές 2024· ίδιο ποσοστό παντού. Οι έδρες '
            'κάθε κόμματος στο σύνολο της χώρας βγαίνουν από τα εθνικά ποσοστά, άρα σχεδόν δεν αλλάζουν '
            + (f'(διαφορά {worst} έδρας σε έως {differ} από τις {thousands(d["n"])} προσομοιώσεις). ' if differ else
               f'(καμία διαφορά στις {thousands(d["n"])} προσομοιώσεις). ')
            + 'Αλλάζει μόνο σε ποια περιφέρεια '
            f'εκλέγονται, έως περίπου {num(moved, 0)} έδρες του κόμματος Σαμαρά.</p></details></section>')

TREND_JSON = HERE / "analysis" / "forecast_trend.json"
THERMO_REF = 42  # days back for the change of the 3% thermometer
THERMO_MIN = 0.05  # a change in the chance of passing 3% of at least this counts as a move


def line_svg(pts, series, w, hgt, fs, labels=True):
    """SVG lines over the dates of pts, y from 0 to 100%: series [(label, colour, dashed, [value 0-1 per point])], each
    labelled at its right end (labels pushed apart so they do not overlap); labels=False: no labels, for a legend below."""
    ds = [date.fromisoformat(p["date"]) for p in pts]
    span = max((ds[-1] - ds[0]).days, 1)
    left, right, tp, bottom = 2.6 * fs, (9.5 if labels else 0.6) * fs, 0.8 * fs, 2 * fs
    X = lambda d: left + (d - ds[0]).days / span * (w - left - right)
    Y = lambda v: tp + (hgt - tp - bottom) * (1 - v)
    out = [f'<svg viewBox="0 0 {w} {hgt}" style="font-size:{fs}px" aria-hidden="true">']
    for v in (0, .25, .5, .75, 1):
        out.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                   f'<text class="ax-l" x="{left - 0.4 * fs}" y="{Y(v) + 0.35 * fs:.1f}" text-anchor="end">{round(100 * v)}%</text>')
    m = date(ds[0].year, ds[0].month, 1)
    while m <= ds[-1]:
        if m >= ds[0]:
            out.append(f'<text class="ax-l" x="{X(m):.1f}" y="{hgt - bottom + 1.3 * fs:.1f}" text-anchor="middle">{MONTHS[m.month - 1]}</text>')
        m = date(m.year + m.month // 12, m.month % 12 + 1, 1)
    ends = []
    for label, c, dashed, ys in series:
        dash_ = ";stroke-dasharray:5 4" if dashed else ""
        out.append(f'<polyline points="{" ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in zip(ds, ys, strict=True))}" '
                   f'style="fill:none;stroke:{c};stroke-width:2;stroke-linejoin:round{dash_}"/>')
        ends.append([Y(ys[-1]), label, c, ys[-1]])
    ends.sort()
    for i in range(1, len(ends)):  # push labels down so each sits at least one line below the one above
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 1.15 * fs)
    for y, label, c, v in ends if labels else ():
        out.append(f'<text x="{w - right + 0.5 * fs:.1f}" y="{y + 0.35 * fs:.1f}" style="fill:var(--ink)">'
                   f'<tspan style="fill:{c}">■</tspan> {html.escape(label)} {pct(v)}</text>')
    return "".join(out) + "</svg>"


def trend_html(names):
    """§1, the forecast over time (forecast_trend.py): majorities and the bonus, second place, ND at 30%, and the
    thermometer of the 3%. Elections today only; empty when forecast_trend.json is missing."""
    if not TREND_JSON.exists():
        return ""
    t = json.loads(TREND_JSON.read_text(encoding="utf-8"))
    pts, last = t["points"], t["points"][-1]
    if len(pts) < 2:
        return ""
    rate = lambda k: [p["rates"][k] for p in pts]
    main_ = [(f"ΝΔ μόνη {MAJ}", colour("ND"), False, rate("p_nd_majority")),
             (f"ΝΔ και ΠΑΣΟΚ {MAJ}", colour("PASOK"), False, rate("p_nd_pasok_151")),
             (f"ΝΔ και ΕΛΑΣ {MAJ}", colour("ELAS"), False, rate("p_nd_elas_151")),
             ("χωρίς μπόνους", "var(--ink-2)", True, [1 - v for v in rate("p_bonus")])]
    pair = sorted(last["p_second"], key=lambda p: -last["p_second"][p])[:2]
    second = [(f"{names[p]} δεύτερο", colour(p), False, [x["p_second"].get(p, 0) for x in pts]) for p in pair]
    second.append(("ΝΔ 30% και πάνω", colour("ND"), True, rate("p_nd_30")))
    key_ = lambda s: "".join(f'<li><i style="--c:{c}"></i>{html.escape(label)} <b>{pct(ys[-1])}</b></li>' for label, c, _, ys in s)
    fig = lambda s, cap: (f'<figure><div class="wide">{line_svg(pts, s, 640, 220, 12)}</div>'
                          f'<div class="narrow">{line_svg(pts, s, 360, 220, 12, labels=False)}<ul class="legend">{key_(s)}</ul></div>'
                          f'<figcaption>{cap}</figcaption></figure>')
    # the 3% thermometer: parties whose chance of passing was between 5 and 95 in 100 on some day
    ref_day = date.fromisoformat(last["date"]) - timedelta(THERMO_REF)
    ref = next((p for p in reversed(pts) if date.fromisoformat(p["date"]) <= ref_day), pts[0])
    edge = [p for p in last["p_in"] if any(0.05 < x["p_in"].get(p, 0) < 0.95 for x in pts)]
    rows = []
    for p in sorted(edge, key=lambda p: -last["p_in"][p]):
        now, then = last["p_in"][p], ref["p_in"].get(p)
        move = ("—" if then is None else "ανεβαίνει" if now - then >= THERMO_MIN else "πέφτει" if then - now >= THERMO_MIN
                else "περίπου ίδιο")
        rows.append(f'<tr><td><span class="sw" style="--c:{colour(p)}"></span>{html.escape(names[p])}</td>'
                    f'<td class="n">{"—" if then is None else pct(then)}</td><td class="n">{pct(now)}</td><td>{move}</td></tr>')
    thermo = ('<h3 class="sub">Το όριο του 3%: ποιος πλησιάζει</h3>'
              f'<div class="wrap"><table><thead><tr><th>κόμμα</th><th class="n">περνά, {day(ref["date"])}</th>'
              f'<th class="n">περνά, {day(last["date"])}</th><th>πορεία</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
              f'<p class="note">«Ανεβαίνει» ή «πέφτει»: αλλαγή {round(100 * THERMO_MIN)} μονάδων και πάνω στις {THERMO_REF // 7} '
              'εβδομάδες. «—»: δεν είχε ακόμη αρκετές δημοσκοπήσεις για να μπει στην πρόβλεψη.</p>' if rows else "")
    return ('<div class="h0"><h2>Πώς άλλαξε η πρόβλεψη</h2>'
            f'<p class="note">Η ίδια πρόβλεψη, με τη σημερινή μέθοδο και μόνο τις δημοσκοπήσεις που είχαν τελειώσει κάθε '
            f'ημερομηνία, ανά {t["step"]} ημέρες από τις {day(t["start"])}, όταν η {names[t["anchor"]]} είχε αρκετές '
            'δημοσκοπήσεις για να μπει. Κόμμα με λίγες δημοσκοπήσεις ως τότε μετρά στα «άλλα».</p>'
            + fig(main_, 'Σε πόσες από τις 100 προσομοιώσεις, κάθε ημερομηνία. Διακεκομμένη: κανένα κόμμα στο 25%, άρα χωρίς μπόνους.')
            + fig(second, 'Ποιο κόμμα βγαίνει δεύτερο, και πόσο συχνά η ΝΔ φτάνει το 30%.')
            + thermo + "</div>")


def ep_geometries():
    """{constituency id: [municipal unit geometries]}: the units of its polling stations in June 2023, matched by name as
    build.py does; plus the units in no constituency (Mount Athos) under None, drawn blank."""
    units = boundaries()[0]
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    dens = {}
    for ep, den in db.execute("SELECT DISTINCT ep_id, den_descr FROM station WHERE election=? AND den_descr<>''",
                              (MAP_ELECTION,)):
        dens.setdefault(str(ep), set()).add(den)
    out = {ep: [u["geometry"] for u in match_units(sorted(names), units).values()] for ep, names in dens.items()}
    owned = {id(g) for gs in out.values() for g in gs}
    out[None] = [u["geometry"] for u in units if id(u["geometry"]) not in owned]
    return out


MAP_BINS = ((0.5, 40), (1, 58), (2, 76), (float("inf"), 95))  # mean seats below -> % of the party colour
HELD = TIERS[2][0]  # a party holds its k-th seat of a constituency when it wins it in 65+ of 100 simulations ("με κλίση")
TOSS_BINS = ((2, 40), (3, 58), (5, 76), (float("inf"), 95))  # toss-up seats below -> % of the ink


def at_least(dist):
    """{k: P(seats >= k)} for k = 1.. from {seats: share} (string keys, as in forecast.json)."""
    d = {int(k): f for k, f in dist.items()}
    return {k: sum(f for s, f in d.items() if s >= k) for k in range(1, max(d, default=0) + 1)}


def contested(e, parties):
    """A constituency's toss-up seats: its seats less the seats each party holds (HELD). Contenders: each party's next seat
    when it wins it in 5 to 65 of 100 simulations. Edge: parties near the 3% (in parliament in 5 to 95 of 100) that win a
    seat there in 5+ of 100, so the seat also turns on whether they pass the threshold."""
    held, cont, edge = 0, [], []
    for p, dist in e["dist"].items():
        ge = at_least(dist)
        h = max((k for k, q in ge.items() if q >= HELD), default=0)
        held += h
        if ge.get(h + 1, 0) >= TIERS[-1][0]:
            cont.append((p, h + 1, ge[h + 1]))
        if 0.05 < parties.get(p, {}).get("p_in", 1) < 0.95 and ge.get(1, 0) >= 0.05:
            edge.append(p)
    return {"n": max(0, e["seats"] - held), "cont": sorted(cont, key=lambda c: -c[2]), "edge": edge}


def toss_words(t, names):
    """The contenders and the parties near 3% of one constituency, in words."""
    out = ", ".join(f"{names[p]} {k}η έδρα {pct(q)}" for p, k, q in t["cont"][:4])
    out = f"διεκδικούν: {out}" if out else ""
    if t["edge"]:
        out += ("· " if out else "") + "κρίνεται και από το αν περάσει το 3%: " + ", ".join(names[p] for p in t["edge"])
    return out


def most_toss(toss, eps, names):
    """The five constituencies with the most toss-up seats, with their contenders: the map's answer for a screen reader
    and for a reader who does not tap the map."""
    top = sorted((ep for ep in eps if toss[ep]["n"]), key=lambda ep: (-toss[ep]["n"], eps[ep]["name"]))[:5]
    if not top:
        return ""
    items = "".join(f'<li><b>{html.escape(eps[ep]["name"])}</b>: {toss[ep]["n"]} από {eps[ep]["seats"]} έδρες'
                    + (f' <small>({html.escape(toss_words(toss[ep], names))})</small>' if toss_words(toss[ep], names) else "")
                    + "</li>" for ep in top)
    total = sum(t["n"] for t in toss.values())
    return (f'<h3 class="sub">Οι περισσότερες αμφίρροπες έδρες</h3><p class="note">Σε όλες τις περιφέρειες: {total} από τις {sum(e["seats"] for e in eps.values())}.'
            f'</p><ol class="toss5">{items}</ol>')


def ep_map(data, order, names):
    """Expected seats per constituency on a map of Greece with Attica enlarged beside it: for the party picked (radio
    buttons), its mean seats in each constituency, in four steps of its colour (the legend takes the same colour). Each
    region carries the class of its step per horizon and party; generated CSS lights the classes of the checked pair. A
    tap, focus or the constituency list shows every party's seats in that constituency under the country map (between it
    and the inset on a phone) and marks the constituency in both figures. Attica's constituencies take keyboard focus only
    in the inset, so each constituency is one tab stop."""
    geoms = ep_geometries()
    hz = data["horizons"]
    eps = {ep: e for ep, e in hz["0"]["eps"].items() if ep != "state"}
    attica = [ep for ep, e in eps.items() if any(w in e["name"] for w in ("Αθην", "Πειρ", "Αττικ"))]
    means = {key: {ep: {p: mean_seats(d) for p, d in r["eps"][ep]["dist"].items()} for ep in eps} for key, r in hz.items()}
    total = {p: sum(m.get(p, 0) for m in means["0"].values()) for p in names}
    picks = [p for p in sorted(total, key=lambda p: -total[p]) if total[p] >= 1]
    toss = {key: {ep: contested(r["eps"][ep], r["parties"]) for ep in eps} for key, r in hz.items()}

    def tstep(ep, key):
        n = toss[key][ep]["n"]
        return 0 if n == 0 else next(i for i, (hi, _) in enumerate(TOSS_BINS, 1) if n < hi)

    def step(ep, key, p):
        m = means[key][ep].get(p, 0)
        return 0 if m < 0.05 else next(i for i, (hi, _) in enumerate(MAP_BINS, 1) if m < hi)

    def detail(ep, key):
        m = sorted(((p, v) for p, v in means[key][ep].items() if v >= 0.05), key=lambda pv: -pv[1])
        t = toss[key][ep]
        words = toss_words(t, names)
        return (f'{eps[ep]["name"]}, {eps[ep]["seats"]} έδρες: ' + " · ".join(f"{names[p]} {num(v)}" for p, v in m)
                + f'. Αμφίρροπες: {t["n"]}' + (f" ({words})" if words else "") + ".")

    def svg(shown, size, label, box=None, focus=()):
        """`box` (lon, lat, lon, lat): frame only the units inside it; the rest is drawn but falls outside the view."""
        inside = [g for ep in shown for g in geoms[ep]
                  if box is None or box[0] < centroid(g)[0] < box[2] and box[1] < centroid(g)[1] < box[3]]
        to_xy, w, h = frame(inside, size)
        out = []
        for ep in shown:
            d = path(boundary(geoms[ep]), to_xy, tol=0.5, min_area=0.6)
            if not d:
                continue
            if ep is None:
                out.append(f'<path class="none" d="{d}"/>')
                continue
            cls = " ".join([*(f"h{key}-{p}-{step(ep, key, p)}" for key in hz for p in picks),
                            *(f"h{key}-toss-{tstep(ep, key)}" for key in hz)])
            data_ = "".join(f' data-d{key}="{html.escape(detail(ep, key), quote=True)}"' for key in hz)
            tab = ' tabindex="0"' if ep in focus else ""
            out.append(f'<path class="{cls}" d="{d}" data-ep="{ep}"{tab} role="img" aria-label="{html.escape(eps[ep]["name"], quote=True)}"'
                       f'{data_}/>')
        return f'<svg viewBox="0 0 {w} {h}" role="group" aria-label="{label}">' + "".join(out) + "</svg>"

    country = svg([*(ep for ep in eps), None], 440, "Χάρτης της Ελλάδας ανά εκλογική περιφέρεια",
                  focus=[ep for ep in eps if ep not in attica])
    zoom = svg(attica, 260, "Αττική σε μεγέθυνση", box=(22.8, 37.6, 24.2, 38.4), focus=attica)  # without Kythira and the far islands
    chips = "".join(f'<label><input type="radio" name="m" id="m-{p}"{" checked" if i == 0 else ""}>'
                    f'<i style="--c:{colour(p)}"></i>{html.escape(names[p])}</label>' for i, p in enumerate(picks))
    chips += '<label><input type="radio" name="m" id="m-toss"><i style="--c:var(--ink)"></i>Αμφίρροπες έδρες</label>'
    css = "".join(f"main:has(#h{key}:checked):has(#m-{p}:checked) .h{key}-{p}-{b}"
                  f"{{fill:color-mix(in oklab,{'var(--mute)' if p in HATCHED else colour(p)} {k}%,var(--paper))}}"
                  for key in hz for p in picks for b, (_, k) in enumerate(MAP_BINS, 1))
    css += "".join(f"main:has(#m-{p}:checked) .legend.bins{{--c:{'var(--mute)' if p in HATCHED else colour(p)}}}"
                   for p in picks)
    css += "".join(f"main:has(#h{key}:checked):has(#m-toss:checked) .h{key}-toss-{b}{{fill:color-mix(in oklab,var(--ink) {k}%,var(--paper))}}"
                   for key in hz for b, (_, k) in enumerate(TOSS_BINS, 1))
    css += ".tl{display:none}main:has(#m-toss:checked) .tl{display:block}main:has(#m-toss:checked) .sl{display:none}"
    bins = ["κάτω από 0,5", "0,5–1", "1–2", "2 και πάνω"]
    tkey = ('<li><i class="z"></i>καμία</li>'
            + "".join(f'<li><i style="background:color-mix(in oklab,var(--ink) {k}%,var(--paper))"></i>{t}</li>'
                      for (_, k), t in zip(TOSS_BINS, ["1", "2", "3–4", "5 και πάνω"], strict=True)))
    key_ = ('<li><i class="z"></i>σχεδόν καμία</li>'
            + "".join(f'<li><i style="background:color-mix(in oklab,var(--c) {k}%,var(--paper))"></i>{t}</li>'
                      for (_, k), t in zip(MAP_BINS, bins)))
    fold = lambda t: "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c)).upper()
    options = "".join(f'<option value="{ep}">{html.escape(eps[ep]["name"])}</option>'
                      for ep in sorted(eps, key=lambda ep: fold(eps[ep]["name"])))
    tables = "".join(f'<div class="h{key}">{most_toss(toss[key], eps, names)}{per_ep(r, order, names)}</div>' for key, r in hz.items())
    return css, (f'<h2>Έδρες ανά περιφέρεια</h2>'
                 '<p class="note">Πόσες έδρες παίρνει κατά μέσο όρο σε κάθε περιφέρεια το κόμμα που διαλέγεις. Οι μεγάλες '
                 'περιφέρειες έχουν περισσότερες έδρες, γι’ αυτό βγαίνουν συνήθως πιο σκούρες. Οι 15 έδρες Επικρατείας δεν '
                 'φαίνονται στον χάρτη. «Αμφίρροπες έδρες»: πόσες έδρες κάθε περιφέρειας δεν τις κερδίζει κανένα κόμμα σε 65 '
                 'ή περισσότερες από τις 100 προσομοιώσεις.</p>'
                 f'<fieldset class="pick"><legend>Κόμμα:</legend>{chips}</fieldset>'
                 f'<div class="sl"><p class="legend-t">Μέσος όρος εδρών:</p><ul class="legend bins">{key_}</ul></div>'
                 f'<div class="tl"><p class="legend-t">Αμφίρροπες έδρες:</p><ul class="legend bins">{tkey}</ul></div>'
                 f'<p class="epsel"><label for="ep">Περιφέρεια:</label> <select id="ep"><option value="">διάλεξε…</option>'
                 f'{options}</select></p>'
                 f'<div class="epmap"><figure>{country}</figure>'
                 '<div class="epd"><p aria-live="polite">Πάτησε ή διάλεξε μια περιφέρεια για τις έδρες όλων των κομμάτων εκεί.</p>'
                 '<p class="note">Οι έδρες είναι μέσοι όροι των προσομοιώσεων, γι’ αυτό έχουν δεκαδικά: 0,4 είναι σαν μία '
                 'έδρα στις 4 από τις 10.</p></div>'
                 f'<figure>{zoom}<figcaption>Αττική σε μεγέθυνση</figcaption></figure></div>' + tables)


LAW_SOURCE = ("https://www.hellenicparliament.gr/UserFiles/7b24652e-78eb-4807-9d68-e9a5d4576eff/eklogi-vouleutwn-epist.pdf",
              "την έκθεση της Επιστημονικής Υπηρεσίας της Βουλής για το νομοσχέδιο (22.1.2020)")


def rules(data):
    """§10, the electoral law in plain words, every number from seats_law.LAWS, with a worked bonus example at ND's
    median share today; closed by default."""
    law = LAW.LAWS[LAW.CURRENT]
    b, seats, state = law["bonus"], law["seats"], law["state"]
    full = b["from"] + (b["cap"] - b["base"]) * b["step"]  # the share at which the bonus reaches its cap
    x = data["horizons"]["0"]["parties"]["ND"]["share"][1]
    rows = "".join(f'<tr><td class="n">{num(s, 1 if s % 1 else 0)}%</td><td class="n">{LAW.bonus_seats(s)}</td></tr>'
                   for s in (b["from"] - 0.1, b["from"], b["from"] + 2.5, 30, 35, full))
    url, src = LAW_SOURCE
    return ('<details class="rules"><summary>Οι κανόνες του εκλογικού νόμου με απλά λόγια</summary>'
            f'<p><b>Πόσες έδρες.</b> {seats} βουλευτές: {seats - state} εκλέγονται στις εκλογικές περιφέρειες και {state} '
            f'είναι οι έδρες Επικρατείας. Πλειοψηφία στη Βουλή (αυτοδυναμία, αν είναι ένα κόμμα): {LAW.majority(LAW.CURRENT)}.</p>'
            f'<p><b>Το όριο του {num(law["threshold"], 0)}%.</b> Έδρες παίρνουν μόνο τα κόμματα με {num(law["threshold"], 0)}% '
            'των έγκυρων ψήφων και πάνω σε όλη τη χώρα. Οι ψήφοι των υπόλοιπων δεν φέρνουν έδρα σε κανέναν, οπότε όσα περνούν '
            'παίρνουν λίγο περισσότερες έδρες από το ποσοστό τους.</p>'
            f'<p><b>Το μπόνους.</b> Το πρώτο κόμμα παίρνει επιπλέον έδρες μόνο αν φτάσει το {num(b["from"], 0)}%: {b["base"]} '
            f'έδρες στο {num(b["from"], 0)}%, και μία ακόμη για κάθε μισή μονάδα πάνω από αυτό, έως {b["cap"]} έδρες στο '
            f'{num(full, 0)}%. Οι υπόλοιπες έδρες, μαζί οι {state} Επικρατείας, μοιράζονται αναλογικά στα κόμματα που πέρασαν το '
            f'όριο. Κάτω από {num(b["from"], 0)}% δεν υπάρχει μπόνους και όλες οι {seats} μοιράζονται αναλογικά.</p>'
            f'<div class="wrap"><table class="bonus"><thead><tr><th class="n">πρώτο κόμμα</th><th class="n">μπόνους</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
            f'<p>Σήμερα η ΝΔ είναι στο {num(x)}% (μεσαία τιμή): μπόνους {LAW.bonus_seats(x)} έδρες.</p>'
            '<p><b>Συνασπισμοί.</b> Συνασπισμός κομμάτων παίρνει μπόνους μόνο αν ο μέσος όρος των κομμάτων που τον απαρτίζουν '
            'είναι μεγαλύτερος από το πρώτο κόμμα που κατέβηκε μόνο του. Η πρόβλεψη μετρά κάθε κόμμα ως αυτοτελές.</p>'
            '<p class="note">Ο νόμος είναι ο ν. 4654/2020, που άλλαξε τα άρθρα 99 και 100 του π.δ. 26/2012, και εφαρμόστηκε '
            f'πρώτη φορά στις εκλογές του Ιουνίου 2023. Οι κανόνες εδώ είναι γραμμένοι από <a href="{url}">{src}</a>. Οι ίδιοι '
            'αριθμοί είναι αυτοί που χρησιμοποιεί η προσομοίωση.</p></details>')


BACKTEST_JSON = HERE / "analysis" / "forecast_backtest.json"


def law_words(law):
    """The bonus rule of one law of seats_law.LAWS, in a few words."""
    b = LAW.LAWS[law]["bonus"]
    if not b:
        return "χωρίς μπόνους, όλες οι έδρες αναλογικά"
    if not b["step"]:
        return f"{b['base']} έδρες μπόνους στο πρώτο κόμμα, οι υπόλοιπες αναλογικά"
    return f"μπόνους {b['base']} έως {b['cap']} έδρες στο πρώτο κόμμα από {num(b['from'], 0)}% και πάνω"


def backtest_html():
    """§11 (a): the seat rule of the forecast on the votes of past elections, against the ministry's seats (closed)."""
    d = json.loads(BACKTEST_JSON.read_text(encoding="utf-8"))
    els = d["elections"]
    ok = sum(e["match"] for e in els)
    seat = lambda p: (f'<span>{html.escape(p["name"])} {p["site"]}'
                      + ("" if p["site"] == p["law"] else f' (κανόνας: {p["law"]})') + "</span>")
    rows = "".join(f'<tr><td>{e["label"]}</td><td>ν. {e["law"]}</td>'
                   f'<td class="bt">{" · ".join(seat(p) for p in e["parties"])}</td><td>{"ναι" if e["match"] else "όχι"}</td></tr>'
                   for e in els)
    laws = "".join(f"<li>ν. {k}: {law_words(k)}, {LAW.LAWS[k]['state']} έδρες Επικρατείας.</li>"
                   for k in dict.fromkeys(e["law"] for e in els))
    verdict = (f"ξαναβγάζει ακριβώς τις έδρες κάθε κόμματος και στις {len(els)} εκλογές" if ok == len(els) else
               f"ξαναβγάζει ακριβώς τις έδρες κάθε κόμματος σε {ok} από τις {len(els)} εκλογές")
    return ('<details class="rules"><summary>Έλεγχος του κανόνα στις εκλογές 2015 έως 2023</summary>'
            '<p>Ο κανόνας που μοιράζει τις έδρες στην πρόβλεψη, με τον νόμο που ίσχυε κάθε φορά και τις ψήφους όλης της χώρας '
            f'όπως τις δίνει το Υπουργείο Εσωτερικών, {verdict}.</p>'
            '<div class="wrap"><table><thead><tr><th>εκλογές</th><th>νόμος</th><th>έδρες ανά κόμμα (Υπουργείο)</th>'
            f'<th>ίδιες</th></tr></thead><tbody>{rows}</tbody></table></div><ul>{laws}</ul>'
            f'<p class="note">Πηγή: τα αποτελέσματα του Υπουργείου Εσωτερικών στο <a href="{d["source"]}">'
            f'{d["source"].split("//")[1].rstrip("/")}</a>, όπου δεν υπάρχουν οι εκλογές του 2012. Ο έλεγχος αφορά τις έδρες κάθε '
            'κόμματος σε όλη τη χώρα, όχι σε ποια περιφέρεια πήγε η κάθε έδρα.</p></details>')


def method(n_sims, n_polls, err, sens):
    a, b, n_pairs = err
    moved = max(max(s["moved"].values()) for s in sens.values())
    same = all(s["same_totals"] for s in sens.values())
    return "".join(f"<p>{t}</p>" for t in [
        (f"<b>Μέσος όρος των δημοσκοπήσεων.</b> Για κάθε κόμμα χωριστά ({n_polls} δημοσκοπήσεις από τον Σεπτέμβριο 2023), ένα "
        "μοντέλο ακολουθεί το επίπεδο του κόμματος στον χρόνο και αφαιρεί τη σταθερή απόκλιση κάθε εταιρείας. Το αποτέλεσμα "
        "είναι το επίπεδο μιας «μέσης» εταιρείας, όχι αναγκαστικά η αλήθεια. Για εκλογές σε έξι μήνες, το επίπεδο μπορεί να "
        "κινηθεί όσο κινήθηκε κατά μέσο όρο στο παρελθόν."),
        (f"<b>Το λάθος της κάλπης.</b> Σε {n_pairs} περιπτώσεις κόμματος σε εθνικές εκλογές από το 2007, συγκρίναμε το αποτέλεσμα "
        "με τον μέσο όρο των τελευταίων δημοσκοπήσεων. Τα μικρά κόμματα απέχουν περισσότερο, σε σχέση με το μέγεθός τους, "
        "από τα μεγάλα. Με αυτό το εύρος λάθους κληρώνουμε το αποτέλεσμα κάθε κόμματος, και τα ποσοστά αθροίζουν σε 100."),
        (f"<b>Από τις ψήφους στις έδρες.</b> Σε καθεμία από τις {thousands(n_sims)} προσομοιώσεις, τα ποσοστά μοιράζονται στις "
        "59 εκλογικές περιφέρειες ανάλογα με το πού ψήφισε κάθε κόμμα στις Ευρωεκλογές 2024 (ή στις εκλογές του Ιουνίου 2023), "
        "με λίγο τυχαίο θόρυβο. Μετά εφαρμόζεται ο νόμος: όριο 3%, μπόνους 20 έως 50 εδρών στο πρώτο κόμμα αν πάρει 25% και "
        f"πάνω, {SEATS - STATE} έδρες στις περιφέρειες και {STATE} Επικρατείας. Κάθε προσομοίωση ελέγχεται να δίνει {SEATS} έδρες."),
        "<b>Τα όρια.</b> Τα λάθη των κομμάτων κληρώνονται ανεξάρτητα, ενώ σε πραγματικές εκλογές συχνά κινούνται μαζί· τα εύρη "
        "μπορεί να είναι στενότερα από όσο πρέπει. Τα νέα κόμματα (ΕΛΑΣ, δηλαδή Ελληνική Αριστερή Συμπαράταξη, Ελπίδα, Συμμαχία Ελλήνων) έχουν λίγες δημοσκοπήσεις "
        "και καμία κάλπη. Για όσα δεν έχουν παρελθόν, το πού παίρνουν ψήφους είναι υπόθεση: η ΕΛΑΣ σαν τον ΣΥΡΙΖΑ του Ιουνίου "
        "2023, τα άλλα ομοιόμορφα. "
        + ("Οι έδρες κάθε κόμματος στο σύνολο της χώρας δεν αλλάζουν με αυτές τις υποθέσεις (βγαίνουν από τα εθνικά ποσοστά)· "
           if same else "")
        + f"αλλάζει μόνο σε ποια περιφέρεια εκλέγονται, έως περίπου {num(moved, 0)} έδρες για ένα κόμμα όταν δοκιμάσαμε "
        "άλλες υποθέσεις. Οι δημοσκοπήσεις είναι από τη Wikipedia και, εκτός από τα ποσοστά της ΝΙΚΗΣ, δεν έχουν ελεγχθεί "
        "μία προς μία με τις εταιρείες.",
        (f"<small>Τεχνικά: λάθος κάλπης log(αποτέλεσμα / μέσος όρος) ~ N(0, a/p + b), a = {num(a, 2)}, b = {num(b, 3)}, "
        "με μέγιστη πιθανοφάνεια.</small>")])


def chapter(key, label, hue, inner, quiet=False):
    """One field of the page: its own colour (hue), an id for the bar of chapters, no heading of its own (the first h2 inside is it)."""
    return (f'<section class="ch{" quiet" if quiet else ""}" id="ch-{key}" style="--hue:{hue}" aria-label="{label}">{inner}</section>', (key, label, hue))

def body(data, order, tail=""):
    names = data["names"]
    today = data["horizons"]["0"]["parties"]
    small = {p for p in order if today[p]["share"][1] < THR}
    HATCHED.update(p for p in order if p not in COLOURS and today[p].get("seats") and today[p]["seats"][1] > 0)
    hz = lambda f: "".join(f'<div class="h{key}">{f(r, key)}</div>' for key, r in data["horizons"].items())  # one block per horizon
    css, section = ep_map(data, order, names)
    sam_css, sam = samaras(names)
    seats = lambda r, key: (f'<h2>Έδρες</h2><p class="note">Οι {SEATS} έδρες, με τον μέσο όρο κάθε κόμματος ώστε να '
                            f'αθροίζουν σε {SEATS}. Τους αριθμούς τους δίνει ο πίνακας. Η γραμμή είναι οι {MAJ} της αυτοδυναμίας.</p>'
                            + seatbar(order, names, r) + seat_table(r, order, names) + histograms(r) + ladder_html(r, key, names))
    chapters = [
        chapter("151", "Αυτοδυναμία", 240, hz(lambda r, key: odds(r, key) + partners_html(r, names) + bonus_html(r, key, names))),
        chapter("shares", "Ποσοστά", 175,
                hz(lambda r, key: '<h2>Ποσοστά</h2>' + shares(r, order, names, small) + second_html(r, key, names)) + trend_html(names)),
        chapter("seats", "Έδρες", 85, hz(seats)),
        chapter("regions", "Περιφέρειες", 145, section),
        chapter("scenario", "Σενάριο Σαμαρά", 15, sam),
        chapter("models", "Άλλοι δύο τρόποι", 320, models(names, order)),
        chapter("method", "Δημοσκοπήσεις και μέθοδος", 260, rules(data) + backtest_html() + tail, quiet=True),
    ]
    return {k: (c, lab, h) for c, (k, lab, h) in chapters}, {"regions": css, "scenario": sam_css}  # html by chapter key; css of the chapters that bring their own


# The forecast is one data set shown on four pages (the six chapters were 620 KB on one): the first holds the headline answer,
# the others the detail. The bar of chapters links across them; a chapter of this page is a jump link, one of another page a link to it.
PAGES = [
    {"file": "forecast.html", "chapters": ["151", "shares"], "h1": "Ποσοστά και έδρες από τις δημοσκοπήσεις", "lead": True, "when": True,
     "title": "Εκλογές σήμερα: ποσοστά και έδρες από τον μέσο όρο των δημοσκοπήσεων",
     "desc": "Πιθανότητες αυτοδυναμίας, ποσοστά και έδρες κάθε κόμματος, από τον μέσο όρο των δημοσκοπήσεων."},
    {"file": "forecast_seats.html", "chapters": ["seats"], "h1": "Έδρες κάθε κόμματος", "lead": False, "when": True,
     "title": "Πρόβλεψη: έδρες κάθε κόμματος από τον μέσο όρο των δημοσκοπήσεων",
     "desc": f"Οι {SEATS} έδρες ανά κόμμα, εύρη, κατανομές και βαθμίδες, από τον μέσο όρο των δημοσκοπήσεων."},
    {"file": "forecast_regions.html", "chapters": ["regions"], "h1": "Έδρες ανά περιφέρεια", "lead": False, "when": True,
     "title": "Πρόβλεψη: έδρες ανά εκλογική περιφέρεια",
     "desc": "Πόσες έδρες παίρνει κάθε κόμμα σε κάθε εκλογική περιφέρεια και ποιες έδρες είναι αμφίρροπες."},
    {"file": "forecast_scenarios.html", "chapters": ["scenario", "models", "method"], "h1": "Σενάρια και μέθοδος", "lead": False, "when": False,
     "title": "Πρόβλεψη: σενάριο Σαμαρά, δύο άλλα μοντέλα, δημοσκοπήσεις και μέθοδος",
     "desc": "Το σενάριο ενός νέου κόμματος του Σαμαρά, δύο άλλοι τρόποι μέτρησης των δημοσκοπήσεων, οι δημοσκοπήσεις ανά εταιρεία και πώς βγαίνουν οι αριθμοί."},
]
LABELS = {"151": "Αυτοδυναμία", "shares": "Ποσοστά", "seats": "Έδρες", "regions": "Περιφέρειες", "scenario": "Σενάριο Σαμαρά", "models": "Άλλοι δύο τρόποι",
          "method": "Δημοσκοπήσεις και μέθοδος"}


def chapnav(page, chaps):
    """The bar of chapters of one page. First chapter of a page = its link carries the view (#180, ...), see the script."""
    first = {pg["chapters"][0]: pg for pg in PAGES}
    out = []
    for pg in PAGES:
        for k in pg["chapters"]:
            hue = chaps[k][2]
            if pg is page:
                cur = ' aria-current="true"' if k == page["chapters"][0] else ""
                out.append(f'<a href="#ch-{k}" style="--hue:{hue}"{cur}>{html.escape(chaps[k][1])}</a>')
            else:
                href = pg["file"] if k in first else f'{pg["file"]}#ch-{k}'
                out.append(f'<a href="{href}" style="--hue:{hue}"{" data-view" if k in first else ""}>{html.escape(chaps[k][1])}</a>')
    return '<nav class="chap" aria-label="Ενότητες">' + "".join(out) + "</nav>"


def when(shown):
    return ('<fieldset class="when"' + ("" if shown else " hidden") + '><legend>Εκλογές:</legend>'
            '<label><input type="radio" name="h" id="h0" checked> σήμερα</label>'
            '<label><input type="radio" name="h" id="h180"> σε έξι μήνες</label></fieldset>')


def main():
    data = json.loads(F.OUT.read_text(encoding="utf-8"))
    today = data["horizons"]["0"]
    order = sorted(today["parties"], key=lambda p: (p == F.OTHER, -today["parties"][p]["share"][1]))
    with open(HERE / "analysis" / "nikh_polls.csv", encoding="utf-8") as f:
        n_polls = sum(1 for _ in csv.DictReader(f))
    leads = "".join(lead(r, key) for key, r in data["horizons"].items())
    sources = (f'Δεδομένα: δημοσκοπήσεις από <a href="{WIKI}">Wikipedia</a> '
               '(η ΝΙΚΗ ελεγμένη με τις εταιρείες), αποτελέσματα από το Υπουργείο Εσωτερικών. '
               '<a href="nikh_polls.html">Η ΝΙΚΗ στις δημοσκοπήσεις</a> · <a href="index.html">Όλοι οι χάρτες</a>')
    template = (HERE / "analysis" / "forecast_template.html").read_text(encoding="utf-8")
    n_sims = today["n"]
    tail = (record() + '<section class="method" aria-labelledby="mh"><h2 id="mh">Πώς βγαίνουν οι αριθμοί</h2>'
            + method(n_sims, n_polls, F.error_fit(), data["sensitivity"]) + "</section>")
    chaps, css = body(data, order, tail)
    light = INDEX_LIGHT | {"mute": MUTE[0]} | {f"p-{p}": c[0] for p, c in COLOURS.items()}
    dark = INDEX_DARK | {"mute": MUTE[1]} | {f"p-{p}": c[1] for p, c in COLOURS.items()}
    for pg in PAGES:
        out = HERE / "out" / pg["file"]
        page = template
        for a, b in (("<!--TITLE-->", html.escape(pg["title"])), ("<!--META-->", meta(pg["title"], pg["desc"])), ("<!--H1-->", html.escape(pg["h1"])), ("<!--WHEN-->", when(pg["when"])),
                     ("<!--H180NOTE-->", H180_NOTE if pg["when"] else ""), ("<!--LEAD-->", leads if pg["lead"] else ""),
                     ("<!--N-->", thousands(n_sims)), ("<!--ASOF-->", day(data["as_of"])), ("<!--CHAPNAV-->", chapnav(pg, chaps)),
                     ("<!--BODY-->", "".join(chaps[k][0] for k in pg["chapters"])),
                     ("/*MAP_CSS*/", "".join(css.get(k, "") for k in pg["chapters"])), ("<!--SOURCES-->", sources)):
            assert a in page, a
            page = page.replace(a, b)
        page = fill(page, light, dark, current="forecast", skip="#main",
                    sources=f'<li>Δημοσκοπήσεις: <a href="{WIKI}" rel="noopener">Wikipedia</a></li>')
        out.write_text(secure(page, out), encoding="utf-8")
        print(f"wrote {out} ({thousands(n_sims)} simulations, polls to {data['as_of']})")


if __name__ == "__main__":
    main()
