"""NIKH in the polls since 2023 -> out/nikh_polls.html: one dot per poll, the poll average as a line with its band,
the 3% threshold, and the ballots (May 2023, June 2023, Euro 2024).

The line is the Kalman smoother of nikh_polls.py over the polls since Sep 2023 (house effects removed, so it is the
level of an average firm), with a 90% band from the smoothed variance. The 2023 campaign polls are drawn as dots only.
The chart is SVG built here (no chart library, no script): one wide and one narrow drawing, the CSS shows one.
Each poll is marked by its basis (KIND, per firm, from the source checks of NIKH.md section 16): the firm's own vote estimate
(filled dot), intention divided by (1 - undecided) (open dot), or not checked (square). Checkboxes in the key hide a kind in
the chart and the table with CSS :has(), no script.

  python -I -X utf8 analysis/nikh_polls_page.py
"""
import csv
import html
import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nikh_polls
from config import HERE
from web import INDEX_DARK, INDEX_LIGHT, fill, meta, secure

OUT = HERE / "out" / "nikh_polls.html"
WIKI = "https://en.wikipedia.org/wiki/Opinion_polling_for_the_next_Greek_legislative_election"
Z90 = 1.645
BALLOTS = [(d, p, name) for (d, p), name in zip(
    [nikh_polls.BALLOT_2023["2023/may"], nikh_polls.BALLOT_2023["2023/june"], nikh_polls.EURO],
    ["Εκλογές Μαΐου 2023", "Εκλογές Ιουνίου 2023", "Ευρωεκλογές 2024"], strict=True)]
# Basis per firm (NIKH.md section 16): "est" the firm publishes a vote estimate (Real Polls a model forecast, Prorata an
# "estimate with scaling"), "sc" the figure is raw intention / (1 - undecided). Within a firm the basis usually stays, not always.
KIND = {"Alco": "sc", "GPO": "sc", "Interview": "sc",
        "Metron Analysis": "est", "Opinion Poll": "est", "Palmos Analysis": "est", "Marc": "est", "Pulse": "est",
        "Prorata": "est", "Real Polls": "est"}
KINDS = [("est", "εκτίμηση ψήφου της εταιρείας"), ("sc", "αναγωγή της πρόθεσης ψήφου"), ("unk", "βάση μη ελεγμένη")]
SHORT = {"Εκλογές Μαΐου 2023": "Μάιος 2023", "Εκλογές Ιουνίου 2023": "Ιούνιος 2023", "Ευρωεκλογές 2024": "Ευρωεκλογές 2024"}
MONTHS = ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μαΐ", "Ιουν", "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"]


def num(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def day(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def thousands(n):
    return f"{n:,}".replace(",", ".")


def kind(firm):
    return KIND.get(firm, "unk")


def mark(k, cx, cy, r):
    """Poll marker by basis: filled dot, open dot, small square (shape, not colour alone, tells them apart)."""
    if k == "unk":
        a = 0.85 * r
        return f'<rect class="poll unk" x="{cx - a:.1f}" y="{cy - a:.1f}" width="{2 * a:.1f}" height="{2 * a:.1f}">'
    return f'<circle class="poll {k}" cx="{cx:.1f}" cy="{cy:.1f}" r="{r}">'


def polls_2023():
    """[(day, firm, sample or None, pct)] of the May/June 2023 campaigns."""
    with open(Path(nikh_polls.__file__).parent / "nikh_polls_2023.csv", encoding="utf-8") as f:
        return sorted((date.fromisoformat(r["end"]), r["firm"].split("/")[0].replace(" RC", "").strip(),
                       int(r["sample"]) if r["sample"] else None, float(r["niki"])) for r in csv.DictReader(f))


def trend(obs):
    """[(day, level, sd)] from the Rauch-Tung-Striebel smoother over nikh_polls.kfilter (the fit of estimate())."""
    h, q, tau2, _ = nikh_polls.fit(obs)
    flt, _ = nikh_polls.kfilter(obs, h, q, tau2)
    xs = nikh_polls.smooth(obs, flt, q)
    ps = [f[1] for f in flt]
    for i in range(len(flt) - 2, -1, -1):
        j = flt[i][1] / flt[i + 1][3]
        ps[i] = flt[i][1] + j * j * (ps[i + 1] - flt[i + 1][3])
    by_day = {}
    for (d, *_), x, p in zip(obs, xs, ps, strict=True):
        by_day[d] = (x, math.sqrt(max(p, 0)))  # several polls on one day: the last smoothed state
    return [(d, x, s) for d, (x, s) in sorted(by_day.items())]


def chart(polls, line, w, h, fs, r, ticks_every):
    """SVG drawing w x h (user units = px at full width), font size fs, dot radius r, an x tick every N months."""
    left, right, top, bottom = 3.2 * fs, 1.2 * fs, 1.2 * fs, 2.4 * fs
    d0 = date(2023, 4, 1)
    d1 = max(p[0] for p in polls) + timedelta(days=20)
    ymax = math.ceil(max(max(p[3] for p in polls), max(b[1] for b in BALLOTS)) + 0.5)
    X = lambda d: left + (w - left - right) * (d - d0).days / (d1 - d0).days  # noqa: E731
    Y = lambda v: top + (h - top - bottom) * (1 - v / ymax)  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" style="font-size:{fs}px" aria-hidden="true">']
    for v in range(ymax + 1):  # y grid and labels
        out.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                   f'<text class="ax" x="{left - 0.5 * fs}" y="{Y(v) + 0.35 * fs:.1f}" text-anchor="end">{v}%</text>')
    m = date(d0.year, d0.month, 1)
    while m <= d1:  # x ticks: January gets the year
        if (m.month - 1) % ticks_every == 0:
            lab = str(m.year) if m.month == 1 else MONTHS[m.month - 1]
            out.append(f'<line class="grid" x1="{X(m):.1f}" x2="{X(m):.1f}" y1="{h - bottom}" y2="{h - bottom + 0.4 * fs}"/>'
                       f'<text class="ax{" yr" if m.month == 1 else ""}" x="{X(m):.1f}" y="{h - bottom + 1.5 * fs}" text-anchor="middle">{lab}</text>')
        m = date(m.year + m.month // 12, m.month % 12 + 1, 1)
    band = [(X(d), Y(x + Z90 * s)) for d, x, s in line] + [(X(d), Y(max(x - Z90 * s, 0))) for d, x, s in reversed(line)]
    out.append('<polygon class="band" points="' + " ".join(f"{a:.1f},{b:.1f}" for a, b in band) + '"/>')
    out.append(f'<line class="thr" x1="{left}" x2="{w - right}" y1="{Y(3):.1f}" y2="{Y(3):.1f}"/>'
               f'<text class="thr-l" x="{w - right}" y="{Y(3) - 0.4 * fs:.1f}" text-anchor="end">όριο 3%</text>')
    for d, _, _ in BALLOTS:  # election day: a rule over the whole plot
        out.append(f'<line class="eday" x1="{X(d):.1f}" x2="{X(d):.1f}" y1="{top}" y2="{h - bottom}"/>')
    names = dict(KINDS)
    for d, f, n, y in polls:
        size = f", δείγμα {thousands(n)}" if n else ""
        k = kind(f)
        tag = mark(k, X(d), Y(y), r)
        out.append(f'{tag}<title>{html.escape(f)}, {day(d)}{size}: {num(y)}% ({names[k]})</title></{tag[1:tag.index(" ")]}>')
    out.append('<polyline class="avg" points="' + " ".join(f"{X(d):.1f},{Y(x):.1f}" for d, x, _ in line) + '"/>')
    for i, (d, y, name) in enumerate(BALLOTS):
        cx, cy, k = X(d), Y(y), 3.4 * r
        out.append(f'<path class="ballot" d="M{cx:.1f} {cy - k:.1f}L{cx + k:.1f} {cy:.1f}L{cx:.1f} {cy + k:.1f}L{cx - k:.1f} {cy:.1f}Z">'
                   f'<title>{name}: {num(y, 2)}%</title></path>')
        # May sits just under the 3% line and next to June: its label goes below, the others above
        ly = cy + k + 1.1 * fs if i == 0 else cy - k - 0.5 * fs
        out.append(f'<text class="ballot-l" x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle">{num(y, 2)}%</text>')
    return "\n".join(out) + "</svg>"


def main():
    recent = nikh_polls.load()
    line = trend(recent)
    polls = polls_2023() + recent
    last_d, last_x, last_s = line[-1]
    above = sum(1 for p in recent if p[3] >= 3)
    lead = (f"Μέσος όρος των δημοσκοπήσεων στις {day(last_d)}: <b>{num(last_x)}%</b> "
            f"(90%: {num(last_x - Z90 * last_s)}–{num(last_x + Z90 * last_s)}%). "
            f"Από τον Σεπτέμβριο 2023, {above} από τις {len(recent)} δημοσκοπήσεις έδωσαν 3% ή περισσότερο.")
    names = dict(KINDS)
    rows = "".join(f'<tr class="{kind(f)}"><td>{day(d)}</td><td>{html.escape(f)}</td><td>{names[kind(f)]}</td>'
                   f"<td>{thousands(n) if n else '—'}</td><td>{num(y)}%</td></tr>" for d, f, n, y in reversed(polls))
    count = {k: sum(1 for p in polls if kind(p[1]) == k) for k, _ in KINDS}
    toggles = "".join(f'<li><label><input type="checkbox" id="k-{k}" checked> <svg viewBox="0 0 22 12" aria-hidden="true">'
                      f'{mark(k, 11, 6, 3.5)}</{"rect" if k == "unk" else "circle"}></svg>{t} ({count[k]})</label></li>'
                      for k, t in KINDS)
    results = "".join(f"<li><span>{SHORT[name]}</span><b>{num(y, 2)}%</b></li>" for _, y, name in BALLOTS)
    page = (HERE / "analysis" / "nikh_polls_template.html").read_text(encoding="utf-8")
    for a, b in (("<!--META-->", meta("Η ΝΙΚΗ στις δημοσκοπήσεις", "Κάθε δημοσκόπηση για τη ΝΙΚΗ από το 2023, ο μέσος όρος τους και το όριο του 3%.")),
                 ("<!--LEAD-->", lead), ("<!--WIDE-->", chart(polls, line, 900, 380, 12, 3, 3)),
                 ("<!--NARROW-->", chart(polls, line, 360, 300, 10, 2.2, 6)), ("<!--ROWS-->", rows),
                 ("<!--KINDS-->", toggles), ("<!--RESULTS-->", results),
                 ("<!--N-->", str(len(polls))), ("<!--WIKI-->", WIKI)):
        assert a in page, a
        page = page.replace(a, b)
    page = fill(page, INDEX_LIGHT | {"dot": "#46453f"}, INDEX_DARK | {"dot": "#c2c1bc"}, current="maps", skip="#main", compact=True)
    OUT.write_text(secure(page), encoding="utf-8")
    print(f"wrote {OUT} ({len(polls)} polls, last average {num(last_x)}% ± {num(Z90 * last_s)})")


if __name__ == "__main__":
    main()
