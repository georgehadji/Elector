"""Poll tables of the Greek elections from the English Wikipedia -> analysis/nikh_pollerror.csv, and the other parties' columns of
analysis/nikh_polls.csv.

Why: the ratio ballot / poll average of small parties (nikh_pollerror.py) and the moves of the other parties against NIKH
(nikh_flows.py) need all parties, not only NIKH. Public aggregate poll figures only.

nikh_pollerror.csv (long format): election, kind (poll | ballot), firm, end (fieldwork end date), sample, party, pct.
- party = Wikipedia article name of the party, taken from the link of the column header (the logo columns have no text); the
  same party can have another article name on another page (e.g. Niki / Victory), which does not matter inside one election.
- Exit polls (date with a time of day), range figures ("34.6- 37.0") and cells without a number are left out. The seat counts
  that follow the percentage in a cell are dropped.
- ballot rows = the election result row of the same table (the row with the election date and no sample).
- Pages and revision ids downloaded on 23 Nov 2026: see PAGES and CURRENT. The pages change; the csv is a copy, rerun to refresh.
- Not checked against the polling firms' own releases (unlike nikh_polls.csv, NIKH.md section 16).

nikh_polls.csv: the party columns of the current-parliament table are added next to firm, end, sample, niki. Rows are matched
on (firm, end date, sample); rows without a match (the three added or corrected by hand, see nikh_polls.py) keep the columns
empty. niki stays as it is (corrected by hand).

  python -I -X utf8 analysis/polls_wiki.py [cache_dir]      # cache_dir keeps the downloaded pages; delete it to refresh
"""
import calendar
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "elections-research-script/1.0 (public aggregate poll data)"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
# (election key, page title, index of the poll table among the wikitables, election day, revision id downloaded)
PAGES = [
    ("2007", "Opinion polling for the 2007 Greek parliamentary election", 0, date(2007, 9, 16), 1267595523),
    ("2009", "Opinion polling for the 2009 Greek parliamentary election", 0, date(2009, 10, 4), 1341665500),
    ("2012/may", "Opinion polling for the May 2012 Greek parliamentary election", 0, date(2012, 5, 6), 1344591318),
    ("2012/june", "Opinion polling for the June 2012 Greek parliamentary election", 0, date(2012, 6, 17), 1306504448),
    ("2015/jan", "Opinion polling for the January 2015 Greek parliamentary election", 0, date(2015, 1, 25), 1324451261),
    ("2015/sep", "Opinion polling for the September 2015 Greek parliamentary election", 0, date(2015, 9, 20), 1306508935),
    ("2019", "Opinion polling for the 2019 Greek parliamentary election", 0, date(2019, 7, 7), 1306348599),
    ("2023/may", "Opinion polling for the May 2023 Greek parliamentary election", 0, date(2023, 5, 21), 1324451274),
    ("2023/june", "Opinion polling for the June 2023 Greek parliamentary election", 0, date(2023, 6, 25), 1267596607),
    ("2014/euro", "2014 European Parliament election in Greece", 0, date(2014, 5, 25), 1380678939),
    ("2019/euro", "2019 European Parliament election in Greece", 0, date(2019, 5, 26), 1377840964),
    ("2024/euro", "2024 European Parliament election in Greece", 1, date(2024, 6, 9), 1386281740),
]
CURRENT = "Opinion polling for the next Greek parliamentary election"  # table 0; revision 1387055332
# the 2019 Euro page has no result row in its poll table: the result is in the national 2019 page, row "2019 EP election"
EURO_2019_BALLOT = ("Opinion polling for the 2019 Greek parliamentary election", 0, date(2019, 5, 26))


class Tables(HTMLParser):
    """The wikitables of a page: rows of cells with their text, spans and first link."""

    def __init__(self):
        super().__init__()
        self.done, self.stack, self.cell, self.skip = [], [], None, 0

    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == "table":
            self.stack.append({"rows": [], "cls": a.get("class", "")})
        elif not self.stack:
            return
        elif tag == "tr":
            self.stack[-1]["rows"].append([])
        elif tag in ("td", "th"):
            self.cell = {"t": "", "rs": int(re.sub(r"\D", "", a.get("rowspan", "1")) or 1),
                         "cs": int(re.sub(r"\D", "", a.get("colspan", "1")) or 1), "href": ""}
        elif tag == "a" and self.cell is not None and not self.cell["href"] and a.get("href", "").startswith("/wiki/"):
            self.cell["href"] = urllib.parse.unquote(a["href"][6:])
        elif tag in ("style", "sup", "script"):
            self.skip += 1
        elif tag == "br" and self.cell is not None:
            self.cell["t"] += " "

    def handle_endtag(self, tag):
        if tag in ("style", "sup", "script") and self.skip:
            self.skip -= 1
        elif tag in ("td", "th") and self.cell is not None and self.stack:
            self.stack[-1]["rows"][-1].append(self.cell)
            self.cell = None
        elif tag == "table" and self.stack:
            self.done.append(self.stack.pop())

    def handle_data(self, d):
        if self.cell is not None and not self.skip:
            self.cell["t"] += d


def grid(t):
    """([[text]], [[link]]) of one parsed table, rowspan and colspan expanded."""
    g = {}
    for r, row in enumerate(t["rows"]):
        c = 0
        for cell in row:
            while (r, c) in g:
                c += 1
            for dr in range(cell["rs"]):
                for dc in range(cell["cs"]):
                    g[r + dr, c + dc] = cell
            c += cell["cs"]
    nc = max((k[1] for k in g), default=-1) + 1
    cells = [[g.get((r, c)) for c in range(nc)] for r in range(len(t["rows"]))]
    return ([[re.sub(r"\s+", " ", x["t"]).strip() if x else "" for x in row] for row in cells],
            [[x["href"] if x else "" for x in row] for row in cells])


def page(title, cache):
    """(wikitables as grids, revision id) of a page; downloaded once into `cache` if given."""
    f = cache / (re.sub(r"\W+", "_", title) + ".json") if cache else None
    if f and f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
    else:
        u = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "parse", "page": title, "prop": "text|revid", "format": "json", "redirects": 1})
        for wait in (30, 60, 120, 0):  # Wikipedia answers 429 when requests come too fast: wait and retry
            try:
                d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60))["parse"]
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or not wait:
                    raise
                time.sleep(wait)
        d = {"revid": d["revid"], "html": d["text"]["*"]}
        if f:
            f.write_text(json.dumps(d), encoding="utf-8")
    p = Tables()
    p.feed(d["html"])
    return [grid(t) for t in p.done if "wikitable" in t["cls"]], d["revid"]


def end_date(s, year=None):
    """Last day of a fieldwork date text ('13-19 Nov 2026', '28 Apr-3 May 2025', 'January 25, 2015', '24 May' with a year given,
    'Dec 2006' = last day of the month); None if not a date."""
    s = re.sub(r"\(.*?\)", "", s).strip()
    ms = re.findall(r"(\d{1,2})\s*([A-Za-z]{3,})\.?,?\s*(\d{4})?$", s) or \
        [(d, m, y) for m, d, y in re.findall(r"([A-Za-z]{3,})\s+(\d{1,2}),\s*(\d{4})$", s)]
    if not ms:
        mm = re.fullmatch(r"([A-Za-z]{3,})\.?\s+(\d{4})", s)
        mon = MONTHS.get(mm.group(1)[:3].lower()) if mm else None
        return date(int(mm.group(2)), mon, calendar.monthrange(int(mm.group(2)), mon)[1]) if mon else None
    d, m, y = ms[-1]
    mon = MONTHS.get(m[:3].lower())
    y = int(y) if y else year
    return date(y, mon, int(d)) if mon and y else None


GREEK_LOOKALIKES = str.maketrans("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧαοορ", "ABEZHIKMNOPTYXaooo")


def fold(firm):
    """Firm name for matching: Greek letters that look Latin (Wikipedia has 'AΝΤ1', 'The Τοc') and spaces ('Action 24') do not count."""
    return firm.translate(GREEK_LOOKALIKES).replace(" ", "").lower()


def pct(s):
    """Percentage in a cell ('30.1', '30.2 122' = percentage and seats); None for '-', empty or a range."""
    if re.search(r"\d\s*[–-]\s*\d", s):
        return None
    m = re.match(r"\s*(\d+(?:\.\d+)?)\b", s)
    return float(m.group(1)) if m else None


def rows(g, hr, election_day, year):
    """([(kind, firm, end, sample, {party: pct})] for every poll and the ballot row of one poll table, number of rows dropped
    for want of a date). A date without a year that falls after the election day is taken from the year before ('2-11 Dec'
    in a table of a May election)."""
    head = g[0]
    firm = next(i for i, h in enumerate(head) if re.search(r"Polling|Firm", h, re.I))
    when = next(i for i, h in enumerate(head) if re.search(r"date", h, re.I))
    smp = next((i for i, h in enumerate(head) if re.search(r"Sample", h)), None)
    parties = {i: hr[0][i] for i in range(len(head)) if i not in (firm, when, smp) and hr[0][i] and not hr[0][i].startswith("File:")}
    out, nodate = [], 0
    for r in g[1:]:
        if not r[firm] or r[firm] == head[firm] or r[when] == head[when]:
            continue
        if re.search(r"\d:\d\d", r[when]):  # an exit poll (time of day in the date)
            continue
        end = end_date(r[when], year)
        if end and end > election_day and not re.search(r"\d{4}", r[when]):
            end = end_date(r[when], year - 1)
        if not end:
            nodate += 1
            continue
        n = re.sub(r"\D", "", r[smp]) if smp is not None else ""
        ballot = end == election_day and not n and re.search(r"election|result", r[firm], re.I)
        if not ballot and not n and re.search(r"election|result", r[firm], re.I):  # result row of another election, kept in the table for reference
            continue
        vals = {p: pct(r[i]) for i, p in parties.items()}
        out.append(("ballot" if ballot else "poll", r[firm], end, int(n) if n else "", {p: v for p, v in vals.items() if v is not None}))
    return out, nodate


def main():
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    long = []
    for key, title, idx, day, rev in PAGES:
        tabs, got = page(title, cache)
        rs, nodate = rows(*tabs[idx], day, day.year)
        if key == "2019/euro":
            ptabs, _ = page(EURO_2019_BALLOT[0], cache)
            rs += [r for r in rows(*ptabs[EURO_2019_BALLOT[1]], EURO_2019_BALLOT[2], 2019)[0] if r[0] == "ballot"]
        late = sum(r[2] > day for r in rs)
        rs = [r for r in rs if r[2] <= day]  # a poll dated after the election day is not a poll of it
        nb = sum(r[0] == "ballot" for r in rs)
        print(f"{key:<10} {sum(r[0] == 'poll' for r in rs):>4} δημοσκοπήσεις, {nb} ballot, rev {got}{'' if got == rev else f' (στο σχέδιο {rev})'}"
              f"{f', {nodate} χωρίς ημερομηνία' if nodate else ''}{f', {late} μετά την εκλογή' if late else ''}")
        assert nb == 1, (key, nb)
        for kind, f, end, n, vals in rs:
            for party, v in vals.items():
                long.append((key, kind, f, end.isoformat(), n, party, v))
    with open(HERE / "nikh_pollerror.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["election", "kind", "firm", "end", "sample", "party", "pct"])
        w.writerows(long)
    print(f"nikh_pollerror.csv: {len(long)} γραμμές")

    tabs, got = page(CURRENT, cache)
    g, hr = tabs[0]
    cols = [(i, h) for i, h in enumerate(g[0]) if i > 2 and h not in ("Lead", "NIKI")]
    wiki = {}
    for r in g[1:]:
        end = end_date(r[1])
        if r[0] and r[0] != g[0][0] and end:
            n = re.sub(r"\D", "", r[2])
            wiki[fold(r[0]), end, int(n) if n else ""] = {h: pct(r[i]) for i, h in cols}
    with open(HERE / "nikh_polls.csv", encoding="utf-8", newline="") as f:
        old = list(csv.DictReader(f))
    names = [h for _, h in cols]
    # parse every row before the file is touched: a bad row must not leave the hand-checked niki column half written
    keys = [(fold(r["firm"]), date.fromisoformat(r["end"]), int(r["sample"]) if r["sample"] else "") for r in old]
    vals = [wiki.pop(k, None) for k in keys]  # exact matches first, so a near match cannot take the key of another row
    for i, k in enumerate(keys):
        if vals[i] is None:  # the same firm and sample within 3 days, nearest first (rows whose date was corrected by hand, nikh_polls.py)
            near = min((x for x in wiki if x[0] == k[0] and x[2] == k[2] and abs((x[1] - k[1]).days) <= 3),
                       key=lambda x: abs((x[1] - k[1]).days), default=None)
            vals[i] = wiki.pop(near) if near else None
    miss = [(r["firm"], r["end"], r["sample"]) for r, v in zip(old, vals, strict=True) if v is None]
    tmp = HERE / "nikh_polls.csv.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["firm", "end", "sample", "niki"] + names)
        for r, v in zip(old, vals, strict=True):
            w.writerow([r["firm"], r["end"], r["sample"], r["niki"]] + [("" if v is None or v[h] is None else v[h]) for h in names])
    tmp.replace(HERE / "nikh_polls.csv")
    print(f"nikh_polls.csv: {len(old)} γραμμές, {len(old) - len(miss)} με στήλες κομμάτων, rev {got}")
    print(f"  χωρίς αντιστοίχιση στον πίνακα ({len(miss)}): {miss}")
    print(f"  γραμμές του πίνακα που δεν βρέθηκαν στο csv ({len(wiki)}): {sorted((k[0], k[1].isoformat(), k[2]) for k in wiki)[:20]}")


if __name__ == "__main__":
    assert end_date("13–19 Nov 2026") == date(2026, 11, 19) and end_date("28 Apr–3 May 2025") == date(2025, 5, 3)
    assert end_date("January 25, 2015") == date(2015, 1, 25) and end_date("24 May", 2014) == date(2014, 5, 24)
    assert end_date("Dec 2006") == date(2006, 12, 31) and end_date("Feb 2008") == date(2008, 2, 29) and end_date("2014") is None
    assert pct("30.2 122") == 30.2 and pct("–") is None and pct("34.6– 37.0") is None and pct("") is None
    main()
