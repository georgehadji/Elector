"""National election forecast -> out/forecast.html, from analysis/forecast.json (run analysis/forecast.py with the database
first; this script needs no simulation, but it does read the database, for the outlines of the constituency map).

Shown for an election today and in 180 days (radio buttons, CSS :has()): who reaches 151 seats, each party's
share (median and 80% range, with P(>= 3%); parties under 3% today folded away), expected seats as one 300-seat bar and
per coalition, seat ranges with and without the bonus, the histograms of ND's seats alone and with PASOK or ELAS, and the
expected seats per constituency as a map (one party at a time, radio buttons again) and a table. The map's outlines are the
ELSTAT 2021 municipal units of each constituency's polling stations in June 2023, read from the database (data/stavroi.sqlite);
the rest comes from forecast.json. Then how close each polling firm fell at the last three elections (pollster_record.py; a
table, and a check that counting the better firms a bit more would not change the shares). Charts are HTML/SVG built here (no
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
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast as F
import pollster_record as PR

from config import DB, HERE, slug
from geo import boundary, frame, path
from matching import boundaries, centroid, match_units
from web import INDEX_DARK, INDEX_LIGHT, fill, meta, secure

OUT = HERE / "out" / "forecast.html"
MAP_ELECTION = "2023/june"  # per-constituency rows link to this election's maps
WIKI = "https://en.wikipedia.org/wiki/Opinion_polling_for_the_next_Greek_legislative_election"
# party: (light, dark); dict order = slot order = order in the seat bar
COLOURS = {"ND": ("#2a78d6", "#3987e5"), "ELAS": ("#eb6834", "#d95926"), "PASOK": ("#1baf7a", "#199e70"),
           "EL": ("#eda100", "#c98500"), "KKE": ("#e87ba4", "#d55181"), "PE": ("#008300", "#0ca30c"),
           "FL": ("#6250d6", "#9085e9"), "ELPIDA": ("#e34948", "#e66767")}
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
    for p in sorted(mean, key=lambda p: whole[p] - mean[p])[:300 - sum(whole.values())]:
        whole[p] += 1
    assert sum(whole.values()) == 300, whole
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
    nd = r["parties"]["ND"]
    return (f'<p class="lead h{key}">Αν οι εκλογές γίνονταν {WHEN[key]}, η ΝΔ θα ήταν πρώτη {in_sims(nd["p_first"])}, '
            f'με {num(nd["share"][1])}% και {nd["seats"][1]} έδρες στη μεσαία περίπτωση. '
            f'Αυτοδύναμη θα ήταν {in_sims(r["p_nd_majority"])}· μαζί με το ΠΑΣΟΚ θα είχε 151 έδρες '
            f'{in_sims(r["p_nd_pasok_151"])}.</p>')


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


# who reaches 151: label, parties, probability key, histogram key, row class; a fixed order from the smallest group up
GROUPS = (("ΝΔ μόνη της (αυτοδυναμία)", ("ND",), "p_nd_majority", "hist_nd", ' class="nd"'),
          ("ΝΔ και ΠΑΣΟΚ", ("ND", "PASOK"), "p_nd_pasok_151", "hist_nd_pasok", ""),
          ("ΝΔ και ΕΛΑΣ", ("ND", "ELAS"), "p_nd_elas_151", "hist_nd_elas", ""),
          ("ΝΔ, ΠΑΣΟΚ και ΕΛΑΣ", ("ND", "PASOK", "ELAS"), "p_nd_pasok_elas_151", "hist_nd_pasok_elas", ' class="far"'))


def odds(r, key):
    """One row per group: its seats (median and 80% range of the summed seats, as in the seat table) drawn against the
    151 line, and how often it reaches 151. The three-party sum is near certain by arithmetic alone, so it is quieter.
    The bar's segments are the parties' mean seats, the widths of the seat bar below."""
    seats = expected(r)
    items = []
    for title, ps, pk, hk, c in GROUPS:
        p, (lo, mid, hi) = r[pk], hist_range(r[hk])
        ps = sorted(ps, key=list(COLOURS).index)
        n = sum(seats.get(x, 0) for x in ps)
        spans = ("".join(f'<span style="--c:{colour(x)};flex:{seats.get(x, 0)}"></span>' for x in ps)
                 + f'<span class="rest" style="flex:{300 - n}"></span>')
        items.append(f'<li{c}><span class="lb">{title}<small>{mid} έδρες ({lo}–{hi}) · {often(p)}</small></span>'
                     f'<div class="seatbar mini" role="img" aria-label="{title}: {mid} έδρες, στις 8 από τις 10 από {lo} '
                     f'έως {hi}">{spans}<i></i></div><b>{pct(p)}</b></li>')
    return (f'<h2>Ποιοι φτάνουν τις 151 έδρες, εκλογές {WHEN[key]}</h2>'
            '<p class="note">Οι έδρες του κόμματος, ή των κομμάτων μαζί: η μεσαία τιμή και, σε παρένθεση, το εύρος όπου '
            'πέφτουν στις 8 από τις 10. Δεξιά, σε τι ποσοστό των προσομοιώσεων φτάνουν τις 151. Η γραμμή στη μπάρα είναι '
            'οι 151. Είναι αθροίσματα εδρών, όχι πρόβλεψη για το ποια κυβέρνηση θα σχηματιστεί.</p>'
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
            f'<span></span><span class="trk ax">{ticks}<span style="left:{x(3)}">3%</span></span><span></span><span></span>')
    rows = {}
    for p in order:
        lo, mid, hi = r["parties"][p]["share"]
        d = 1 if hi < 10 else 0
        p_in = "—" if p == F.OTHER else pct(r["parties"][p]["p_in"])  # many small parties together: no threshold
        tip = f"{names[p]}: {num(mid)}% (80%: {num(lo)}–{num(hi)}%)" + ("" if p == F.OTHER else f", πιθανότητα να περάσει το 3%: {p_in}")
        rows[p] = (f'<span class="nm">{html.escape(names[p])}</span>'
                   f'<span class="trk" title="{html.escape(tip, quote=True)}" style="--c:{colour(p)}">'
                   f'{grid}<span class="thr" style="left:{x(3)}"></span>'
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
    return (f'<div class="seatbar" role="img" aria-label="Οι 300 έδρες, από αριστερά: {html.escape(label, quote=True)}">'
            f'{spans}<i></i></div>'
            '<div class="trk ax"><span style="left:0;transform:none">0</span><span style="left:50.33%">151</span>'
            '<span style="right:0;transform:none">300</span></div>'
            f'<ul class="legend">{legend}</ul>')


def seats_range(x):
    """[10%, median, 90%] as '117 (100–134)'; one number when the range is a single value."""
    return "—" if not x else str(x[1]) if x[0] == x[2] else f"{x[1]} ({x[0]}–{x[2]})"


def seat_table(r, order, names):
    rows = []
    for p in order:
        d = r["parties"][p]
        if "seats" not in d or d["seats"][2] == 0:  # OTHER has no seats
            continue
        rows.append(f'<tr><td><span class="sw" style="--c:{colour(p)}"></span>{html.escape(names[p])}</td>'
                    f'<td class="n">{pct(d["p_first"])}</td><td class="n">{seats_range(d["seats"])}</td>'
                    f'<td class="n">{seats_range(d["seats_bonus"])}</td><td class="n">{seats_range(d["seats_nobonus"])}</td></tr>')
    return ('<div class="wrap"><table><thead><tr><th>κόμμα</th><th class="n">βγαίνει πρώτο</th><th class="n">έδρες</th>'
            '<th class="n">αν υπάρχει μπόνους</th><th class="n">χωρίς μπόνους</th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table></div>'
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
        out.append(f'<rect class="bar{" win" if s >= 151 else ""}" x="{X(s) + gap / 2:.2f}" y="{Y(f):.1f}" '
                   f'width="{max(bw - gap, 0.4):.2f}" height="{Y(0) - Y(f):.1f}"><title>{s} έδρες: {pct(f)}</title></rect>')
    out.append(f'<line class="base" x1="{left}" x2="{w - right}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/>'
               f'<line class="m151" x1="{X(151):.1f}" x2="{X(151):.1f}" y1="{tp - 0.6 * fs:.1f}" y2="{Y(0):.1f}"/>'
               f'<text class="m151-l" x="{X(151) + 0.3 * fs:.1f}" y="{tp - 0.2 * fs:.1f}">151</text>')
    return "\n".join(out) + "</svg>"


def histograms(r):
    out = []
    no_bonus = 1 - r["p_bonus"]
    hump = ("" if no_bonus < 0.005 else  # the low values on the left: no party reached 25%, so no bonus seats
            f" Οι χαμηλές τιμές αριστερά είναι κυρίως οι προσομοιώσεις χωρίς μπόνους ({pct(no_bonus)}), όπου κανένα "
            "κόμμα δεν έφτασε το 25%.")
    for key, title, p in (("hist_nd", "Έδρες της ΝΔ", r["p_nd_majority"]),
                          ("hist_nd_pasok", "Έδρες ΝΔ και ΠΑΣΟΚ μαζί", r["p_nd_pasok_151"]),
                          ("hist_nd_elas", "Έδρες ΝΔ και ΕΛΑΣ μαζί", r["p_nd_elas_151"])):
        out.append(f'<figure><h3>{title}</h3><div class="wide">{hist(r[key], 440, 210, 12, 20)}</div>'
                   f'<div class="narrow">{hist(r[key], 360, 210, 12, 20)}</div>'
                   f'<figcaption>151 ή περισσότερες: {pct(p)}.</figcaption></figure>')
    return ('<details><summary>Πώς κατανέμονται οι έδρες στις προσομοιώσεις</summary>'
            f'<p class="note">Ποσοστό των προσομοιώσεων ανά αριθμό εδρών· η διακεκομμένη γραμμή είναι οι 151.{hump}</p>'
            '<div class="two">' + "".join(out) + "</div></details>")


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
            'περίπου σε 4 από τις 10. «·»: κάτω από 0,05. Η κατανομή ανά περιφέρεια στηρίζεται σε υποθέσεις (βλ. παρακάτω).</p>'
            f'<div class="wrap"><table><thead><tr><th>περιφέρεια</th><th class="n">έδρες</th>{head}</tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div></details>")


def record():
    """How close each firm fell at 2019, May 2023 and June 2023 (pollster_record.py), and whether weights would move the shares."""
    rows, bench = PR.table()
    top = max(r["avg"] for r in rows)
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
        body_rows.append(f'<tr><td>{html.escape(r["firm"])}</td><td class="rbar"><div class="meter" aria-hidden="true">'
                         f'<i style="width:{100 * r["avg"] / top:.0f}%"></i></div></td><td class="n">{num(r["avg"])}</td>{cells}</tr>')
    return ('<section class="rec" aria-labelledby="rh"><h2 id="rh">Πόσο κοντά έπεσαν οι εταιρείες δημοσκοπήσεων</h2>'
            '<p class="note">Για κάθε εταιρεία που δημοσκοπεί σήμερα: πόσο απείχε η τελευταία της δημοσκόπηση πριν την κάλπη '
            '(έως 21 ημέρες πριν) από το αποτέλεσμα, στις εκλογές του 2019, του Μαΐου 2023 και του Ιουνίου 2023. Η τιμή είναι η '
            'μέση διαφορά ανά κόμμα με 3% και πάνω, σε ποσοστιαίες μονάδες. Μικρότερη σημαίνει πιο κοντά. «·»: η εταιρεία '
            f'δεν είχε τότε δημοσκόπηση στο διάστημα αυτό. Όλες οι δημοσκοπήσεις μαζί απείχαν κατά μέσο όρο {num(bench)} μονάδες.</p>'
            '<div class="wrap"><table class="rec"><thead><tr><th>εταιρεία</th><th></th><th class="n">μέσος όρος</th>'
            f'{head}</tr></thead><tbody>' + "".join(body_rows) + '</tbody></table></div>'
            f'<p class="note">{spread}Οι διαφορές '
            'ανάμεσα στις περισσότερες εταιρείες είναι μικρότερες από τις διακυμάνσεις από εκλογή σε εκλογή: ο πίνακας δείχνει πόσο '
            'κοντά έπεσαν, όχι πόσο κοντά θα πέσουν. Στο μέσο όρο που βγάζουμε, όλες οι εταιρείες μετράνε το ίδιο. Δοκιμάσαμε να '
            f'μετράνε λίγο περισσότερο οι πιο κοντινές: {tested}</p></section>')


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


MAP_BINS = ((0.2, 30), (0.4, 50), (0.6, 72), (1.01, 95))  # share of the constituency's seats -> % of the party colour


def ep_map(data, order, names):
    """Expected seats per constituency on a map of Greece with Attica enlarged beside it: for the party picked (radio
    buttons), the share of each constituency's seats it wins on average, in four steps of its colour. Each region carries
    the class of its step per horizon and party; generated CSS lights the classes of the checked pair. A tap or focus
    shows every party's seats in that constituency below the map."""
    geoms = ep_geometries()
    hz = data["horizons"]
    eps = {ep: e for ep, e in hz["0"]["eps"].items() if ep != "state"}
    attica = [ep for ep, e in eps.items() if any(w in e["name"] for w in ("Αθην", "Πειρ", "Αττικ"))]
    means = {key: {ep: {p: mean_seats(d) for p, d in r["eps"][ep]["dist"].items()} for ep in eps} for key, r in hz.items()}
    total = {p: sum(m.get(p, 0) for m in means["0"].values()) for p in names}
    picks = [p for p in sorted(total, key=lambda p: -total[p]) if total[p] >= 1]

    def step(ep, key, p):
        share = means[key][ep].get(p, 0) / eps[ep]["seats"]
        return 0 if means[key][ep].get(p, 0) < 0.05 else next(i for i, (hi, _) in enumerate(MAP_BINS, 1) if share < hi)

    def detail(ep, key):
        m = sorted(((p, v) for p, v in means[key][ep].items() if v >= 0.05), key=lambda pv: -pv[1])
        return f'{eps[ep]["name"]}, {eps[ep]["seats"]} έδρες: ' + " · ".join(f"{names[p]} {num(v)}" for p, v in m)

    def svg(shown, size, label, box=None):
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
            cls = " ".join(f"h{key}-{p}-{step(ep, key, p)}" for key in hz for p in picks)
            data_ = "".join(f' data-d{key}="{html.escape(detail(ep, key), quote=True)}"' for key in hz)
            out.append(f'<path class="{cls}" d="{d}" tabindex="0" aria-label="{html.escape(eps[ep]["name"], quote=True)}"'
                       f'{data_}/>')
        return f'<svg viewBox="0 0 {w} {h}" role="group" aria-label="{label}">' + "".join(out) + "</svg>"

    country = svg([*(ep for ep in eps), None], 440, "Χάρτης της Ελλάδας ανά εκλογική περιφέρεια")
    zoom = svg(attica, 260, "Αττική σε μεγέθυνση", box=(22.8, 37.6, 24.2, 38.4))  # without Kythira and the far islands
    chips = "".join(f'<label><input type="radio" name="m" id="m-{p}"{" checked" if i == 0 else ""}>'
                    f'<i style="--c:{colour(p)}"></i>{html.escape(names[p])}</label>' for i, p in enumerate(picks))
    css = "".join(f"main:has(#h{key}:checked):has(#m-{p}:checked) .h{key}-{p}-{b}"
                  f"{{fill:color-mix(in oklab,{'var(--mute)' if p in HATCHED else colour(p)} {k}%,var(--paper))}}"
                  for key in hz for p in picks for b, (_, k) in enumerate(MAP_BINS, 1))
    bins = ["κάτω από 20%", "20–40%", "40–60%", "60% και πάνω"]
    key_ = ('<li><i class="z"></i>καμία</li>'
            + "".join(f'<li><i style="background:color-mix(in oklab,var(--ink-2) {k}%,var(--paper))"></i>{t}</li>'
                      for (_, k), t in zip(MAP_BINS, bins)))
    tables = "".join(f'<div class="h{key}">{per_ep(r, order, names)}</div>' for key, r in hz.items())
    return css, (f'<h2>Έδρες ανά περιφέρεια, εκλογές <span class="h0">{WHEN["0"]}</span><span class="h180">{WHEN["180"]}</span></h2>'
                 '<p class="note">Τι μέρος των εδρών κάθε περιφέρειας παίρνει κατά μέσο όρο το κόμμα που διαλέγεις. Πάτησε μια '
                 'περιφέρεια για τις έδρες όλων των κομμάτων εκεί. Οι 15 έδρες Επικρατείας δεν φαίνονται στον χάρτη.</p>'
                 f'<fieldset class="pick"><legend>Κόμμα:</legend>{chips}</fieldset>'
                 f'<div class="epmap"><figure>{country}</figure><figure>{zoom}<figcaption>Αττική σε μεγέθυνση</figcaption></figure></div>'
                 f'<ul class="legend bins">{key_}</ul>'
                 '<p class="epd" aria-live="polite">Πάτησε μια περιφέρεια.</p>' + tables)


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
        "πάνω, 285 έδρες στις περιφέρειες και 15 Επικρατείας. Κάθε προσομοίωση ελέγχεται να δίνει 300 έδρες."),
        "<b>Τα όρια.</b> Τα λάθη των κομμάτων κληρώνονται ανεξάρτητα, ενώ σε πραγματικές εκλογές συχνά κινούνται μαζί· τα εύρη "
        "μπορεί να είναι στενότερα από όσο πρέπει. Τα νέα κόμματα (ΕΛΑΣ, Ελπίδα, Συμμαχία Ελλήνων) έχουν λίγες δημοσκοπήσεις "
        "και καμία κάλπη. Για όσα δεν έχουν παρελθόν, το πού παίρνουν ψήφους είναι υπόθεση: η ΕΛΑΣ σαν τον ΣΥΡΙΖΑ του Ιουνίου "
        "2023, τα άλλα ομοιόμορφα. "
        + ("Οι έδρες κάθε κόμματος στο σύνολο της χώρας δεν αλλάζουν με αυτές τις υποθέσεις (βγαίνουν από τα εθνικά ποσοστά)· "
           if same else "")
        + f"αλλάζει μόνο σε ποια περιφέρεια εκλέγονται, έως περίπου {num(moved, 0)} έδρες για ένα κόμμα όταν δοκιμάσαμε "
        "άλλες υποθέσεις. Οι δημοσκοπήσεις είναι από τη Wikipedia και, εκτός από τα ποσοστά της ΝΙΚΗΣ, δεν έχουν ελεγχθεί "
        "μία προς μία με τις εταιρείες.",
        (f"<small>Τεχνικά: λάθος κάλπης log(αποτέλεσμα / μέσος όρος) ~ N(0, a/p + b), a = {num(a, 2)}, b = {num(b, 3)}, "
        "με μέγιστη πιθανοφάνεια.</small>")])


def body(data, order):
    names = data["names"]
    today = data["horizons"]["0"]["parties"]
    small = {p for p in order if today[p]["share"][1] < 3}
    HATCHED.update(p for p in order if p not in COLOURS and today[p].get("seats") and today[p]["seats"][1] > 0)
    out = []
    for key, r in data["horizons"].items():
        out.append(f'<div class="h{key}">'
                   + odds(r, key)
                   + f'<h2>Ποσοστά, εκλογές {WHEN[key]}</h2>' + shares(r, order, names, small)
                   + f'<h2>Έδρες, εκλογές {WHEN[key]}</h2><p class="note">Οι 300 έδρες, με τον μέσο όρο κάθε κόμματος ώστε να '
                     'αθροίζουν σε 300. Τους αριθμούς τους δίνει ο πίνακας. Η γραμμή είναι οι 151 της αυτοδυναμίας.</p>'
                     + seatbar(order, names, r)
                   + seat_table(r, order, names) + histograms(r) + "</div>")
    css, section = ep_map(data, order, names)
    return css, "".join(out) + section


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
    page = (HERE / "analysis" / "forecast_template.html").read_text(encoding="utf-8")
    map_css, body_html = body(data, order)
    n_sims = today["n"]
    for a, b in (("<!--META-->", meta("Πρόβλεψη βουλευτικών εκλογών",
                                      "Πιθανότητες αυτοδυναμίας, ποσοστά και έδρες κάθε κόμματος, από τον μέσο όρο των δημοσκοπήσεων.")),
                 ("<!--LEAD-->", leads), ("<!--N-->", thousands(n_sims)), ("<!--ASOF-->", day(data["as_of"])),
                 ("<!--BODY-->", body_html), ("/*MAP_CSS*/", map_css), ("<!--RECORD-->", record()),
                 ("<!--METHOD-->", method(n_sims, n_polls, F.error_fit(), data["sensitivity"])), ("<!--SOURCES-->", sources)):
        assert a in page, a
        page = page.replace(a, b)
    light = INDEX_LIGHT | {"mute": MUTE[0]} | {f"p-{p}": c[0] for p, c in COLOURS.items()}
    dark = INDEX_DARK | {"mute": MUTE[1]} | {f"p-{p}": c[1] for p, c in COLOURS.items()}
    page = fill(page, light, dark, current="forecast", skip="#main", compact=True,
                sources=f'<li>Δημοσκοπήσεις: <a href="{WIKI}" rel="noopener">Wikipedia</a></li>')  # not in the nav: nothing marked current
    OUT.write_text(secure(page, OUT), encoding="utf-8")
    print(f"wrote {OUT} ({thousands(n_sims)} simulations, polls to {data['as_of']})")


if __name__ == "__main__":
    main()
