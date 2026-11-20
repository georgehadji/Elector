"""Leading parties per polling venue and per wider area, overall and within each political bloc,
nationwide, for every election in config.ELECTIONS.

Usage: python -I -X utf8 analysis/venue_parties.py
Reads the ministry spreadsheets "Εκλογικά τμήματα με κατάστημα ψηφοφορίας" from analysis/venues_xls/
(ypes.gr, eklogika-tmimata; see XLS). Writes analysis/venue_parties/*.csv and summary.md.

Levels:
- venue (κατάστημα ψηφοφορίας): the spreadsheet gives each station (constituency, number) its venue.
  The spreadsheet's constituency codes differ from the results site's, so each spreadsheet
  constituency is matched to the database one whose (station number, municipal unit) pairs it shares
  most. A station is used only when its municipal unit agrees too. A venue is identified across
  elections by (constituency, municipal unit, normalised venue text), so a venue whose text changed
  between elections shows up as two venues.
- community (ELSTAT 2021 local community, via area_match) and municipal unit (δημοτική ενότητα).

Blocs are a default grouping and a judgement call: edit BLOCS. Parties not listed count as "Λοιπά".
Only public aggregate results are used.
"""
import csv
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import DB, ELECTION_NAMES, HERE, PARTY_SHORT
from matching import boundaries, ep_label, label, stems

SRC = Path(__file__).resolve().parent / "venues_xls"
DEST = Path(__file__).resolve().parent / "venue_parties"
ELECTIONS = list(ELECTION_NAMES)
# election -> (file, column of station number, municipal unit, venue); constituency name is column 1.
XLS = {"2019": ("eklogika_tmimata_boyl2019.xls", 2, 6, 10),
       "2023/may": ("EklogikaTMHMATAmeKATASTHMApsifofor-20230520-1939.xls", 2, 6, 10),
       "2023/june": ("EklogikaTMHMATAmeKATASTHMApsifofor-VouleftikesIouniou2023-20230624-1317.xls", 2, 6, 10),
       "2024/euro": ("eklogikatmimata_08062024_1420.xlsx", 2, 7, 15)}

BLOCS = {  # party id -> bloc; ids are stable across elections
    "Αριστερά": [3, 122, 123, 44, 100],                       # ΚΚΕ, ΜέΡΑ25, Πλεύση, ΑΝΤΑΡΣΥΑ, ΛΑΕ
    "Κεντροαριστερά": [4, 106, 166, 28],                       # ΣΥΡΙΖΑ, ΠΑΣΟΚ, Νέα Αριστερά, Οικολόγοι
    "Κεντροδεξιά": [2, 60, 164],                               # ΝΔ, Δημιουργία/Τζήμερος, Δημοκράτες
    "Δεξιά της ΝΔ": [108, 131, 157, 41, 158, 153, 163, 113],   # Ελ. Λύση, ΝΙΚΗ, Σπαρτιάτες, ΧΑ, Φωνή Λογικής,
}                                                              # Πατρ. Συνασπισμός, Πατριώτες, Ελλ. Συνέλευσις
BLOC_OF = {pid: b for b, pids in BLOCS.items() for pid in pids}
BLOC_NAMES = list(BLOCS) + ["Λοιπά"]
EXTRA_SHORT = {166: "Νέα Αριστερά", 164: "Δημοκράτες", 163: "Πατριώτες", 153: "Πατρ. Συνασπισμός",
               60: "Δημιουργία (Τζήμερος)", 44: "ΑΝΤΑΡΣΥΑ", 135: "Συμμαχία Ανατροπής", 169: "ΚΟΣΜΟΣ",
               73: "ΚΙΕΦ"}


def short(pid, names):
    return PARTY_SHORT.get(pid) or EXTRA_SHORT.get(pid) or names.get(pid, str(pid))[:30]


def sheet_rows(election):
    """[(spreadsheet constituency, station number, municipal unit, venue text)] of one election."""
    name, c_seq, c_den, c_venue = XLS[election]
    path = SRC / name
    if path.suffix == ".xlsx":
        rows = list(openpyxl.load_workbook(path, read_only=True).worksheets[0].iter_rows(values_only=True))
    else:
        s = xlrd.open_workbook(path).sheet_by_index(0)
        rows = [s.row_values(i) for i in range(s.nrows)]
    out = []
    for r in rows[1:]:
        try:
            seq = int(float(r[c_seq]))
        except (TypeError, ValueError):
            continue  # blank or footer line
        out.append((str(r[1]).strip(), seq, str(r[c_den] or "").strip(), str(r[c_venue] or "").strip()))
    return out


def venue_of_station(db, election):
    """{tm_id: (venue key, venue text)}, plus counts for the report."""
    rows = sheet_rows(election)
    db_den = {tm: stems(den) for tm, den in db.execute(
        "SELECT tm_id, den_descr FROM station WHERE election=? AND kind='Κ'", (election,))}
    by_ep = defaultdict(set)
    for tm, den in db_den.items():
        by_ep[tm // 10000].add((tm % 10000, den))
    sheet_eps = defaultdict(list)
    for ep_name, seq, den, venue in rows:
        sheet_eps[ep_name].append((seq, den, venue))
    out, unmatched_eps, den_mismatch = {}, [], 0
    for ep_name, st in sheet_eps.items():
        pairs = {(seq, stems(den)) for seq, den, _ in st}
        ep, hits = max(((ep, len(pairs & p)) for ep, p in by_ep.items()), key=lambda x: x[1])
        if hits < 0.5 * len(pairs):
            unmatched_eps.append(ep_name)
            continue
        for seq, den, venue in st:
            tm = ep * 10000 + seq
            if tm not in db_den or db_den[tm] != stems(den):
                den_mismatch += 1
                continue
            out[tm] = ((ep, db_den[tm], vnorm(venue)), venue)
    return out, {"γραμμές xls": len(rows), "τμήματα με κατάστημα": len(out), "τμήματα βάσης": len(db_den),
                 "διαφορά δημ. ενότητας": den_mismatch, "περιφέρειες xls χωρίς αντιστοίχιση": unmatched_eps}


def vnorm(s):
    """Venue text for comparison: no accents, capitals, punctuation as spaces. Unlike matching.norm,
    it keeps leading numbers: "1ο" and "2ο ΓΥΜΝΑΣΙΟ" are different venues."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").upper()
    return re.sub(r"\s+", " ", re.sub(r"[^\w]", " ", s)).strip()


# Words every venue shares (as case-free stems); they say nothing about which venue it is.
GENERIC = set(stems(
    "ΔΗΜΟΤΙΚΟ ΣΧΟΛΕΙΟ ΣΧΟΛ ΔΗΜ ΟΛΟΗΜΕΡΟ ΓΥΜΝΑΣΙΟ ΛΥΚΕΙΟ ΓΕΝΙΚΟ ΗΜΕΡΗΣΙΟ ΕΣΠΕΡΙΝΟ ΕΠΑΛ ΝΗΠΙΑΓΩΓΕΙΟ "
    "ΜΕΙΟΝΟΤΙΚΟ ΠΡΩΗΝ ΚΤΙΡΙΟ ΚΤΗΡΙΟ ΑΙΘΟΥΣΑ ΠΑΡΑΡΤΗΜΑ ΚΟΙΝΟΤΗΤΑ ΤΟΠΙΚΗ ΔΗΜΟΣ ΤΟΥ ΤΗΣ ΚΑΙ ΤΟ Η "
    "ΚΟΙΝΟΤΙΚΟ ΚΑΤΑΣΤΗΜΑ ΓΡΑΦΕΙΟ ΠΟΛΙΤΙΣΤΙΚΟΣ ΣΥΛΛΟΓΟΣ ΚΕΝΤΡΟ ΠΛΑΤΕΙΑ ΟΔΟΣ ΤΚ ΙΣΟΓΕΙΟ ΠΟΛΛΑΠΛΩΝ ΧΡΗΣΕΩΝ"))
ORDINAL = re.compile(r"\d+(Ο|ΟΣ|Η|ΗΣ|ΟΝ|ΟΥ)?")


def features(key_text):
    """(ordinal or "", set of distinctive word stems) of a vnorm'ed venue text."""
    words = key_text.split()
    ordinal = words[0] if words and ORDINAL.fullmatch(words[0]) else ""
    return ordinal, {s for w in words if not w.isdigit() for s in stems(w)} - GENERIC


LINKS = []  # (election, venue text, reference venue text, how) for venue_links.csv


REFERENCE = "2023/june"  # venues of this election are the canonical list
MIN_SIMILARITY = 0.5


def link_venues(v_of_all, checks):
    """Rewrite each election's venue keys to the matching REFERENCE venue, in place.
    Exact normalised text first; otherwise, inside the same constituency and municipal unit, the
    reference venue with the same ordinal ("1ο", or none on both) and the highest overlap of
    distinctive word stems (Jaccard >= MIN_SIMILARITY). Unmatched venues keep their own key
    (moved, new or closed venues)."""
    ref = {k for k, _ in v_of_all[REFERENCE].values()}
    by_unit = defaultdict(list)
    for k in ref:
        by_unit[k[:2]].append((k, *features(k[2])))
    for e, v_of in v_of_all.items():
        if e == REFERENCE:
            checks[ELECTION_NAMES[e]]["καταστήματα: ίδια περιγραφή / παρόμοια / χωρίς ζεύγος"] = f"{len(ref)} / 0 / 0"
            continue
        link, n = {}, Counter()
        for k in {k for k, _ in v_of.values()}:
            if k in ref:
                link[k] = k
                n["exact"] += 1
                continue
            first, ws = features(k[2])
            best = max(((len(ws & rw) / len(ws | rw), rk) for rk, rf, rw in by_unit[k[:2]]
                        if rf == first and ws & rw), default=(0, None))
            link[k] = best[1] if best[0] >= MIN_SIMILARITY else k
            n["similar" if best[0] >= MIN_SIMILARITY else "none"] += 1
        ref_text = {k: t for k, t in v_of_all[REFERENCE].values()}
        seen = set()
        for tm, (k, text) in v_of.items():
            v_of[tm] = (link[k], text)
            if k not in seen and link[k] != k:
                seen.add(k)
                LINKS.append({"election": ELECTION_NAMES[e], "κατάστημα": text,
                              "κατάστημα αναφοράς (Ιούνιος 2023)": ref_text[link[k]]})
        checks[ELECTION_NAMES[e]]["καταστήματα: ίδια περιγραφή / παρόμοια / χωρίς ζεύγος"] = (
            f"{n['exact']} / {n['similar']} / {n['none']}")


def ranked(votes, valid, names):
    """votes {pid: n} -> rows sorted by votes, with overall rank, bloc and rank inside the bloc."""
    rows, in_bloc = [], Counter()
    for rank, (pid, n) in enumerate(sorted(votes.items(), key=lambda x: -x[1]), 1):
        bloc = BLOC_OF.get(pid, "Λοιπά")
        in_bloc[bloc] += 1
        rows.append({"party_id": pid, "party": short(pid, names), "votes": n,
                     "share": round(100 * n / valid, 2) if valid else 0, "rank": rank,
                     "bloc": bloc, "rank_in_bloc": in_bloc[bloc]})
    return rows


def summary_row(key, election, valid, rows):
    """One wide row: top 3 overall, each bloc's share and its two leading parties."""
    out = {**key, "election": ELECTION_NAMES[election], "valid": valid}
    for i in range(3):
        r = rows[i] if i < len(rows) else None
        out[f"{i + 1}ο"] = f"{r['party']} {r['share']:.1f}%" if r else ""
    for b in BLOC_NAMES:
        br = [r for r in rows if r["bloc"] == b]
        out[f"{b} %"] = round(sum(r["share"] for r in br), 1)
        out[f"{b} 1ος"] = f"{br[0]['party']} {br[0]['share']:.1f}%" if br else ""
        out[f"{b} 2ος"] = f"{br[1]['party']} {br[1]['share']:.1f}%" if len(br) > 1 else ""
    return out


def write(name, rows):
    if not rows:
        return
    with open(DEST / name, "w", encoding="utf-8-sig", newline="") as f:  # BOM: Excel reads Greek
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    DEST.mkdir(exist_ok=True)
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    names = {}
    for e in ELECTIONS:  # a later election's name wins
        names.update(db.execute("SELECT party_id, name FROM party WHERE election=?", (e,)).fetchall())
    ep_name = {ep: ep_label(n) for ep, n in db.execute("SELECT ep_id, name FROM ep WHERE election='2023/june'")}
    _, comm_by_code, _ = boundaries()
    geo = json.loads((HERE / "data" / "venues_geo.json").read_text(encoding="utf-8"))

    def new():
        return {"valid": 0, "v": Counter(), "n": 0}

    venues, comms, dens = defaultdict(new), defaultdict(new), defaultdict(new)
    venue_text, venue_comm, venue_den, checks = defaultdict(Counter), defaultdict(Counter), {}, {}
    v_of_all = {}
    for e in ELECTIONS:
        v_of_all[e], checks[ELECTION_NAMES[e]] = venue_of_station(db, e)
    link_venues(v_of_all, checks)
    for e in ELECTIONS:
        v_of = v_of_all[e]
        meta = {}  # tm -> accumulators this station adds to
        for tm, ep, den, valid, comm in db.execute("""
                SELECT s.tm_id, s.ep_id, s.den_descr, s.valid, a.comm_code FROM station s
                LEFT JOIN area_match a ON a.election = s.election AND a.tm_id = s.tm_id
                WHERE s.election=? AND s.kind='Κ'""", (e,)):
            accs = [dens[e, ep, den]] + ([comms[e, ep, comm]] if comm else [])
            if tm in v_of:
                key, text = v_of[tm]
                accs.append(venues[e, key])
                venues[e, key]["n"] += 1
                venue_text[key][text] += 1
                venue_den[key] = den
                if comm:
                    venue_comm[key][comm] += 1
            for a in accs:
                a["valid"] += valid or 0
            meta[tm] = accs
        for tm, pid, n in db.execute("SELECT tm_id, party_id, votes FROM party_votes WHERE election=? AND votes > 0",
                                     (e,)):
            for a in meta.get(tm, ()):
                a["v"][pid] += n

    # Stable venue ids, ordered by constituency, municipal unit, venue.
    vid = {k: i for i, k in enumerate(sorted(venue_text, key=lambda k: (k[0], venue_den[k], k[2])), 1)}
    venue_info = {}
    for k, i in vid.items():
        texts = [t for t, _ in venue_text[k].most_common()]
        g = next((geo[t] for t in texts if geo.get(t)), None)
        comm = venue_comm[k].most_common(1)[0][0] if venue_comm[k] else ""
        venue_info[k] = {"id": i, "περιφέρεια": ep_name[k[0]], "δημ. ενότητα": venue_den[k],
                         "κοινότητα": label(comm_by_code[comm]) if comm else "", "κοινότητα κωδ.": comm,
                         "κατάστημα": texts[0], "lat": g["lat"] if g else "", "lon": g["lon"] if g else ""}

    venue_rows, long_rows = [], []
    for (e, k), a in sorted(venues.items(), key=lambda x: (vid[x[0][1]], ELECTIONS.index(x[0][0]))):
        rows = ranked(a["v"], a["valid"], names)
        venue_rows.append(summary_row({**venue_info[k], "τμήματα": a["n"]}, e, a["valid"], rows))
        long_rows += [{"id": vid[k], "election": ELECTION_NAMES[e], **r} for r in rows]
    comm_rows = [summary_row({"περιφέρεια": ep_name[ep], "κοινότητα": label(comm_by_code[c]), "κοινότητα κωδ.": c},
                             e, a["valid"], ranked(a["v"], a["valid"], names))
                 for (e, ep, c), a in sorted(comms.items(), key=lambda x: (x[0][1], x[0][2], ELECTIONS.index(x[0][0])))]
    den_rows = [summary_row({"περιφέρεια": ep_name[ep], "δημ. ενότητα": d}, e, a["valid"],
                            ranked(a["v"], a["valid"], names))
                for (e, ep, d), a in sorted(dens.items(), key=lambda x: (x[0][1], x[0][2], ELECTIONS.index(x[0][0])))]

    in_all = sum(1 for k in vid if all((e, k) in venues for e in ELECTIONS))
    write("venue_links.csv", LINKS)
    write("venues.csv", venue_rows)
    write("venue_parties_long.csv", long_rows)
    write("communities.csv", comm_rows)
    write("municipal_units.csv", den_rows)
    (DEST / "summary.md").write_text(report(venues, dens, ep_name, names, checks, len(vid), in_all), encoding="utf-8")
    for el, c in checks.items():
        print(el, c)
    print(f"venues {len(vid)} (in all {len(ELECTIONS)} elections: {in_all}), communities "
          f"{len({k[1:] for k in comms})}, municipal units {len({k[1:] for k in dens})}\nwrote {DEST}")


def leaders(groups, election, names, top=6):
    """Across areas of one election: who is 1st and 2nd overall and inside each bloc (count of areas)."""
    first, second = Counter(), Counter()
    bloc_first, bloc_second, bloc_share = defaultdict(Counter), defaultdict(Counter), defaultdict(list)
    for (e, *_), a in groups.items():
        if e != election or not a["valid"]:
            continue
        rows = ranked(a["v"], a["valid"], names)
        first[rows[0]["party"]] += 1
        if len(rows) > 1:
            second[rows[1]["party"]] += 1
        for b in BLOCS:
            br = [r for r in rows if r["bloc"] == b]
            if br:
                bloc_first[b][br[0]["party"]] += 1
            if len(br) > 1:
                bloc_second[b][br[1]["party"]] += 1
            bloc_share[b].append(sum(r["share"] for r in br))

    def fmt(c):
        return ", ".join(f"{p} {n}" for p, n in c.most_common(top))
    lines = ["| Χώρος | 1ο κόμμα (περιοχές) | 2ο κόμμα (περιοχές) |", "|---|---|---|",
             f"| Σύνολο | {fmt(first)} | {fmt(second)} |"]
    for b in BLOCS:
        s = sorted(bloc_share[b])
        med = s[len(s) // 2] if s else 0
        lines.append(f"| {b} (διάμεσο {med:.1f}%) | {fmt(bloc_first[b])} | {fmt(bloc_second[b])} |")
    return lines


def report(venues, dens, ep_name, names, checks, n_venues, in_all):
    out = ["# Κόμματα ανά κατάστημα ψηφοφορίας και περιοχή", "",
           "Παράγεται από `analysis/venue_parties.py`. Μόνο δημόσια aggregate αποτελέσματα (ανεπίσημα).", "",
           "Χώροι (προεπιλογή, αλλάζει στο `BLOCS`): " + "; ".join(
               f"**{b}**: " + ", ".join(short(p, names) for p in pids) for b, pids in BLOCS.items()) + ".", "",
           ("Κάθε κελί: κόμμα και σε πόσες περιοχές ήταν 1ο ή 2ο, συνολικά ή μέσα στον χώρο. "
            "Διάμεσο: τυπικό ποσοστό του χώρου ανά περιοχή."), "",
           (f"Καταστήματα: {n_venues}, από τα οποία {in_all} και στις 4 εκλογές. Κατάστημα αναφοράς: "
            f"Ιούνιος 2023· οι άλλες εκλογές συνδέονται με ίδια ή παρόμοια περιγραφή στην ίδια δημ. ενότητα."), "",
           ("| Εκλογή | Γραμμές xls | Τμήματα με κατάστημα | Τμήματα βάσης | Διαφορά δημ. ενότητας | "
            "Περιφέρειες xls χωρίς αντιστοίχιση | Καταστήματα: ίδια / παρόμοια / χωρίς ζεύγος |"),
           "|---|---|---|---|---|---|---|"]
    out += [f"| {e} | " + " | ".join(str(v) for v in c.values()) + " |" for e, c in checks.items()]
    out += ["", "## Όλη η χώρα", ""]
    for e in ELECTIONS:
        n = sum(1 for k in venues if k[0] == e)
        out += [f"**Καταστήματα, {ELECTION_NAMES[e]}** ({n})", "", *leaders(venues, e, names), ""]
    for ep in sorted(ep_name, key=ep_name.get):
        out += [f"## {ep_name[ep]}", ""]
        for e in ELECTIONS:
            group = {k: v for k, v in venues.items() if k[1][0] == ep}
            n = sum(1 for k in group if k[0] == e)
            out += [f"**Καταστήματα, {ELECTION_NAMES[e]}** ({n})", "", *leaders(group, e, names), ""]
        for e in ELECTIONS:
            group = {k: v for k, v in dens.items() if k[1] == ep}
            n = sum(1 for k in group if k[0] == e)
            out += [f"**Δημοτικές ενότητες, {ELECTION_NAMES[e]}** ({n})", "", *leaders(group, e, names), ""]
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
