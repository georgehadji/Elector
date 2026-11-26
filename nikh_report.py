"""NIKH (party 131) in the 9 constituencies where it elected an MP in June 2023.

Usage: python -I nikh_report.py <venues.xls>
Compares May 2023 (2.92%, no seats) with June 2023 (3.70%, 10 seats) per constituency,
municipal unit and polling station; adds the May preference votes of each elected MP
(June 2023 per-station preference votes are not published on the results site).
Writes out/NIKH_eklegmenoi_2023.html (next to the maps) and exports/NIKH_2023_ana_dhm_enotita.csv.
"""
import csv
import html
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # python -I drops the script dir
import xlrd

from config import DB, ELECTED, HERE, NIKH
from matching import norm
from stations_map import XLS_EP, venue_parts
from web import fill, meta, secure

MAY, JUN = "2023/may", "2023/june"


def strip(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn")


def pct(a, b):
    return 100 * a / b if b else 0.0


def shares(db, election, ep, by):
    """{key: (nikh, valid)} over ordinary stations located in the constituency; by = 'den' or 'tm'."""
    col = {"den": "s.den_descr", "tm": "s.tm_id"}[by]
    rows = db.execute(f"""
        SELECT {col}, SUM(COALESCE(p.votes,0)), SUM(COALESCE(s.valid,0)) FROM station s
        LEFT JOIN party_votes p ON p.election=s.election AND p.tm_id=s.tm_id AND p.party_id=?
        WHERE s.election=? AND s.ep_id=? AND s.ep_geo=? AND s.kind='Κ' GROUP BY 1""",
        (NIKH, election, ep, ep)).fetchall()
    return {k: (n, v) for k, n, v in rows}


def total(db, election, ep):
    n, v = db.execute("""SELECT SUM(COALESCE(p.votes,0)), SUM(COALESCE(s.valid,0)) FROM station s
        LEFT JOIN party_votes p ON p.election=s.election AND p.tm_id=s.tm_id AND p.party_id=?
        WHERE s.election=? AND s.ep_id=?""", (NIKH, election, ep)).fetchone()
    return n or 0, v or 0


def main(xls):
    db = sqlite3.connect(DB)
    sheet = xlrd.open_workbook(xls).sheet_by_index(0)
    venue_rows = [sheet.row_values(i) for i in range(1, sheet.nrows)]
    md = ["# ΝΙΚΗ: οι 9 περιφέρειες με εκλεγμένο βουλευτή (Ιούνιος 2023)", "",
          "Πηγή: ΥΠΕΣ (ekloges-prev.singularlogic.eu), αποτελέσματα ανά εκλογικό τμήμα. "
          "Ποσοστό = ψήφοι ΝΙΚΗ / έγκυρα. Μάιος 2023: 2,92% πανελλαδικά, εκτός Βουλής. "
          "Ιούνιος 2023: 3,70%, 10 έδρες. Τον Ιούνιο δεν δημοσιεύτηκαν σταυροί ανά τμήμα, "
          "γι' αυτό οι σταυροί είναι του Μαΐου.", "",
          "| Περιφέρεια | Βουλευτής | Μάιος % | Ιούνιος % | Δ μον. | Ψήφοι Ιουν. | Σταυροί Μαΐου (θέση) |",
          "|---|---|---:|---:|---:|---:|---|"]
    detail, csv_rows = [], []
    for ep, surname in ELECTED.items():
        name = db.execute("SELECT name FROM ep WHERE election=? AND ep_id=?", (JUN, ep)).fetchone()[0]
        (mn, mv), (jn, jv) = total(db, MAY, ep), total(db, JUN, ep)
        cands = db.execute("""SELECT c.name, COALESCE(t.votes,0) FROM candidate c
            LEFT JOIN ep_total t USING(election, ep_id, party_id, cand_id)
            WHERE c.election=? AND c.ep_id=? AND c.party_id=? ORDER BY 2 DESC""", (MAY, ep, NIKH)).fetchall()
        mp = next(((i, n, v) for i, (n, v) in enumerate(cands, 1) if strip(surname) in strip(n)), None)
        june = [n for (n,) in db.execute("SELECT name FROM candidate WHERE election=? AND ep_id=? AND party_id=?",
                                          (JUN, ep, NIKH)) if strip(surname) in strip(n)]
        mp_name = mp[1] if mp else (june[0] if june else surname)
        cross = f"{mp[2]:,} ({mp[0]}η/{len(cands)})" if mp else "νέος/α υποψήφιος/α τον Ιούνιο"
        if not mp:  # may have run in another constituency in May
            for oep, oname in db.execute("""SELECT c.ep_id, e.name FROM candidate c JOIN ep e USING(election, ep_id)
                    WHERE c.election=? AND c.party_id=? AND c.ep_id<>?""", (MAY, NIKH, ep)).fetchall():
                other = db.execute("""SELECT c.name, COALESCE(t.votes,0) FROM candidate c
                    LEFT JOIN ep_total t USING(election, ep_id, party_id, cand_id)
                    WHERE c.election=? AND c.ep_id=? AND c.party_id=? ORDER BY 2 DESC""", (MAY, oep, NIKH)).fetchall()
                hit = next(((i, v) for i, (n, v) in enumerate(other, 1) if strip(n) == strip(mp_name)), None)
                if hit:
                    cross = f"{hit[1]:,} ({hit[0]}η/{len(other)}) στην περιφέρεια {oname}"
                    break
        md.append(f"| {name} | {mp_name} | {pct(mn, mv):.2f} | {pct(jn, jv):.2f} | "
                  f"{pct(jn, jv) - pct(mn, mv):+.2f} | {jn:,} | {cross} |")

        may_den, jun_den = shares(db, MAY, ep, "den"), shares(db, JUN, ep, "den")
        dens = sorted(jun_den, key=lambda d: -pct(*jun_den[d]))
        detail += [f"## {name}: {mp_name}", "",
                   f'<p><a href="2023-june_{ep}_tm_131-0.html">Χάρτης ανά εκλογικό κατάστημα</a></p>', "",
                   "Σταυροί ΝΙΚΗ Μαΐου: " + ", ".join(f"{n} {v:,}" for n, v in cands[:4]), "",
                   "| Δημ. ενότητα | Μάιος % | Ιούνιος % | Δ | Ψήφοι Ιουν. |", "|---|---:|---:|---:|---:|"]
        for d in dens:
            jd, md_ = jun_den[d], may_den.get(d, (0, 0))
            csv_rows.append([name, mp_name, d, md_[0], md_[1], round(pct(*md_), 2), jd[0], jd[1], round(pct(*jd), 2)])
            if jd[1] >= 500:  # tiny units are noise in the report; all are in the CSV
                detail.append(f"| {d} | {pct(*md_):.2f} | {pct(*jd):.2f} | {pct(*jd) - pct(*md_):+.2f} | {jd[0]:,} |")

        # Top stations (≥100 valid). Venue names come from the May spreadsheet, used only
        # when the station kept the same electoral district between May and June.
        ekd = dict(db.execute("SELECT tm_id, ekd_id FROM station WHERE election=? AND ep_id=?", (MAY, ep)))
        ekd_j = dict(db.execute("SELECT tm_id, ekd_id FROM station WHERE election=? AND ep_id=?", (JUN, ep)))
        venue = {int(r[2]): venue_parts(r[10])[0] for r in venue_rows
                 if norm(r[1]) == norm(XLS_EP.get(name, name))}
        info = dict((tm, (den, e)) for tm, den, e in db.execute(
            "SELECT tm_id, den_descr, ekd_descr FROM station WHERE election=? AND ep_id=?", (JUN, ep)))
        st = [(tm, n, v) for tm, (n, v) in shares(db, JUN, ep, "tm").items() if v >= 100]
        st.sort(key=lambda r: -pct(r[1], r[2]))
        detail += ["", "Κορυφαία τμήματα Ιουνίου (≥100 έγκυρα):", "",
                   "| Τμ. | Δημ. ενότητα | Εκλ. διαμέρισμα | Κατάστημα | Ψήφοι | % |", "|---:|---|---|---|---:|---:|"]
        for tm, n, v in st[:10]:
            seq = tm - ep * 10000
            ven = venue.get(seq, "") if ekd.get(tm) == ekd_j.get(tm) else ""
            detail.append(f"| {seq} | {info[tm][0]} | {info[tm][1]} | {ven} | {n} | {pct(n, v):.1f} |")
        detail.append("")

    md += ["", "Σημ.: η 10η έδρα (Επικρατείας, χωρίς περιφέρεια) ανήκε στον Γ. Αποστολάκη. Παραιτήθηκε για πολιτικούς λόγους και "
           "την πήρε ο Αθανάσιος Ρακοβαλής. Οι βουλευτές Νικόλαος Βρεττός και Νικόλαος Παπαδόπουλος διαγράφηκαν από το κόμμα και κράτησαν τις έδρες τους.",
           '<p><a href="index.html">Όλοι οι χάρτες</a> · <a href="../exports/NIKH_2023_ana_dhm_enotita.csv">'
           'CSV ανά δημοτική ενότητα</a> · <a href="nikh_targets.html">Χάρτης στόχευσης</a> · <a href="nikh_2023-2024.html">Χάρτης 2019–2024</a></p>', ""] + detail
    report = HERE / "out" / "NIKH_eklegmenoi_2023.html"  # next to the maps it links to
    report.write_text(to_html(md, report), encoding="utf-8")
    with open(HERE / "exports" / "NIKH_2023_ana_dhm_enotita.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Περιφέρεια", "Βουλευτής", "Δημ. ενότητα", "Ψήφοι Μάιος", "Έγκυρα Μάιος", "% Μάιος",
                    "Ψήφοι Ιούνιος", "Έγκυρα Ιούνιος", "% Ιούνιος"])
        w.writerows(csv_rows)
    print(f"wrote {report}")


def to_html(lines, path):
    """The report's small markdown subset (#, ##, pipe tables, paragraphs, raw '<' lines) -> one HTML page."""
    body, table, align = [], [], []

    def flush():
        if table:
            head, *rows = table
            cell = lambda tag, c, a: f'<{tag}{" class=n" if a else ""}>{html.escape(c)}</{tag}>'
            body.append("<div class=tw><table><thead><tr>" + "".join(cell("th", c, a) for c, a in zip(head, align))
                        + "</tr></thead><tbody>" + "".join("<tr>" + "".join(cell("td", c, a) for c, a in zip(r, align))
                                                           + "</tr>" for r in rows) + "</tbody></table></div>")
            table.clear()

    for line in lines:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set(line) <= set("|-: "):
                align[:] = [c.endswith(":") for c in cells]
            else:
                table.append(cells)
            continue
        flush()
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("<"):
            body.append(line)  # trusted markup written above
        elif line:
            body.append(f"<p>{html.escape(line)}</p>")
    flush()
    return secure(fill(f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ΝΙΚΗ 2023</title>{meta("ΝΙΚΗ 2023: Μάιος και Ιούνιος", "Η ΝΙΚΗ στις εννέα περιφέρειες όπου εξέλεξε βουλευτή τον Ιούνιο 2023, σε σύγκριση με τον Μάιο, ανά περιφέρεια, δημοτική ενότητα και εκλογικό τμήμα.")}<script>/*THEME_JS*/</script><style>
/*THEME_TOKENS*/
/*SITE_CSS*/
body{{margin:0;font:1rem/1.6 "IBM Plex Sans",system-ui,sans-serif;background:var(--surface);color:var(--ink)}}
main{{--page:1040px;max-width:var(--page);margin:0 auto;padding:var(--space-lg) var(--space-md) 0}}
h1{{font-size:clamp(1.75rem,1.1rem + 2.4vw,2.75rem);line-height:1.1;letter-spacing:-.03em;margin:var(--space-md) 0 var(--space-md)}}
h2{{font-size:1.5rem;line-height:1.2;letter-spacing:-.02em;margin:var(--space-2xl) 0 var(--space-xs)}}
p{{color:var(--ink-2);max-width:68ch}} a{{color:var(--link)}}
.tw{{overflow-x:auto}} table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;margin:var(--space-xs) 0 var(--space-md);font-size:.9375rem}}
th,td{{text-align:left;padding:var(--space-xs) var(--space-sm);border-bottom:1px solid color-mix(in srgb,var(--ink) 10%,var(--surface));vertical-align:top}}
th{{color:var(--ink-2);font-size:.875rem;font-weight:600;border-bottom-color:var(--line)}} .n{{text-align:right;white-space:nowrap}} tbody tr:hover{{background:var(--chip)}}
@media(max-width:639px){{th{{font-size:.8125rem}}td{{font-size:.875rem}}th,td{{padding:var(--space-xs)}}}}
@media print{{h2{{break-after:avoid}} tr{{break-inside:avoid}} a{{color:inherit}}}}
</style></head><body><main id="main">
<!--HEADER-->
{chr(10).join(body)}
<!--FOOTER-->
</main></body></html>"""), path)


if __name__ == "__main__":
    main(sys.argv[1])
