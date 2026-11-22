"""Poll average for NIKH (party 131): Kalman local-level model with a house effect per polling firm.

Data: analysis/nikh_polls.csv (firm, end date of fieldwork, sample, NIKH %), 337 polls from 26 Sep 2023 to 19 Nov 2026, copied
on 22 Nov 2026 from the Wikipedia table "Opinion polling for the next Greek parliamentary election". The table does not say
for every poll whether the figure is a vote estimate (undecided removed) or a raw intention, so firms differ in basis; the
house effects absorb that. Rows of the table without a firm name, and polls with no NIKH figure, are left out.
The csv was typed by hand and then compared row by row with the table by a script in the browser (firm, end date, sample,
NIKH %): one missing poll was added, no other difference.
Four NIKH figures of the table were wrong and are corrected here from the published estimates (NIKH.md section 16):
Interview/Political 2026-02-09 2.2 -> 1.4, Metron Analysis/Mega 2025-12-16 2.6 -> 2.1, Pulse RC/Skai 2024-12-17 4.5 -> 3.5,
Marc/ANT1 2024-10-26 3.5 -> 3.1. So the csv no longer equals the Wikipedia table in those four rows.
Good Affairs/Dailypost May 2024: end date and sample follow the pollster's PDF (2024-05-23, 3670), not Wikipedia (25 May, 1000).
Real Polls/Protagon 2025-10-20 (1724, 2.8) is not in the Wikipedia table; added from the pollster's own page and chart.
GPO/Parapolitika 2024-11-15 (1000, 3.5) is a row without a firm name in the Wikipedia table (15-16 Nov, 3.7); added from
Ta Nea 16 Nov 2024: raw intention 3.1, undecided 12.4, so 3.1 / (1 - 0.124) = 3.5. Sample from Wikipedia.
Model (stdlib only):
- true level x_t (% of valid votes) follows a random walk, daily variance q;
- poll i of firm f: y_i = x_t + h_f + e_i, var(e_i) = p(1-p)/n * 10^4 + tau^2 (sampling + non-sampling noise, in %^2);
- h_f: mean residual of the firm, shrunk by n_f/(n_f + 3), centred to 0 over all polls. So the average has the average house's
  bias: the average of the polls, not the truth.
- q and tau are chosen by maximum likelihood on a grid; the house effects and (q, tau) are iterated 6 times; a Rauch-Tung-Striebel
  smoother gives the residuals. The estimate at a date is the filter, using only polls up to that date.
Calibration: the same model on polls up to 8 Jun 2024 vs the Euro 2024 result (4.37% with postal votes).
For May and June 2023: analysis/nikh_polls_2023.csv, the polls with a NIKH figure in the Wikipedia tables "Opinion polling
for the May 2023 / June 2023 Greek parliamentary election" (exit polls left out), ballot / plain mean of the polls of the
last 14 days. No house effects there: 10 and 24 polls are too few.
Unofficial results.

  python -I -X utf8 analysis/nikh_polls.py
"""
import csv
import math
from datetime import date
from pathlib import Path

CSV = Path(__file__).resolve().parent / "nikh_polls.csv"
TODAY = date(2026, 11, 22)
EURO = (date(2024, 6, 9), 4.37)  # Euro 2024 ballot, official with postal votes
D0 = date(2023, 9, 26)
BALLOT_2023 = {"2023/may": (date(2023, 5, 21), 2.92), "2023/june": (date(2023, 6, 25), 3.70)}  # NIKH % of valid votes


def load():
    """[(day, firm, sample, pct)] sorted by day. Firm = first part of 'Firm/Commissioner'."""
    with open(CSV, encoding="utf-8") as f:
        rows = [(date.fromisoformat(r["end"]), r["firm"].split("/")[0].replace(" RC", "").strip(), int(r["sample"]), float(r["niki"]))
                for r in csv.DictReader(f)]
    return sorted(rows)


def kfilter(obs, h, q, tau2, upto=None):
    """Filter over obs [(day, firm, n, y)] sorted by day. Returns lists of (x_f, P_f, x_pred, P_pred), loglik."""
    out, ll = [], 0.0
    x, P, t = obs[0][3], 4.0, obs[0][0]
    for d, f, n, y in obs:
        if upto and d > upto:
            break
        xp, Pp = x, P + q * (d - t).days
        p = min(max(xp, 0.3) / 100, 0.5)
        S = Pp + p * (1 - p) / n * 1e4 + tau2
        v = y - h.get(f, 0) - xp
        K = Pp / S
        x, P, t = xp + K * v, (1 - K) * Pp, d
        out.append((x, P, xp, Pp))
        ll += -0.5 * (math.log(2 * math.pi * S) + v * v / S)
    return out, ll


def smooth(obs, flt, q):
    xs = [f[0] for f in flt]
    for i in range(len(flt) - 2, -1, -1):
        Pp = flt[i + 1][3]
        J = flt[i][1] / Pp
        xs[i] = flt[i][0] + J * (xs[i + 1] - flt[i + 1][2])
    return xs


def fit(obs):
    """house effects, q, tau2, loglik."""
    h = {}
    best = None
    for _ in range(6):
        best = max((kfilter(obs, h, q, tau * tau)[1], q, tau * tau)
                    for q in (0.0005, 0.001, 0.002, 0.004, 0.008, 0.016, 0.03) for tau in (0.01, 0.1, 0.2, 0.3, 0.45, 0.6, 0.8))
        _, q, tau2 = best
        flt, _ = kfilter(obs, h, q, tau2)
        xs = smooth(obs, flt, q)
        res = {}
        for (d, f, n, y), s in zip(obs, xs, strict=True):
            res.setdefault(f, []).append(y - s)
        raw = {f: sum(r) / (len(r) + 3) for f, r in res.items()}
        mean = sum(raw[f] * len(res[f]) for f in raw) / len(obs)
        h = {f: raw[f] - mean for f in raw}
    return h, q, tau2, best[0]


def estimate(horizon_days=0):
    """(mean, sd) of NIKH's true level at TODAY + horizon_days, from all polls. sd includes the random-walk drift."""
    obs = load()
    h, q, tau2, _ = fit([(d, f, n, y) for d, f, n, y in obs])
    flt, _ = kfilter(obs, h, q, tau2)
    x, P, _, _ = flt[-1]
    gap = (TODAY - obs[-1][0]).days + horizon_days
    return x, math.sqrt(P + q * gap)


def euro_miss(h, q, tau2, obs):
    """Ballot / poll-average ratios for Euro 2024: the filter's own and each poll of the last 14 days (house effect removed)."""
    flt, _ = kfilter(obs, h, q, tau2, upto=EURO[0])
    last = [(d, f, n, y) for d, f, n, y in obs if (EURO[0] - d).days <= 14 and d < EURO[0]]
    x = flt[len(obs[: len(flt)]) - 1][0]
    return EURO[1] / x, sorted(EURO[1] / (y - h.get(f, 0)) for _, f, _, y in last)


def miss_2023(days=14):
    """{election: (ballot / mean of the polls of the last `days` days, sorted per-poll ratios, number of polls)}."""
    with open(CSV.with_name("nikh_polls_2023.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for e, (day, ballot) in BALLOT_2023.items():
        ys = [float(r["niki"]) for r in rows if r["election"] == e and 0 < (day - date.fromisoformat(r["end"])).days <= days]
        out[e] = (ballot / (sum(ys) / len(ys)), sorted(ballot / y for y in ys), len(ys))
    return out


if __name__ == "__main__":
    obs = load()
    # self-check: constant level 2% from one firm -> filter ends near 2
    _o = [(date(2024, 1, 1 + i), "A", 1000, 2.0) for i in range(20)]
    assert abs(kfilter(_o, {}, 0.001, 0.01)[0][-1][0] - 2.0) < 1e-6
    h, q, tau2, ll = fit(obs)
    print(f"{len(obs)} δημοσκοπήσεις, {len({f for _, f, _, _ in obs})} εταιρείες, {obs[0][0]} έως {obs[-1][0]}")
    print(f"Μοντέλο: q^(1/2) = {math.sqrt(q):.3f} μονάδες ανά √ημέρα (= {math.sqrt(q * 30):.2f} ανά μήνα), "
          f"τ = {math.sqrt(tau2):.2f} μονάδες (θόρυβος εκτός δειγματοληψίας), loglik {ll:.1f}")
    print("\nΕφέ εταιρείας (μονάδες ΝΙΚΗΣ πάνω/κάτω από τον μέσο όρο όλων, σμίκρυνση n/(n+3))")
    cnt = {f: sum(1 for o in obs if o[1] == f) for f in h}
    for f in sorted(h, key=h.get):
        print(f"  {f:<28}{h[f]:+6.2f}   ({cnt[f]} δημοσκοπήσεις)")
    flt, _ = kfilter(obs, h, q, tau2)
    xs = smooth(obs, flt, q)
    print("\nΕκτίμηση του πραγματικού επιπέδου (μέσος όρος εταιρειών, εξομαλυμένη τιμή ανά τρίμηνο)")
    seen = set()
    for (d, f, n, y), s in zip(obs, xs, strict=True):
        k = (d.year, (d.month - 1) // 3)
        if k not in seen and d.month in (1, 4, 7, 10) or d == obs[-1][0]:
            seen.add(k)
            print(f"  {d}  {s:.2f}%")
    x, P, _, _ = flt[-1]
    gap = (TODAY - obs[-1][0]).days
    for H in (0, 180):
        sd = math.sqrt(P + q * (gap + H))
        print(f"\nΣτις {TODAY} + {H} ημέρες: μέσος όρος {x:.2f}% (95%: {x - 1.96 * sd:.2f}–{x + 1.96 * sd:.2f}%)"
              f" = {x / 100 * 5.1e6:,.0f} ψήφοι με 5,1 εκατ. έγκυρα")
    recent = [y - h.get(f, 0) for d, f, n, y in obs if (obs[-1][0] - d).days <= 60]
    print(f"Απλός μέσος όρος των τελευταίων 60 ημερών: {sum(recent) / len(recent):.2f}% ({len(recent)} δημοσκοπήσεις, εύρος "
          f"{min(y for d, f, n, y in obs if (obs[-1][0] - d).days <= 60):.1f}–{max(y for d, f, n, y in obs if (obs[-1][0] - d).days <= 60):.1f}%)")
    print("\nΤελευταία δημοσκόπηση κάθε εταιρείας (εφέ εταιρείας αφαιρείται)")
    last = {}
    for o in obs:
        last[o[1]] = o
    for f, (d, _, n, y) in sorted(last.items(), key=lambda kv: kv[1][0], reverse=True)[:12]:
        print(f"  {d}  {f:<28}{y:.1f}%  → {y - h[f]:.2f}%")
    m, per = euro_miss(h, q, tau2, obs)
    k = len(per)
    print(f"\nΕυρωεκλογές 9.6.2024: κάλπη {EURO[1]}%. Μέσος όρος δημοσκοπήσεων μέχρι 8.6: {EURO[1] / m:.2f}% → κάλπη/δημοσκοπήσεις = {m:.2f}")
    print(f"  ανά δημοσκόπηση των τελευταίων 14 ημερών ({k}): {per[0]:.2f}–{per[-1]:.2f}, 10%-90%: {per[int(.1 * k)]:.2f}–{per[min(k - 1, int(.9 * k))]:.2f}")
    for e, (m3, per3, k3) in miss_2023().items():
        day, ballot = BALLOT_2023[e]
        print(f"Εκλογές {day}: κάλπη {ballot}%. Απλός μέσος όρος των {k3} δημοσκοπήσεων των τελευταίων 14 ημερών: {ballot / m3:.2f}% "
              f"→ κάλπη/δημοσκοπήσεις = {m3:.2f}· ανά δημοσκόπηση {per3[0]:.2f}–{per3[-1]:.2f}, 10%-90%: {per3[int(.1 * k3)]:.2f}–{per3[min(k3 - 1, int(.9 * k3))]:.2f}")
