"""Download every act of parliamentary oversight signed by an MP elected with ΝΙΚΗ (party 131) in June 2023.

Sources (both public; robots.txt of each allows it):
  1. hellenicparliament.gr, «Μέσα Κοινοβουλευτικού Ελέγχου»: the official list of every kind of act
     (Ερώτηση, Ερώτηση με ΑΚΕ, ΑΚΕ, Επίκαιρη Ερώτηση, Αναφορά, Επερώτηση, ...). One listing per MP
     (`mpId`, oldest first, 10 per page), then the page of each act: signers, groups, ministries, answer files.
     It gives no answer date.
  2. vouliwatch.gr API (`/api/api/v1/parliamentary-control/documents?submitter=...`): Ερωτήσεις,
     Επίκαιρες Ερωτήσεις and Αναφορές only, with the date of the written answer and Vouliwatch's own
     (AI-made) grade of how fully each ministry answered. Joined on the Parliament id (`pcm_id`).

At most 1 request per second, a generic User-Agent, nothing personal sent. Raw pages are cached in
data/parl_control/ (git-ignored), so a rerun resumes; the last listing page of each MP and the Vouliwatch
pages are fetched again on every run so new acts are seen. Delete data/parl_control/act/ to re-read answers.

  python -I -X utf8 analysis/nikh_control_fetch.py            # all acts of the ΝΙΚΗ MPs
  python -I -X utf8 analysis/nikh_control_fetch.py baseline   # count of acts since 25/06/2023 for every MP in
      nikh_control_baseline.csv, from the Parliament listing -> data/parl_control/baseline_counts.json
  python -I -X utf8 analysis/nikh_control_fetch.py answers    # text of the first answer PDF of 50 random answered
      written acts -> data/parl_control/answer_sample.json (PDFs not kept; needs PyMuPDF, tesseract for scans)
  python -I -X utf8 analysis/nikh_control_fetch.py all_answers  # text of every answer PDF -> data/parl_control/answer/
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import ELECTION_DATE as ED

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "parl_control"
BASE = "https://www.hellenicparliament.gr/Koinovouleftikos-Elenchos/Mesa-Koinovouleutikou-Elegxou"
VW = "https://vouliwatch.gr/api/api/v1/parliamentary-control"
UA = "Mozilla/5.0 (compatible; research-script)"
START = ED["2023/june"].isoformat()  # election day; the parliament first met on 3 July 2023
HEADER = re.compile(r"Βρέθηκαν (\d+) αποτελέσματα, σελ\. \d+ από (\d+)")

# Parliament site id, short name, full name as the Parliament writes signers (surname, father's name, name;
# Vouliwatch uses the same), constituency ep_id
# (config.ELECTED; None = Επικρατείας). Every MP elected with ΝΙΚΗ on 25 June 2023, plus Ρακοβαλής,
# who took the State seat when Αποστολάκης resigned.
MPS = [
    ("f6696643-d3ec-4334-bef5-b034010b02d2", "Κουρουπάκη", "Κουρουπάκη Ιωάννη Ασπασία", 60),
    ("25f3f2ae-a117-46ed-a71f-b034010ac721", "Βορύλλας", "Βορύλλας Δημητρίου Ανδρέας", 61),
    ("0668186a-5a97-4365-bf76-b034010ac576", "Βρεττός", "Βρεττός Δημητρίου Νικόλαος", 62),
    ("40cbbf7e-bfd5-45d1-ba89-b034010b56ae", "Οικονομόπουλος", "Οικονομόπουλος Παναγιώτη Τάσος", 63),
    ("817e5dee-ddbb-47a3-924e-b034010b36eb", "Τσιρώνης", "Τσιρώνης Μιχαήλ Σπυρίδων", 31),
    ("7f504ced-478a-4646-a227-b034010b019d", "Νατσιός", "Νατσιός Ιωάννη Δημήτριος", 6),
    ("4345db9d-faad-4aa5-b86f-b034010ac3e7", "Παπαδόπουλος", "Παπαδόπουλος Δημητρίου Νικόλαος", 7),
    ("478365e7-87f1-40bb-a260-b034010b4288", "Ρούντας", "Ρούντας Ναπολέοντος Γεώργιος", 22),
    ("b14ee02d-19ab-4c90-8ff6-b034010a6f98", "Δελβερούδης", "Δελβερούδης Βαγιάνου Κομνηνός", 13),
    ("239e9a35-ad38-4431-b80c-b034010b8225", "Αποστολάκης", "Αποστολάκης Στεφάνου Γεώργιος", None),
    ("bc4d112b-87ff-48c2-87e1-b23e00ec50a2", "Ρακοβαλής", "Ρακοβαλής Παντελή Αθανάσιος", None),
]

_last = 0.0
# formal given name of the short forms in the Vouliwatch table (upper case, no accents)
NICK = {"ΝΙΚΟΣ": "ΝΙΚΟΛΑΟΣ", "ΓΙΩΡΓΟΣ": "ΓΕΩΡΓΙΟΣ", "ΔΗΜΗΤΡΗΣ": "ΔΗΜΗΤΡΙΟΣ", "ΜΑΝΩΛΗΣ": "ΕΜΜΑΝΟΥΗΛ",
        "ΣΠΥΡΟΣ": "ΣΠΥΡΙΔΩΝ", "ΕΛΕΝΑ": "ΕΛΕΝΗ", "ΤΑΣΟΣ": "ΑΝΑΣΤΑΣΙΟΣ", "ΔΙΑΜΑΝΤΗΣ": "ΑΔΑΜΑΝΤΙΟΣ",
        "ΑΓΓΕΛΟΣ": "ΕΥΑΓΓΕΛΟΣ", "ΘΑΝΑΣΗΣ": "ΑΘΑΝΑΣΙΟΣ", "ΚΩΣΤΑΣ": "ΚΩΝΣΤΑΝΤΙΝΟΣ", "ΓΙΑΝΝΗΣ": "ΙΩΑΝΝΗΣ"}


def get(url):
    """GET with at most one request per second; retries a busy Vouliwatch (503) and network errors."""
    global _last
    for attempt in range(6):
        time.sleep(max(0.0, 1.0 - (time.monotonic() - _last)))
        _last = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            wait = int(e.headers.get("Retry-After") or 0)
        except (urllib.error.URLError, TimeoutError):
            wait = 0
        time.sleep(max(wait, 2 ** attempt * 2))
    raise RuntimeError(f"gave up: {url}")


def cached(path, url, refresh=False):
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_text(get(url), encoding="utf-8")
        tmp.replace(path)
    return path.read_text(encoding="utf-8")


def rows(h):
    """(number, date, kind, pcm_id, title) of each result row of a listing page."""
    for row in re.findall(r"<tr[^>]*>.*?</tr>", h, re.DOTALL):
        ake, date = re.search(r"lblake\">([^<]*)", row), re.search(r"lbldate\">([^<]*)", row)
        kind, pcm = re.search(r"lblType\">([^<]*)", row), re.search(r"pcm_id=([0-9a-f-]{36})\">([^<]*)", row)
        if ake and date and kind and pcm:
            yield ake[1].strip(), date[1].strip(), kind[1].strip(), pcm[1], pcm[2].strip()


def listing(mp_id, short):
    """All acts of one MP on the Parliament site {pcm_id: [number, date, kind, title]} and the site's count.
    Acts filed the same day have no fixed order, so a row can move between pages and be missed: when the count
    falls short, the list is read again newest first and the two are joined."""
    acts, total = read_pages(mp_id, short, "asc")
    if len(acts) < total:
        more, total = read_pages(mp_id, short, "desc")
        acts.update(more)
    return acts, total


def read_pages(mp_id, short, order):
    """Newest-first pages shift whenever an act is filed, so they are always read fresh."""
    acts, page, pages, total = {}, 1, 1, None
    while page <= pages:
        url = f"{BASE}?mpId={mp_id}&SortBy=date&SortDirection={order}&pageNo={page}"
        path = CACHE / "list" / f"{short}_{page:03d}.html" if order == "asc" else \
            CACHE / "list" / f"{short}_{order}_{page:03d}.html"
        m = HEADER.search(cached(path, url, refresh=order == "desc"))
        if not m:
            raise RuntimeError(f"no result header: {url}")
        if order == "asc" and page == int(m[2]):  # the last page grows as acts are filed: always read it fresh
            m = HEADER.search(cached(path, url, refresh=True))
        total, pages = int(m[1]), int(m[2])
        for ake, date, kind, pcm, title in rows(path.read_text(encoding="utf-8")):
            acts[pcm] = [ake, date, kind, title]
        page += 1
    return acts, total


def vouliwatch(name, short):
    """All Vouliwatch documents of one submitter since START (read fresh on every run)."""
    docs, page = [], 1
    while True:
        q = urllib.parse.urlencode({"from": START, "submitter": name, "sort": "date", "page": page,
                                    "per_page": 100, "include_total": 1})
        j = json.loads(cached(CACHE / "vw" / f"{short}_{page:03d}.json", f"{VW}/documents?{q}", refresh=True))
        docs += j["results"]
        if not j.get("has_more"):
            return docs, j.get("total")
        page += 1


def baseline_counts():
    """Acts since START of every MP in nikh_control_baseline.csv, counted by the Parliament (the first listing page
    with DateFrom says how many). The MP id comes from the site's MP menu by name: the whole name first (with the
    nickname in brackets, which tells «Κεδίκογλου Συμεών (Σίμος)» from «Κεδίκογλου Συμεών»), else the surname and a
    given name in its formal form (NICK) or its first four letters. A name the menu has more than once is read for
    each id and the ids with acts are kept. Writes CACHE/baseline_counts.json."""
    import csv
    import unicodedata

    def plain(text):  # upper case, no accents, only letters and spaces
        text = unicodedata.normalize("NFD", text)
        text = "".join(c for c in text if not unicodedata.combining(c)).upper()
        return " ".join(re.sub(r"[^\w]|\d|_", " ", text).split())

    def forms(name):  # (surname, {given names}) with nicknames and initials handled
        words = [w for w in plain(name).split() if len(w) > 1]
        given = {NICK.get(w, w) for w in words[1:]}
        return words[0] if words else "", given | {g[:4] for g in given}
    menu = re.search(r"<select[^>]*ddMps.*?</select>", (CACHE / "list" / f"{MPS[0][1]}_001.html")
                     .read_text(encoding="utf-8"), re.DOTALL)[0]
    options = re.findall(r'<option[^>]*value="([0-9a-f-]{36})"[^>]*>([^<]*)', menu)
    since = "/".join(reversed(START.split("-")))
    with open(Path(__file__).with_name("nikh_control_baseline.csv"), encoding="utf-8-sig") as f:
        names = [r["ΟΝΟΜΑ"] for r in csv.DictReader(f, delimiter=";")]
    out = {}
    for row in names:
        person = re.sub(r"\s*\([^()]*\)\s*$", "", row)  # the last brackets are the group
        match = [i for i, n in options if plain(n) == plain(person)]
        if not match:
            sur, given = forms(person)
            match = [i for i, n in options if forms(n)[0] == sur and forms(n)[1] & given]
        found = []
        for mp_id in dict.fromkeys(match):
            h = cached(CACHE / "base" / f"{mp_id}.html", f"{BASE}?mpId={mp_id}&DateFrom={since}&pageNo=1")
            m = HEADER.search(h)
            found.append([mp_id, int(m[1]) if m else 0])  # no header: the listing is empty
        # homonyms: keep the ids with acts; when none has acts the MP has none (a minister, say)
        out[row] = [f for f in found if f[1]] or found[:1]
    (CACHE / "baseline_counts.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{sum(1 for v in out.values() if len(v) == 1)} of {len(out)} MPs found once", flush=True)


def answer_files():
    """{pcm_id: [(url, file number), ...]} of every act with answer files, lowest number first."""
    index = json.loads((CACHE / "list_index.json").read_text(encoding="utf-8"))
    out = {}
    for pcm in index:
        block = re.search(r"Αρχεία Απαντήσεων:</dt>\s*<dd>(.*?)</dd>",
                          (CACHE / "act" / f"{pcm}.html").read_text(encoding="utf-8"), re.DOTALL)
        files = sorted(re.findall(r'href="([^"]+/(\d+)\.pdf)"', block[1]) if block else [], key=lambda f: int(f[1]))
        if files:
            out[pcm] = files
    return out


def pdf_text(url):
    """{pages, created, ocr, text} of one answer PDF, or None if it cannot be fetched. Needs PyMuPDF (fitz); a PDF
    with no text layer (a scan) is read with tesseract (Greek), first three and last page. The PDF is not kept."""
    import shutil
    import subprocess
    import tempfile
    import fitz
    global _last
    for attempt in range(3):
        time.sleep(max(0.0, 1.0 - (time.monotonic() - _last)))
        _last = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90) as r:
                data = r.read()
            break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt * 2)
    else:
        return None
    doc = fitz.open(stream=data, filetype="pdf")
    text, ocr = "".join(page.get_text() for page in doc), False
    if len(text.strip()) < 200:
        tess = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        ocr, text = True, ""
        with tempfile.TemporaryDirectory() as tmp:
            for i in sorted({*range(min(3, len(doc))), len(doc) - 1}):
                png = Path(tmp) / f"{i}.png"
                doc[i].get_pixmap(dpi=200).save(png)
                text += subprocess.run([tess, str(png), "-", "-l", "ell"], capture_output=True,
                                       text=True, encoding="utf-8").stdout
    return {"pages": len(doc), "created": doc.metadata.get("creationDate", ""), "ocr": ocr, "text": text}


def sample_answers(n=50, seed=2026):
    """Text of the first answer file of n random answered written acts, to check the estimated answer day, who
    signed and Vouliwatch's grade by hand. Only the text is kept, in CACHE/answer_sample.json."""
    import random
    written = {"Ερωτήσεις", "Ερώτηση σε συνδυασμό με Α.Κ.Ε.", "Α.Κ.Ε.", "Α.Κ.Ε. σε συνδυασμό με ερώτηση", "Αναφορές"}
    index = json.loads((CACHE / "list_index.json").read_text(encoding="utf-8"))
    pool = [(pcm, files[0][0]) for pcm, files in answer_files().items() if index[pcm][2] in written]
    random.seed(seed)
    out = []
    for pcm, url in random.sample(sorted(pool), n):
        t = pdf_text(url)
        if t:
            out.append({"pcm_id": pcm, "url": url, "pages": t["pages"], "created": t["created"], "ocr": t["ocr"],
                        "head": t["text"][:3000], "tail": t["text"][-2000:]})
            print(f"{len(out)}/{n}", flush=True)
    (CACHE / "answer_sample.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")


def all_answers():
    """Text of every answer file, one JSON per file number in CACHE/answer/ (resumable; PDFs not kept)."""
    todo = [(url, no) for files in answer_files().values() for url, no in files
            if not (CACHE / "answer" / f"{no}.json").exists()]
    print(f"{len(todo)} answer files to read", flush=True)
    (CACHE / "answer").mkdir(exist_ok=True)
    for i, (url, no) in enumerate(todo, 1):
        t = pdf_text(url)
        if t:
            path = CACHE / "answer" / f"{no}.json"
            path.with_suffix(".part").write_text(json.dumps({"url": url, **t}, ensure_ascii=False), encoding="utf-8")
            path.with_suffix(".part").replace(path)
        if i % 100 == 0:
            print(f"  {i}/{len(todo)}", flush=True)


def main():
    if sys.argv[1:] == ["baseline"]:
        return baseline_counts()
    if sys.argv[1:] == ["answers"]:
        return sample_answers()
    if sys.argv[1:] == ["all_answers"]:
        return all_answers()
    summary, index = {}, {}
    for mp_id, short, _, _ in MPS:
        acts, total = listing(mp_id, short)
        print(f"{short}: {len(acts)} πράξεις (η Βουλή μετρά {total})", flush=True)
        summary[short] = {"parliament": len(acts), "parliament_total": total}
        for k, v in acts.items():
            index.setdefault(k, v)
    (CACHE / "list_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
    todo = [k for k in index if not (CACHE / "act" / f"{k}.html").exists()]
    print(f"{len(index)} μοναδικές πράξεις, {len(todo)} σελίδες να κατεβούν", flush=True)
    for i, k in enumerate(todo, 1):
        cached(CACHE / "act" / f"{k}.html", f"{BASE}?pcm_id={k}")
        if i % 100 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
    for _, short, full, _ in MPS:
        docs, total = vouliwatch(full, short)
        summary[short].update(vouliwatch=len(docs), vouliwatch_total=total)
        print(f"Vouliwatch {full}: {len(docs)} (μετρά {total})", flush=True)
    (CACHE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
