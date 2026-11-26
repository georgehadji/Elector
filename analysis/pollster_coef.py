"""Coefficient of each polling firm and party: ballot / poll, over every poll of every past election, however early it was.

Data: analysis/nikh_pollerror.csv (polls_wiki.py: Wikipedia poll tables of 12 elections, 2007-2024; not checked against the
firms' releases; rows of kind "ballot" carry each party's result, % of valid votes, rounded to 0.1).
- A poll = consecutive rows with the same (election, firm, end, sample); a party seen twice starts the next poll (two polls of
  one firm can share an end day and an empty sample). Firm = pollster_record.firm_of() without Wikipedia's "Archived ..."
  note, spellings merged (FIRM). Party = PARTY (the same party under the names Wikipedia gave it over the years).
  NIKH comes from the hand-checked nikh_polls_2023.csv and nikh_polls.csv instead (niki_cells): Wikipedia lists it in few polls.
- Only vote estimates: a poll whose listed parties sum to less than MIN_SUM % is raw vote intention (undecided still in it),
  whose ratio to the ballot would mostly measure the undecided; it is left out.
- A cell (poll, party) counts when the party has a ballot >= MIN_PCT and the poll >= MIN_PCT (ratios of tiny figures are
  rounding noise). r = ln(ballot / poll).
- Per firm, party and election: mean r over all its polls of that party (any lead time). Per firm and party:
  k = exp(mean over elections), each election one weight (one election with 80 polls does not outvote three with 5).
  sd = sd of the per-election means (needs >= 2 elections): the coefficient's stability from one election to the next.
- h = the firm's house effect: exp(mean over elections of (firm's election mean - mean of all firms' election means for that
  party)). k mixes the firm with the error every firm shared at that election (May 2023: everybody had ND too low); h keeps
  only what sets the firm apart, so it is the part more likely to repeat. h > 1: the firm had the party lower than the others.
- Lead-time table: k of each party over all firms, by days before the election (0-30, 31-90, 91-365, 366+): how much of k is
  the poll being early.
Elections are few and not independent; a firm with one election has a coefficient, not a track record.

Method of each poll: analysis/pollster_methods.csv (firm, from, to, mode: CATI telephone, MIXED telephone + online panel, CAWI
online, IVR automated calls, UNKNOWN; sources in the file, pre-2013 rows mostly inferred). The period with the latest start
that contains the poll's end day wins (Alco: one client's polls stayed telephone). model() uses the national elections
only (the European ones of 2014, 2019 and 2024 had the governing party lower than its polls, see governing()) and splits
each party's ln k in three,
each shrunk toward the level above as n / (n + K):
- party: mean over elections of all firms' mean (K_EL elections);
- method: mean, over (firm, election), of the firm's election mean minus all firms' mean in that election (K_MODE entries):
  compared inside an election, so a method used only in 2023-2024 is not blamed for the error everyone made then; UNKNOWN 0;
- firm and method: the rest, mean over elections (K_EL).
k(firm, method, party) = exp(sum). A firm-method never seen gets party + method; a party never seen (ELAS) gets 1.
Weights (forecast_models.py, model B): inverse mean square of r over the polls ending within NEAR days of an election, per
election, shrunk firm-method -> method -> party (same K), relative to the party's mean; clipped to [1/W_CLIP, W_CLIP].
governing(): k of the party in government and of the main opposition, per election and lead time (2012 left out: coalition,
then a caretaker government).

  python -I -X utf8 analysis/pollster_coef.py   -> analysis/pollster_coef.csv, analysis/pollster_coef.txt
"""
import csv
import math
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from functools import cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pollster_record import firm_of  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC = HERE / "nikh_pollerror.csv"
OUT_CSV, OUT_TXT = HERE / "pollster_coef.csv", HERE / "pollster_coef.txt"
MIN_SUM, MIN_PCT = 85.0, 0.5
BUCKETS = ((0, 30), (31, 90), (91, 365), (366, 10**4))
METHODS = HERE / "pollster_methods.csv"
K_EL, K_MODE, NEAR, W_CLIP = 2, 5, 90, 3.0
MODES = ("CATI", "MIXED", "CAWI", "IVR", "UNKNOWN")
# election: (party of the prime minister, main opposition)
GOV = {"2007": ("ΝΔ", "ΠΑΣΟΚ"), "2009": ("ΝΔ", "ΠΑΣΟΚ"), "2014/euro": ("ΝΔ", "ΣΥΡΙΖΑ"), "2015/jan": ("ΝΔ", "ΣΥΡΙΖΑ"),
       "2015/sep": ("ΣΥΡΙΖΑ", "ΝΔ"), "2019/euro": ("ΣΥΡΙΖΑ", "ΝΔ"), "2019": ("ΣΥΡΙΖΑ", "ΝΔ"), "2023/may": ("ΝΔ", "ΣΥΡΙΖΑ"),
       "2023/june": ("ΝΔ", "ΣΥΡΙΖΑ"), "2024/euro": ("ΝΔ", "ΣΥΡΙΖΑ")}
FIRM = {"MARC": "Marc", "RASS": "Rass", "AUEB–STAT": "AUEB-STAT", "Opinion": "Opinion Poll"}
PARTY = {
    "New_Democracy_(Greece)": "ΝΔ", "SYRIZA": "ΣΥΡΙΖΑ", "Syriza": "ΣΥΡΙΖΑ", "Coalition_of_the_Radical_Left": "ΣΥΡΙΖΑ",
    "PASOK": "ΠΑΣΟΚ", "Panhellenic_Socialist_Movement": "ΠΑΣΟΚ", "PASOK_–_Movement_for_Change": "ΠΑΣΟΚ",
    "Movement_for_Change_(Greece)": "ΠΑΣΟΚ", "Olive_Tree_(Greece)": "ΠΑΣΟΚ",  # Ελιά 2014, the PASOK-led list
    "Communist_Party_of_Greece": "ΚΚΕ", "Golden_Dawn_(Greece)": "ΧΑ", "Golden_Dawn_(political_party)": "ΧΑ",
    "Independent_Greeks": "ΑΝΕΛ", "Popular_Orthodox_Rally": "ΛΑΟΣ", "Greek_Solution": "Ελληνική Λύση",
    "Democratic_Left_(Greece)": "ΔΗΜΑΡ", "The_River_(Greece)": "Ποτάμι", "MeRA25": "ΜέΡΑ25",
    "Course_of_Freedom": "Πλεύση Ελευθερίας", "Niki_(Greek_political_party)": "ΝΙΚΗ", "Victory_(Greek_political_party)": "ΝΙΚΗ",
    "Spartans_(Greek_political_party)": "Σπαρτιάτες", "Union_of_Centrists": "Ένωση Κεντρώων", "Popular_Unity_(Greece)": "ΛΑΕ",
    "Ecologist_Greens": "Οικολόγοι Πράσινοι", "Democratic_Alliance_(Greece)": "Δημοκρατική Συμμαχία",
    "Movement_of_Democratic_Socialists": "ΚΙΔΗΣΟ", "Antarsya": "ΑΝΤΑΡΣΥΑ", "Recreate_Greece": "Δημιουργία ξανά",
    "National_Creation": "Εθνική Δημιουργία", "Voice_of_Reason_(political_party)": "Φωνή Λογικής", "New_Left_(Greece)": "Νέα Αριστερά",
    "Democrats_(Greece,_2024)": "Δημοκράτες", "Kosmos_(political_party)": "Κόσμος",
    "Patriots_–_Prodromos_Emfietzoglou": "Πατριώτες",
}


def firm(name):
    f = re.sub(r"\s*Archived .*$", "", firm_of(name)).strip()
    return FIRM.get(f, f)


def _day(s, end=False):
    """'2023', '2023-05' or '2023-05-12' as the first (or with end, the last) day it covers."""
    p = [int(x) for x in s.split("-")]
    if len(p) == 3:
        return date(*p)
    if not end:
        return date(p[0], p[1] if len(p) > 1 else 1, 1)
    y, m = (p[0], 12) if len(p) == 1 else (p[0], p[1])
    return date(y + m // 12, m % 12 + 1, 1) - timedelta(1)


@cache
def _periods():
    with open(METHODS, encoding="utf-8") as f:
        rs = [(r["firm"], _day(r["from"]), _day(r["to"], True) if r["to"] else date.max, r["mode"]) for r in csv.DictReader(f)]
    out = defaultdict(list)
    for fm, a, b, m in rs:
        out[fm].append((a, b, m))
    return out


def mode(fm, day):
    """Method of firm fm's poll ending on day: the containing period with the latest start; UNKNOWN when none."""
    ps = [(a, m) for a, b, m in _periods().get(fm, ()) if a <= day <= b]
    return max(ps)[1] if ps else "UNKNOWN"


def polls():
    """([(election, firm, end, {wiki party: pct})], {election: {wiki party: ballot}}, {election: day})."""
    out, ballot, day = [], defaultdict(dict), {}
    key = None
    with open(SRC, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            end = date.fromisoformat(r["end"])
            if r["kind"] == "ballot":
                ballot[r["election"]][r["party"]] = float(r["pct"])
                day[r["election"]] = end
                continue
            if not r["pct"]:
                continue
            k = (r["election"], r["firm"], r["end"], r["sample"])
            if k != key or r["party"] in out[-1][3]:
                out.append((r["election"], firm(r["firm"]), end, {}))
                key = k
            out[-1][3][r["party"]] = float(r["pct"])
    return out, ballot, day


def niki_cells():
    """NIKH from the hand-checked files instead of Wikipedia, which lists it in few polls: nikh_polls_2023.csv (May, June
    2023) and the polls of nikh_polls.csv up to the Euro 2024 election day; ballots of nikh_polls (as pollster_record)."""
    import nikh_polls as NP
    ballots = {**NP.BALLOT_2023, "2024/euro": NP.EURO}
    rows = []
    with open(HERE / "nikh_polls_2023.csv", encoding="utf-8") as f:
        rows += [(r["election"], r["firm"], r["end"], r["niki"]) for r in csv.DictReader(f)]
    with open(HERE / "nikh_polls.csv", encoding="utf-8") as f:
        rows += [("2024/euro", r["firm"], r["end"], r["niki"]) for r in csv.DictReader(f)]
    out = []
    for el, fm, end, y in rows:
        d = (ballots[el][0] - date.fromisoformat(end)).days
        if y.strip() and d >= 0 and float(y) >= MIN_PCT:
            out.append((el, firm(fm), "ΝΙΚΗ", d, math.log(ballots[el][1] / float(y)), mode(firm(fm), date.fromisoformat(end))))
    return out


def cells():
    """[(election, firm, party, days before, r, method)] of the vote-estimate polls."""
    ps, ballot, day = polls()
    out = []
    for el, fm, end, row in ps:
        if sum(row.values()) < MIN_SUM:
            continue
        for p, y in row.items():
            b = ballot[el].get(p)
            if p in PARTY and PARTY[p] != "ΝΙΚΗ" and b is not None and b >= MIN_PCT and y >= MIN_PCT:
                out.append((el, fm, PARTY[p], (day[el] - end).days, math.log(b / y), mode(fm, end)))
    return out + niki_cells()


def mean(v):
    return sum(v) / len(v)


def coefficients(cs):
    """[{firm, party, k, h, sd, n_polls, n_el, elections}] sorted by party, firm."""
    by = defaultdict(list)  # (firm, party, election): [r]
    for el, fm, p, _, r, _ in cs:
        by[fm, p, el].append(r)
    em = {key: mean(v) for key, v in by.items()}  # firm's election mean
    allf = defaultdict(list)
    for (fm, p, el), v in em.items():
        allf[p, el].append(v)
    pe = {key: mean(v) for key, v in allf.items()}  # all firms' mean, party and election
    rows = defaultdict(list)
    for (fm, p, el), v in em.items():
        rows[fm, p].append((el, v, v - pe[p, el], len(by[fm, p, el])))
    out = []
    for (fm, p), xs in rows.items():
        ms = [v for _, v, _, _ in xs]
        sd = math.sqrt(sum((m - mean(ms)) ** 2 for m in ms) / (len(ms) - 1)) if len(ms) > 1 else None
        out.append({"firm": fm, "party": p, "k": math.exp(mean(ms)), "h": math.exp(mean([d for _, _, d, _ in xs])),
                    "sd": sd, "n_polls": sum(n for *_, n in xs), "n_el": len(xs),
                    "elections": " ".join(sorted(el for el, *_ in xs))})
    return sorted(out, key=lambda r: (r["party"], r["firm"]))


def party_by_lead(cs):
    """{party: {bucket: (k, polls)}} over all firms; each election one weight within a bucket."""
    by = defaultdict(lambda: defaultdict(list))
    for el, _, p, d, r, _ in cs:
        for lo, hi in BUCKETS:
            if lo <= d <= hi:
                by[p, (lo, hi)][el].append(r)
    out = defaultdict(dict)
    for (p, b), els in by.items():
        out[p][b] = (math.exp(mean([mean(v) for v in els.values()])), sum(len(v) for v in els.values()))
    return out


def shrink(x, n, k, to=0.0):
    return (n * x + k * to) / (n + k)


@cache
def model():
    """The parts of ln k and of the mean square error (see the docstring): {"party": {p}, "mode": {(m, p)}, "n_mode": {(m, p)},
    "fm": {(firm, m, p)}, "bench": {p}, "w_mode": {(m, p)}, "w_fm": {(firm, m, p)}}."""
    by, sq = defaultdict(list), defaultdict(list)
    for el, fm, p, d, r, m in cells():
        if el.endswith("/euro"):  # the forecast is of a national election; European ones err otherwise
            continue
        by[fm, m, p, el].append(r)
        if d <= NEAR:
            sq[fm, m, p, el].append(r * r)
    em = {k: mean(v) for k, v in by.items()}  # firm-method election mean
    allf, els = defaultdict(list), defaultdict(list)
    for (_, _, p, el), v in em.items():
        allf[p, el].append(v)
    pe = {k: mean(v) for k, v in allf.items()}  # all firms' mean, party and election
    for (p, _), v in pe.items():
        els[p].append(v)
    dev, rest = defaultdict(list), defaultdict(list)
    for (fm, m, p, el), v in em.items():
        if m != "UNKNOWN":
            dev[m, p].append(v - pe[p, el])
    md = {k: shrink(mean(v), len(v), K_MODE) for k, v in dev.items()}
    for (fm, m, p, el), v in em.items():
        rest[fm, m, p].append(v - pe[p, el] - md.get((m, p), 0))
    # mean square error of a firm-method relative to all firms' in the same election, so an election everyone missed
    # (PASOK 2012) does not count against the methods and firms that polled then
    se = defaultdict(list)
    for (_, _, p, el), v in sq.items():
        se[p, el].append(mean(v))
    bl, ml, fl = defaultdict(list), defaultdict(list), defaultdict(list)
    for (fm, m, p, el), v in sq.items():
        x = mean(v) / max(mean(se[p, el]), 1e-6)
        bl[p].append(x)
        fl[fm, m, p].append(x)
        if m != "UNKNOWN":
            ml[m, p].append(x)
    bench = {p: mean(v) for p, v in bl.items()}
    wm = {(m, p): shrink(mean(v), len(v), K_MODE, bench[p]) for (m, p), v in ml.items()}
    return {"party": {p: shrink(mean(v), len(v), K_EL) for p, v in els.items()}, "mode": md,
            "n_mode": {k: len(v) for k, v in dev.items()}, "fm": {k: shrink(mean(v), len(v), K_EL) for k, v in rest.items()},
            "bench": bench, "w_mode": wm,
            "w_fm": {(fm, m, p): shrink(mean(v), len(v), K_EL, wm.get((m, p), bench[p])) for (fm, m, p), v in fl.items()}}


def coef(fm, m, p):
    """k (ballot / poll) of firm fm's polls by method m for party p; 1 for a party never seen."""
    M = model()
    if p not in M["party"]:
        return 1.0
    return math.exp(M["party"][p] + M["mode"].get((m, p), 0) + M["fm"].get((fm, m, p), 0))


def weight(fm, m, p):
    """Weight of firm fm's polls by method m for party p in a poll average (1 = an average firm; 1 for a party never seen)."""
    M = model()
    if p not in M["bench"]:
        return 1.0
    mse = M["w_fm"].get((fm, m, p), M["w_mode"].get((m, p), M["bench"][p]))
    return min(W_CLIP, max(1 / W_CLIP, M["bench"][p] / mse))


def governing():
    """{role: {election: {bucket or None (all): (k, polls)}}}, role 0 the party in government, 1 the main opposition."""
    out, cs = {0: defaultdict(dict), 1: defaultdict(dict)}, cells()
    for role in out:
        for el, ps in GOV.items():
            for b in (*BUCKETS, None):
                by = defaultdict(list)
                for e, fm, p, d, r, _ in cs:
                    if e == el and p == ps[role] and (b is None or b[0] <= d <= b[1]):
                        by[fm].append(r)
                if by:
                    out[role][el][b] = (math.exp(mean([mean(v) for v in by.values()])), sum(map(len, by.values())))
    return out


def current():
    """{firm: method} of the firms in nikh_polls.csv, by their latest poll."""
    with open(HERE / "nikh_polls.csv", encoding="utf-8") as f:
        rs = sorted((r["end"], firm(r["firm"])) for r in csv.DictReader(f))
    return {fm: mode(fm, date.fromisoformat(end)) for end, fm in rs}


def method_lines():
    M = model()
    ps = ["ΝΔ", "ΠΑΣΟΚ", "ΣΥΡΙΖΑ", "ΚΚΕ", "Ελληνική Λύση", "Πλεύση Ελευθερίας", "ΜέΡΑ25", "ΝΙΚΗ", "Φωνή Λογικής"]
    out = ["", "Μέθοδος: συντελεστής της μεθόδου μέσα στις ίδιες εκλογές (1 = όπως οι άλλες εταιρείες), (εταιρεία x εκλογές)",
           f"{'κόμμα':20}" + "".join(f"{m:>15}" for m in MODES[:4])]
    for p in ps:
        out.append(f"{p:20}" + "".join(f"{math.exp(M['mode'][m, p]):8.3f} ({M['n_mode'][m, p]:3})" if (m, p) in M["mode"]
                                       else f"{'':15}" for m in MODES[:4]))
    out += ["", "Εταιρείες σήμερα, με τη μέθοδο της τελευταίας δημοσκόπησης: k / βάρος",
            f"{'εταιρεία':24}" + "".join(f"{p[:10]:>12}" for p in ps)]
    for fm, m in sorted(current().items()):
        out.append(f"{fm + ' ' + m:24}" + "".join(f"{coef(fm, m, p):6.2f}/{weight(fm, m, p):4.2f}" + " " for p in ps))
    return out


def governing_lines():
    g = governing()
    head = "".join(f"{f'{lo}-{hi}' if hi < 10**4 else f'{lo}+':>13}" for lo, hi in BUCKETS) + f"{'όλες':>13}"
    out = []
    for role, label in ((0, "Κόμμα της κυβέρνησης"), (1, "Αξιωματική αντιπολίτευση")):
        out += ["", f"{label}: k ανά μέρες πριν τις εκλογές (δημοσκοπήσεις)", f"{'εκλογές':11}{'κόμμα':8}{head}"]
        logs = defaultdict(list)
        for el, ps in GOV.items():
            row = g[role][el]
            out.append(f"{el:11}{ps[role]:8}" + "".join(f"{row[b][0]:7.3f} ({row[b][1]:3})" if b in row else f"{'':13}"
                                                         for b in (*BUCKETS, None)))
            for b, (k, _) in row.items():
                logs[b].append(math.log(k))
        out.append(f"{'μέσος [k<1]':19}" + "".join(f"{math.exp(mean(logs[b])):7.3f} [{sum(x < 0 for x in logs[b])}/{len(logs[b])}]"
                                                   if logs[b] else f"{'':13}" for b in (*BUCKETS, None)))
    return out


def main():
    cs = cells()
    rows = coefficients(cs)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["firm", "party", "k", "h", "sd_log", "n_polls", "n_elections", "elections"])
        for r in rows:
            w.writerow([r["firm"], r["party"], f"{r['k']:.3f}", f"{r['h']:.3f}", "" if r["sd"] is None else f"{r['sd']:.3f}",
                        r["n_polls"], r["n_el"], r["elections"]])
    lead = party_by_lead(cs)
    ps = polls()[0]
    raw = sum(sum(row.values()) < MIN_SUM for *_, row in ps)
    lines = [f"Συντελεστές αποτέλεσμα / δημοσκόπηση: {len(cs)} τιμές κόμματος από {len(ps) - raw} δημοσκοπήσεις της Wikipedia "
             f"({raw} με ωμή πρόθεση ψήφου έξω) και {len(niki_cells())} ελεγμένες τιμές της ΝΙΚΗΣ,",
             f"{len({el for el, *_ in cs})} εκλογές 2007-2024, {len({fm for _, fm, *_ in cs})} εταιρείες. k = αποτέλεσμα / δημοσκόπηση,",
             "h = ίδιο προς τις άλλες εταιρείες στις ίδιες εκλογές (house effect). Πίνακας ανά κόμμα: εταιρείες με >= 2 εκλογές.", ""]
    lines.append("k ανά κόμμα (όλες οι εταιρείες) και πόσες μέρες πριν τις εκλογές:")
    lines.append(f"{'κόμμα':22}" + "".join(f"{f'{lo}-{hi}' if hi < 10**4 else f'{lo}+':>14}" for lo, hi in BUCKETS))
    for p in sorted(lead, key=lambda p: -sum(n for _, n in lead[p].values())):
        lines.append(f"{p:22}" + "".join(f"{lead[p][b][0]:>8.2f} ({lead[p][b][1]:>3})" if b in lead[p] else f"{'':>14}"
                                          for b in BUCKETS))
    for p in sorted({r["party"] for r in rows}, key=lambda p: (-sum(r["n_polls"] for r in rows if r["party"] == p), p)):
        rs = sorted((r for r in rows if r["party"] == p and r["n_el"] >= 2), key=lambda r: r["h"])
        if not rs:
            continue
        lines += ["", f"{p}: εταιρεία, k, h, sd(log) μεταξύ εκλογών, δημοσκοπήσεις, εκλογές"]
        lines += [f"  {r['firm']:18}{r['k']:6.2f}{r['h']:6.2f}{r['sd']:7.2f}{r['n_polls']:6}  {r['elections']}" for r in rs]
    lines += method_lines() + governing_lines()
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
