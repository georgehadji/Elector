"""National election forecast -> out/forecast.html, from analysis/forecast.json (run analysis/forecast.py with the database
first; this script needs neither the database nor a simulation).

Shown for an election today and in 180 days (radio buttons, CSS :has(), no script): the three probabilities, each party's
share (median and 80% range, with P(>= 3%)), expected seats as one 300-seat bar, seat ranges with and without the bonus,
the histograms of ND's and ND+PASOK's seats, and the expected seats per constituency. Charts are HTML/SVG built here (no
chart library); the histograms have a wide and a narrow drawing, the CSS shows one.
Party colours: the reference palette of the dataviz skill in its validated order (adjacent pairs in the seat bar pass the
colour-vision checks in both themes, against INDEX_LIGHT/INDEX_DARK paper); parties past the eighth are grey.

  python -I -X utf8 analysis/forecast_page.py
"""
import csv
import html
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast as F

from config import HERE
from web import INDEX_DARK, INDEX_LIGHT, fill, meta, secure

OUT = HERE / "out" / "forecast.html"
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


def colour(p):
    return f"var(--p-{p})" if p in COLOURS else "var(--mute)"


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


def cards(r):
    items = [("ΝΔ αυτοδύναμη, 151 έδρες ή περισσότερες", r["p_nd_majority"]),
             ("Το πρώτο κόμμα παίρνει μπόνους (25% και πάνω)", r["p_bonus"]),
             ("ΝΔ και ΠΑΣΟΚ μαζί 151 ή περισσότερες", r["p_nd_pasok_151"]),
             ("ΝΔ και ΕΛΑΣ μαζί 151 ή περισσότερες", r["p_nd_elas_151"]),
             ("ΝΔ, ΠΑΣΟΚ και ΕΛΑΣ μαζί 151 ή περισσότερες", r["p_nd_pasok_elas_151"])]
    return '<ul class="cards">' + "".join(f"<li><span>{t}</span><b>{pct(p)}</b></li>" for t, p in items) + "</ul>"


def shares(r, order, names):
    top = max(r["parties"][p]["share"][2] for p in order)
    scale = 5 * (int(top) // 5 + 1)
    x = lambda v: f"{100 * v / scale:.2f}%"
    out = [('<div class="sh"><span class="hd l">κόμμα</span><span class="hd l">ποσοστό: κουκκίδα ο διάμεσος, γραμμή το 80%</span>'
           '<span class="hd">διάμεσος</span><span class="hd">πιθ. ≥3%</span>')]
    for p in order:
        lo, mid, hi = r["parties"][p]["share"]
        p_in = "—" if p == F.OTHER else pct(r["parties"][p]["p_in"])  # many small parties together: no threshold
        tip = f"{names[p]}: {num(mid)}% (80%: {num(lo)}–{num(hi)}%)" + ("" if p == F.OTHER else f", πιθανότητα να περάσει το 3%: {p_in}")
        out.append(f'<span class="nm">{html.escape(names[p])}</span>'
                   f'<span class="trk" title="{html.escape(tip, quote=True)}" style="--c:{colour(p)}">'
                   f'<span class="thr" style="left:{x(3)}"></span>'
                   f'<span class="rng" style="left:{x(lo)};width:{100 * (hi - lo) / scale:.2f}%"></span>'
                   f'<span class="dot" style="left:{x(mid)}"></span></span>'
                   f'<span class="v">{num(mid)}%</span><span class="v">{p_in}</span>')
    ticks = "".join(f'<span style="left:{x(v)}">{v}%</span>' for v in range(0, scale + 1, 10 if scale > 20 else 5))
    out.append(f'<span></span><span class="trk ax">{ticks}<span style="left:{x(3)};top:-2px">3%</span></span><span></span><span></span></div>')
    return "".join(out)


def seatbar(r, order, names):
    """One 300-seat bar of expected seats: the coloured parties in slot order, the rest folded into one grey segment."""
    seats = expected(r)
    rest = [p for p in order if p not in COLOURS and seats.get(p)]
    parts = [(colour(p), names[p], seats[p], "") for p in COLOURS if seats.get(p)]
    if rest:
        parts.append(("var(--mute)", "Άλλα κόμματα", sum(seats[p] for p in rest),
                      " (" + ", ".join(f"{names[p]} {seats[p]}" for p in rest) + ")"))
    spans = "".join(f'<span style="--c:{c};flex:{n}" title="{html.escape(t + " " + str(n) + x, quote=True)}"></span>'
                    for c, t, n, x in parts)
    legend = "".join(f'<li><i style="--c:{c}"></i>{html.escape(t)} <b>{n}</b>{html.escape(x)}</li>' for c, t, n, x in parts)
    label = ", ".join(f"{t} {n}{x}" for _, t, n, x in parts)
    return (f'<div class="seatbar" role="img" aria-label="Αναμενόμενες έδρες: {html.escape(label, quote=True)}">{spans}<i></i></div>'
            '<div class="trk ax"><span style="left:0;transform:none">0</span><span style="left:50.33%">151</span>'
            '<span style="right:0;transform:none">300</span></div>'
            f'<ul class="legend">{legend}</ul>')


def seat_table(r, order, names):
    rows = []
    for p in order:
        d = r["parties"][p]
        if "seats" not in d or d["seats"][2] == 0:  # OTHER has no seats
            continue
        rows.append(f'<tr><td><span class="sw" style="--c:{colour(p)}"></span>{html.escape(names[p])}</td>'
                    f'<td class="n">{pct(d["p_first"])}</td><td class="n">{F.fmt(d["seats"])}</td>'
                    f'<td class="n">{F.fmt(d["seats_bonus"])}</td><td class="n">{F.fmt(d["seats_nobonus"])}</td></tr>')
    return ('<div class="wrap"><table><thead><tr><th>κόμμα</th><th class="n">πιθ. 1ο</th><th class="n">έδρες</th>'
            '<th class="n">αν υπάρχει μπόνους</th><th class="n">χωρίς μπόνους</th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table></div>'
            '<p class="note">Έδρες: 10%–διάμεσος–90% των προσομοιώσεων. «Αν υπάρχει μπόνους»: μόνο οι προσομοιώσεις όπου το '
            'πρώτο κόμμα πήρε 25% και πάνω.</p>')


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
    for key, title, p in (("hist_nd", "Έδρες της ΝΔ", r["p_nd_majority"]),
                          ("hist_nd_pasok", "Έδρες ΝΔ και ΠΑΣΟΚ μαζί", r["p_nd_pasok_151"])):
        out.append(f'<figure><h3>{title}</h3><div class="wide">{hist(r[key], 440, 210, 12, 20)}</div>'
                   f'<div class="narrow">{hist(r[key], 360, 210, 12, 20)}</div>'
                   f'<figcaption>Ποσοστό των προσομοιώσεων ανά αριθμό εδρών. 151 ή περισσότερες: {pct(p)}.</figcaption></figure>')
    return '<div class="two">' + "".join(out) + "</div>"


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
        rows.append(f"<tr{cls}><td>{html.escape(e['name'])}</td><td class=\"n\">{e['seats']}</td>{cells}</tr>")
    return ('<details><summary>Αναμενόμενες έδρες ανά εκλογική περιφέρεια</summary>'
            '<p class="note">Μέσος όρος των προσομοιώσεων, γι’ αυτό έχει δεκαδικά: 0,4 σημαίνει ότι το κόμμα παίρνει έδρα εκεί '
            'περίπου σε 4 από τις 10. «·»: κάτω από 0,05. Η κατανομή ανά περιφέρεια στηρίζεται σε υποθέσεις (βλ. παρακάτω).</p>'
            f'<div class="wrap"><table><thead><tr><th>περιφέρεια</th><th class="n">έδρες</th>{head}</tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div></details>")


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
        "άλλες υποθέσεις. Οι στήλες των δημοσκοπήσεων εκτός της ΝΙΚΗΣ είναι από τη Wikipedia και δεν έχουν ελεγχθεί μία προς "
        "μία με τις εταιρείες.",
        (f"<small>Τεχνικά: λάθος κάλπης log(αποτέλεσμα / μέσος όρος) ~ N(0, a/p + b), a = {num(a, 2)}, b = {num(b, 3)}, "
        "με μέγιστη πιθανοφάνεια.</small>")])


def body(data, order):
    names = data["names"]
    out = []
    for key, r in data["horizons"].items():
        out.append(f'<div class="h{key}">'
                   + cards(r)
                   + f'<h2>Ποσοστά, εκλογές {WHEN[key]}</h2>' + shares(r, order, names)
                   + f'<h2>Έδρες, εκλογές {WHEN[key]}</h2><p class="note">Αναμενόμενες έδρες: μέσος όρος των προσομοιώσεων, '
                     'γι’ αυτό μπορεί να διαφέρει λίγο από τη μεσαία τιμή του πίνακα. Η γραμμή είναι οι 151 της αυτοδυναμίας.</p>' + seatbar(r, order, names)
                   + seat_table(r, order, names) + histograms(r) + per_ep(r, order, names) + "</div>")
    return "".join(out)


def main():
    data = json.loads(F.OUT.read_text(encoding="utf-8"))
    today = data["horizons"]["0"]
    order = sorted(today["parties"], key=lambda p: (p == F.OTHER, -today["parties"][p]["share"][1]))
    with open(HERE / "analysis" / "nikh_polls.csv", encoding="utf-8") as f:
        n_polls = sum(1 for _ in csv.DictReader(f))
    nd = today["parties"]["ND"]
    lead = (f"Αν οι εκλογές γίνονταν σήμερα, η ΝΔ θα ήταν πρώτη σε {pct(nd['p_first'])} των προσομοιώσεων, με "
            f"{num(nd['share'][1])}% και {nd['seats'][1]} έδρες στη μέση περίπτωση. Αυτοδύναμη θα ήταν σε "
            f"{pct(today['p_nd_majority'])}· μαζί με το ΠΑΣΟΚ θα είχε 151 έδρες σε {pct(today['p_nd_pasok_151'])}.")
    sources = (f'Δεδομένα: δημοσκοπήσεις από <a href="{WIKI}">Wikipedia</a> '
               '(η ΝΙΚΗ ελεγμένη με τις εταιρείες), αποτελέσματα από το Υπουργείο Εσωτερικών. '
               '<a href="nikh_polls.html">Η ΝΙΚΗ στις δημοσκοπήσεις</a> · <a href="index.html">Όλοι οι χάρτες</a>')
    page = (HERE / "analysis" / "forecast_template.html").read_text(encoding="utf-8")
    n_sims = today["n"]
    for a, b in (("<!--META-->", meta("Πρόβλεψη βουλευτικών εκλογών",
                                      "Πιθανότητες αυτοδυναμίας, ποσοστά και έδρες κάθε κόμματος, από τον μέσο όρο των δημοσκοπήσεων.")),
                 ("<!--LEAD-->", lead), ("<!--N-->", thousands(n_sims)), ("<!--ASOF-->", day(data["as_of"])),
                 ("<!--BODY-->", body(data, order)),
                 ("<!--METHOD-->", method(n_sims, n_polls, F.error_fit(), data["sensitivity"])), ("<!--SOURCES-->", sources)):
        assert a in page, a
        page = page.replace(a, b)
    light = INDEX_LIGHT | {"mute": MUTE[0]} | {f"p-{p}": c[0] for p, c in COLOURS.items()}
    dark = INDEX_DARK | {"mute": MUTE[1]} | {f"p-{p}": c[1] for p, c in COLOURS.items()}
    page = fill(page, light, dark, current="maps", skip="#main", compact=True)
    OUT.write_text(secure(page, OUT), encoding="utf-8")
    print(f"wrote {OUT} ({thousands(n_sims)} simulations, polls to {data['as_of']})")


if __name__ == "__main__":
    main()
