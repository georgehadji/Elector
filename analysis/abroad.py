"""Voters abroad and postal votes -> out/abroad.html, and the same tables as text on stdout (analysis/abroad.txt).

Abroad (May and June 2023): the stations of the constituency of voters abroad (ep 57), each placed by country and city
in table abroad (fetch.py), grouped by continent, country and city and compared with the whole country.
Postal votes (Euro 2024): the ministry publishes them only as constituency totals, stored by fetch.py as one station of
kind Τ per constituency; compared with the ballot boxes of the same constituency. Abroad, every vote in 2024 was postal.
"Registered" abroad and for postal votes is the list of those who applied, so valid / registered is close to turnout.

  python -I -X utf8 analysis/abroad.py data/stavroi.sqlite > analysis/abroad.txt
"""
import html
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import DB, ELECTION_NAMES, NIKH, OUT, PARTY_SHORT  # noqa: E402
from web import FONTS, common_css, fill, footer, header, meta, secure  # noqa: E402

ABROAD = 57  # constituency of voters abroad
ABROAD_ELECTIONS = ("2023/may", "2023/june")  # the ones with stations abroad and a country for each
EURO = "2024/euro"
PAGE = OUT / "abroad.html"
MIN_SHARE = 2.0  # parties shown: at least this % of the whole country's valid votes, and ΝΙΚΗ

db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else DB)


def groups(e, key, where):
    """{group: {"n": stations, "reg": registered, "valid": valid votes, "votes": {party: votes}}} over the stations of
    election e matching where, grouped by key (SQL over station s and abroad a)."""
    src = "FROM station s LEFT JOIN abroad a ON a.election=s.election AND a.tm_id=s.tm_id"
    out = {g: {"n": n, "reg": r or 0, "valid": v or 0, "votes": {}} for g, n, r, v in db.execute(
        f"SELECT {key}, COUNT(*), SUM(s.registered), SUM(s.valid) {src} WHERE s.election=? AND {where} GROUP BY 1", (e,))}
    for g, pid, v in db.execute(f"SELECT {key}, p.party_id, SUM(p.votes) {src} JOIN party_votes p ON p.election=s.election "
                                f"AND p.tm_id=s.tm_id WHERE s.election=? AND {where} GROUP BY 1, 2", (e,)):
        out[g]["votes"][pid] = v
    return out


def total(e, where="1"):
    return groups(e, "'all'", where)["all"]


def name(e, pid):
    return PARTY_SHORT.get(pid) or db.execute("SELECT name FROM party WHERE election=? AND party_id=?", (e, pid)).fetchone()[0]


def shown(e):
    """Parties with at least MIN_SHARE % of the whole country, by votes, and ΝΙΚΗ."""
    t = total(e)
    return [p for p, v in sorted(t["votes"].items(), key=lambda x: -x[1]) if 100 * v / t["valid"] >= MIN_SHARE or p == NIKH]


def share(g, pid):
    return 100 * g["votes"].get(pid, 0) / g["valid"] if g["valid"] else 0


def first(e, g):
    return name(e, max(g["votes"], key=g["votes"].get)) if g["votes"] else "-"


def thousands(n):
    return f"{n:,}".replace(",", ".")


def num(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def signed(x):
    x = round(x, 1)  # no "−0,0"
    return ("+" if x > 0 else "−" if x < 0 else "±") + num(abs(x))


def table(head, rows):
    """An HTML table: head is a list of (label, numeric); rows hold already escaped cells."""
    th = "".join(f'<th scope="col"{" class=n" if n else ""}>{html.escape(h)}</th>' for h, n in head)
    tr = "".join("<tr>" + "".join(f'<td{" class=n" if n else ""}>{c}</td>' for c, (_, n) in zip(r, head, strict=True)) + "</tr>"
                 for r in rows)
    return f'<div class="wrap"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def text_table(head, rows):
    """The same table as plain text, for stdout."""
    cells = [[h for h, _ in head]] + [[html.unescape(re.sub(r"<[^>]+>", "", c)) for c in r] for r in rows]
    w = [max(len(r[i]) for r in cells) for i in range(len(head))]
    return "\n".join("  ".join(c.rjust(w[i]) if head[i][1] else c.ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in cells)


SECTIONS = []  # html of the page, in order; the text goes to stdout as it is made


def emit(title, intro, head, rows, fold=False):
    """One table: printed, and added to the page (inside <details> when fold, for the long ones)."""
    print(f"\n{title}\n" + text_table(head, rows))
    body = (f"<p>{intro}</p>" if intro else "") + table(head, rows)
    SECTIONS.append(f"<details><summary><h3>{html.escape(title)}</h3></summary>{body}</details>" if fold
                    else f"<h3>{html.escape(title)}</h3>{body}")


def area_rows(e, gs, parties):
    """Rows of a table of areas (continents, countries, cities), most valid votes first: stations, registered, valid,
    valid / registered, first party and the shares of the parties shown."""
    return [[html.escape(str(g)), str(d["n"]), thousands(d["reg"]), thousands(d["valid"]),
             num(100 * d["valid"] / d["reg"]) + "%" if d["reg"] else "-", html.escape(first(e, d))]
            + [num(share(d, p)) for p in parties] for g, d in sorted(gs.items(), key=lambda x: -x[1]["valid"])]


def abroad_section(e):
    parties = shown(e)
    ab, nat = total(e, f"s.ep_id={ABROAD}"), total(e)
    countries, cities = db.execute("SELECT COUNT(DISTINCT country), COUNT(DISTINCT city || country) FROM abroad WHERE election=?",
                                   (e,)).fetchone()
    title = ELECTION_NAMES[e]
    print(f"\n=== Εξωτερικό, {title} ===")
    lead = (f"{ab['n']} εκλογικά τμήματα σε {countries} χώρες και {cities} πόλεις. Εγγεγραμμένοι {thousands(ab['reg'])}, "
            f"έγκυρα {thousands(ab['valid'])} ({num(100 * ab['valid'] / ab['reg'])}% των εγγεγραμμένων), "
            f"δηλαδή {num(100 * ab['valid'] / nat['valid'], 2)}% των εγκύρων όλης της χώρας.")
    print(lead)
    SECTIONS.append(f'<h2 id="ab-{e.replace("/", "-")}">Εξωτερικό · {html.escape(title)}</h2><p>{lead}</p>')
    rows = [[html.escape(name(e, p)), num(share(ab, p)), num(share(nat, p)), signed(share(ab, p) - share(nat, p))]
            for p in sorted(ab["votes"], key=lambda p: -ab["votes"][p])
            if p in parties or 100 * ab["votes"][p] / ab["valid"] >= MIN_SHARE]
    emit(f"Κόμματα: εξωτερικό και όλη η χώρα, {title}", "Ποσοστό επί των εγκύρων· διαφορά σε ποσοστιαίες μονάδες.",
         [("Κόμμα", False), ("Εξωτερικό %", True), ("Όλη η χώρα %", True), ("Διαφορά", True)], rows)
    head = [("Τμήματα", True), ("Εγγεγραμμένοι", True), ("Έγκυρα", True), ("Έγκυρα / εγγ.", True), ("Πρώτο", False)]
    head += [(name(e, p) + " %", True) for p in parties]
    where = f"s.ep_id={ABROAD}"
    emit(f"Ανά ήπειρο, {title}", "", [("Ήπειρος", False)] + head, area_rows(e, groups(e, "a.continent", where), parties))
    emit(f"Ανά χώρα, {title}", "Με σειρά εγκύρων. Σε χώρες με λίγες εκατοντάδες ψήφους λίγες ψήφοι αλλάζουν πολύ τα ποσοστά.",
         [("Χώρα", False)] + head, area_rows(e, groups(e, "a.country", where), parties), fold=True)
    emit(f"Ανά πόλη, {title}", "", [("Πόλη (χώρα)", False)] + head,
         area_rows(e, groups(e, "a.city || ' (' || a.country || ')'", where), parties), fold=True)


def postal_section():
    parties = shown(EURO)
    post, box, nat = total(EURO, "s.kind='Τ'"), total(EURO, "s.kind<>'Τ'"), total(EURO)
    dom = total(EURO, f"s.kind='Τ' AND s.ep_id<>{ABROAD}")
    title = ELECTION_NAMES[EURO]
    print(f"\n=== Επιστολική ψήφος, {title} ===")
    lead = (f"Εγγεγραμμένοι στην επιστολική ψήφο {thousands(post['reg'])}, έγκυρα {thousands(post['valid'])} "
            f"({num(100 * post['valid'] / post['reg'])}% των εγγεγραμμένων), δηλαδή {num(100 * post['valid'] / nat['valid'], 2)}% "
            f"των εγκύρων όλης της χώρας. Από αυτά {thousands(dom['valid'])} στην Ελλάδα και "
            f"{thousands(post['valid'] - dom['valid'])} στο εξωτερικό, όπου όλη η ψήφος ήταν επιστολική. "
            "Το ΥΠΕΣ δίνει τις επιστολικές μόνο ως σύνολο ανά περιφέρεια.")
    print(lead)
    SECTIONS.append(f'<h2 id="postal">Επιστολική ψήφος · {html.escape(title)}</h2><p>{lead}</p>')
    rows = [[html.escape(name(EURO, p)), num(share(post, p)), num(share(dom, p)), num(share(box, p)),
             signed(share(dom, p) - share(box, p))] for p in parties]
    emit(f"Κόμματα: επιστολική και κάλπη, {title}",
         "«Επιστολική στην Ελλάδα»: χωρίς το εξωτερικό. Διαφορά: της επιστολικής στην Ελλάδα από την κάλπη, σε μονάδες.",
         [("Κόμμα", False), ("Επιστολική %", True), ("Επιστολική στην Ελλάδα %", True), ("Κάλπη %", True), ("Διαφορά", True)], rows)
    june, ab = total("2023/june", f"s.ep_id={ABROAD}"), total(EURO, f"s.ep_id={ABROAD}")
    rows = [[html.escape(name(EURO, p)), num(share(ab, p)), num(share(june, p)) if p in june["votes"] else "-"] for p in parties]
    emit("Εξωτερικό: Ευρωεκλογές 2024 (επιστολική) και Ιούνιος 2023 (κάλπη)",
         f"Δύο διαφορετικές αναμετρήσεις, με {thousands(ab['valid'])} και {thousands(june['valid'])} έγκυρα. "
         "Για το 2024 το ΥΠΕΣ δεν δίνει κατανομή ανά χώρα.",
         [("Κόμμα", False), ("Εξωτερικό 2024 %", True), ("Εξωτερικό Ιούνιος 2023 %", True)], rows)
    names = dict(db.execute("SELECT ep_id, name FROM ep WHERE election=?", (EURO,)))
    pb, bb = groups(EURO, "s.ep_id", "s.kind='Τ'"), groups(EURO, "s.ep_id", "s.kind<>'Τ'")
    rows = [[html.escape(names[ep]), thousands(d["reg"]), thousands(d["valid"]), num(100 * d["valid"] / (d["valid"] + bb[ep]["valid"])) + "%"]
            + [f"{num(share(d, p))} ({signed(share(d, p) - share(bb[ep], p))})" for p in parties]
            for ep, d in sorted(pb.items(), key=lambda x: -x[1]["valid"]) if ep != ABROAD]
    emit(f"Ανά περιφέρεια, {title}",
         "Για κάθε κόμμα: ποσοστό στην επιστολική και, σε παρένθεση, η διαφορά από την κάλπη της ίδιας περιφέρειας, σε μονάδες.",
         [("Περιφέρεια", False), ("Εγγεγραμμένοι", True), ("Έγκυρα", True), ("% των εγκύρων", True)]
         + [(name(EURO, p) + " %", True) for p in parties], rows, fold=True)


def page():
    # the sections sit in a <div>: common.css moves "main > h2" to the end on phones (a rule for the map pages)
    title = "Ψηφοφόροι εξωτερικού και επιστολική ψήφος"
    jump = " · ".join([f'<a href="#ab-{e.replace("/", "-")}">Εξωτερικό, {html.escape(ELECTION_NAMES[e])}</a>' for e in ABROAD_ELECTIONS]
                      + ['<a href="#postal">Επιστολική ψήφος, Ευρωεκλογές 2024</a>'])
    return f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{meta(title, "Πώς ψήφισαν οι Έλληνες του εξωτερικού ανά χώρα και πόλη (2023) και όσοι ψήφισαν επιστολικά (Ευρωεκλογές 2024).")}
{FONTS}
<script>/*THEME_JS*/</script><style>{common_css()}
main{{max-width:1100px}} p{{color:var(--ink-2)}} .wrap{{overflow-x:auto;margin-bottom:1.5em}} h2{{margin-top:1.8em;font-size:1.5em}}
summary{{cursor:pointer}} summary h3{{display:inline}} details{{margin:1em 0}}
@media (max-width:599px){{th,td{{padding:6px 4px}} th{{font-size:11px}} td{{font-size:13px}}}}</style></head><body><main id="main">
{header()}
<h1>{title}</h1>
<p>Από τα ανεπίσημα αποτελέσματα του ΥΠΕΣ. Οι ψήφοι αυτές δεν έχουν θέση στους χάρτες, μετρούν όμως στα σύνολα. «Εγγεγραμμένοι»
στο εξωτερικό και στην επιστολική ψήφο είναι όσοι έκαναν αίτηση, άρα τα έγκυρα ως ποσοστό τους είναι κοντά στη συμμετοχή.</p>
<p>{jump}</p>
<div>{"".join(SECTIONS)}</div>
{footer()}</main></body></html>"""


def main():
    for e in ABROAD_ELECTIONS:
        abroad_section(e)
    postal_section()
    PAGE.write_text(secure(fill(page()), PAGE), encoding="utf-8")
    print(f"\nwrote {PAGE}", file=sys.stderr)


if __name__ == "__main__":
    main()
