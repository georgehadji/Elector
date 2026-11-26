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

  python -I -X utf8 analysis/pollster_coef.py   -> analysis/pollster_coef.csv, analysis/pollster_coef.txt
"""
import csv
import math
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pollster_record import firm_of  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC = HERE / "nikh_pollerror.csv"
OUT_CSV, OUT_TXT = HERE / "pollster_coef.csv", HERE / "pollster_coef.txt"
MIN_SUM, MIN_PCT = 85.0, 0.5
BUCKETS = ((0, 30), (31, 90), (91, 365), (366, 10**4))
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
            out.append((el, firm(fm), "ΝΙΚΗ", d, math.log(ballots[el][1] / float(y))))
    return out


def cells():
    """[(election, firm, party, days before, r)] of the vote-estimate polls."""
    ps, ballot, day = polls()
    out = []
    for el, fm, end, row in ps:
        if sum(row.values()) < MIN_SUM:
            continue
        for p, y in row.items():
            b = ballot[el].get(p)
            if p in PARTY and PARTY[p] != "ΝΙΚΗ" and b is not None and b >= MIN_PCT and y >= MIN_PCT:
                out.append((el, fm, PARTY[p], (day[el] - end).days, math.log(b / y)))
    return out + niki_cells()


def mean(v):
    return sum(v) / len(v)


def coefficients(cs):
    """[{firm, party, k, h, sd, n_polls, n_el, elections}] sorted by party, firm."""
    by = defaultdict(list)  # (firm, party, election): [r]
    for el, fm, p, _, r in cs:
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
    for el, _, p, d, r in cs:
        for lo, hi in BUCKETS:
            if lo <= d <= hi:
                by[p, (lo, hi)][el].append(r)
    out = defaultdict(dict)
    for (p, b), els in by.items():
        out[p][b] = (math.exp(mean([mean(v) for v in els.values()])), sum(len(v) for v in els.values()))
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
    for p in sorted({r["party"] for r in rows}, key=lambda p: -sum(r["n_polls"] for r in rows if r["party"] == p)):
        rs = sorted((r for r in rows if r["party"] == p and r["n_el"] >= 2), key=lambda r: r["h"])
        if not rs:
            continue
        lines += ["", f"{p}: εταιρεία, k, h, sd(log) μεταξύ εκλογών, δημοσκοπήσεις, εκλογές"]
        lines += [f"  {r['firm']:18}{r['k']:6.2f}{r['h']:6.2f}{r['sd']:7.2f}{r['n_polls']:6}  {r['elections']}" for r in rs]
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
