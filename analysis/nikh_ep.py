"""ΝΙΚΗ in the European Parliament: the questions and plenary speeches of its MEP, Νικόλαος Αναδιώτης,
compared with the other Greek MEPs and with every MEP of the 10th term. Public data of the EP Open Data API only
(the europarl.europa.eu pages refuse scripts; Parltrack's robots.txt excludes AI agents, so neither is used).

  python -I -X utf8 analysis/nikh_ep.py fetch    # -> data/ep_control/ (cached, at most 1 request a second)
  python -I -X utf8 analysis/nikh_ep.py          # -> analysis/nikh_ep.txt

Every question of the term (written, priority, oral, interpellation) is read with its authors, addressee and
answer, in batches of 50 ids. A question signed by several MEPs counts for each signer, as in the Greek
Parliament count (nikh_control.py).
"""
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "ep_control"
OUT = Path(__file__).with_suffix(".txt")
API = "https://data.europarl.europa.eu/api/v2/"
UA = "Mozilla/5.0 (research script)"
ANADIOTIS = "256858"
YEARS = (2024, 2025, 2026)  # the 10th term began on 16 July 2024
PAGE = 5000  # a larger limit makes the API fail with 500
TODAY = date(2026, 11, 25)
MIN_AGE = 60  # days: younger questions are left out of answer rates (the Commission has 6 weeks, 3 for priority)
KIND = {"QUESTION_WRITTEN": "γραπτή", "QUESTION_WRITTEN_PRIORITY": "γραπτή κατά προτεραιότητα",
        "QUESTION_ORAL": "προφορική", "INTERPELLATION_MAJOR": "επερώτηση"}
TO = {"COM": "Επιτροπή", "HRVP": "Ύπατος Εκπρόσωπος", "CS": "Συμβούλιο"}
# shortcut: keyword stems in the Greek title, checked by eye on his 142 titles only; a classifier would be needed for all MEPs
THEMES = {"Τουρκία, Κύπρος, Αλβανία, Πρέσπες": ("τουρκ", "κύπρ", "κυπρ", "αλβαν", "πρεσπ", "γαλάζια πατρίδα", "ερντογ", "τουρκολιβ", "κατοχ", "μειονότητ"),
          "Χριστιανοί, Ορθοδοξία, θρησκεία": ("χριστιαν", "ορθόδοξ", "ορθοδόξ", "ορθοδοξ", "θρησκ", "μονή", "μονης", "εκκλησ"),
          "Μετανάστευση, Σένγκεν": ("μεταναστ", "σένγκεν", "προσφυγ", "λαθρο")}
_last = 0.0


def slim(x):
    """Drop the per-language file listings (most of each answer's size); nothing here reads them."""
    if isinstance(x, dict):
        return {k: slim(v) for k, v in x.items() if k != "is_realized_by"}
    return [slim(v) for v in x] if isinstance(x, list) else x


def get(path, cache):
    """JSON of an API path, cached in CACHE/cache; at most one request a second, retried when the API fails."""
    global _last
    f = CACHE / cache
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    sep = "&" if "?" in path else "?"
    url = f"{API}{path}{sep}format=application%2Fld%2Bjson"
    for attempt in range(5):
        time.sleep(max(0.0, 1.0 - (time.time() - _last)))
        _last = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/ld+json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read().decode("utf-8")
            data = json.loads(body) if body.strip() else {"data": []}  # 204: nothing found
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  retry {attempt + 1} {path[:80]}: {e}", flush=True)
            time.sleep(10 * (attempt + 1))
    else:
        raise RuntimeError(f"API failed: {path}")
    f.parent.mkdir(parents=True, exist_ok=True)
    data = slim(data)
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def question_ids():
    ids = []
    for y in YEARS:
        page = get(f"parliamentary-questions?year={y}&limit={PAGE}", f"list_{y}.json")["data"]
        assert len(page) < PAGE, f"{y}: list may be cut at {PAGE}"
        ids += [x["identifier"] for x in page]
    return sorted(set(ids))


def current_meps():
    return get("meps/show-current?limit=1000", "meps_current.json")["data"]


def fetch():
    meps = current_meps()
    ids = question_ids()
    print(f"{len(ids)} questions, {len(meps)} current MEPs", flush=True)
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        get("parliamentary-questions/" + ",".join(batch), f"q/{batch[0]}_{len(batch)}.json")
        if i % 1000 == 0:
            print(f"  {i}/{len(ids)}", flush=True)
    for m in meps:
        if m.get("api:country-of-representation") == "GR":
            speeches(m["identifier"])


def speeches(mep):
    out, off = [], 0
    while True:
        page = get(f"speeches?person-id={mep}&limit=500&offset={off}", f"sp/{mep}_{off}.json").get("data", [])
        out += page
        if len(page) < 500:
            return out
        off += 500


def people(parts, role):
    return [p.split("/")[-1] for x in parts if x.get("participation_role", "").endswith(role)
            for p in x.get("had_participant_person", [])]


def orgs(parts, role):
    return [o.split("/")[-1] for x in parts if x.get("participation_role", "").endswith(role)
            for o in x.get("had_participant_organization", [])]


def load():
    meps = {m["identifier"]: m for m in current_meps()}
    qs = {}
    for f in sorted((CACHE / "q").glob("*.json")):
        for q in json.loads(f.read_text(encoding="utf-8")).get("data", []):
            if "ep-10" not in str(q.get("parliamentary_term", "")):
                continue
            parts = q.get("workHadParticipation", [])
            answers = sorted(a["document_date"] for a in q.get("inverse_answers_to", []) if a.get("document_date"))
            title = q.get("title_dcterms") or {}
            kind = q["work_type"].split("/")[-1]
            qs[q["identifier"]] = {
                "id": q["identifier"], "date": date.fromisoformat(q["document_date"]),
                "kind": KIND.get(kind, kind), "authors": people(parts, "AUTHOR"), "to": orgs(parts, "ADDRESSEE"),
                "answer": date.fromisoformat(answers[0][:10]) if answers else None,
                "title": title.get("el") or title.get("en") or "",
            }
    return meps, qs


def main():
    if sys.argv[1:] == ["fetch"]:
        return fetch()
    meps, qs = load()
    lines = []
    p = lines.append
    by = Counter(a for q in qs.values() for a in q["authors"])
    me = [q for q in qs.values() if ANADIOTIS in q["authors"]]
    gr = {i for i, m in meps.items() if m.get("api:country-of-representation") == "GR"}

    def name(i):
        return meps[i]["label"] if i in meps else i

    def group(i):
        return meps[i].get("api:political-group", "?") if i in meps else "?"

    p(f"ΝΙΚΗ στο Ευρωκοινοβούλιο: Νικόλαος Αναδιώτης (μη εγγεγραμμένος), 10η περίοδος, ως {TODAY:%d.%m.%Y}")
    p(f"Πηγή: EP Open Data API· {len(qs)} ερωτήσεις της περιόδου, {len(meps)} σημερινοί ευρωβουλευτές.")
    p("")
    p(f"1. Ερωτήσεις του Αναδιώτη: {len(me)}")
    p("   Ανά είδος: " + ", ".join(f"{k} {n}" for k, n in Counter(q["kind"] for q in me).most_common()))
    p("   Αποδέκτης: " + ", ".join(f"{TO.get(k, k)} {n}" for k, n in Counter(t for q in me for t in q["to"]).most_common()))
    theme = Counter(next((t for t, keys in THEMES.items() if any(k in q["title"].lower() for k in keys)), "Άλλα (οικονομία, περιβάλλον, Ελλάδα κ.ά.)") for q in me)
    p("   Θέμα (λέξεις του τίτλου): " + ", ".join(f"{k} {n}" for k, n in theme.most_common()))
    p("   Ανά έτος: " + ", ".join(f"{y} {n}" for y, n in sorted(Counter(q["date"].year for q in me).items())))
    months = Counter(q["date"].strftime("%Y-%m") for q in me)
    p("   Ανά μήνα: " + ", ".join(f"{m} {months[m]}" for m in sorted(months)))
    solo = sum(len(q["authors"]) == 1 for q in me)
    co = Counter(a for q in me for a in q["authors"] if a != ANADIOTIS)
    p(f"   Μόνος του: {solo}· με άλλους: {len(me) - solo}")
    if co:
        p("   Συνυπογράφοντες: " + ", ".join(f"{name(a)} ({group(a)}) {n}" for a, n in co.most_common(10)))
    p("")

    def written_old(sub):
        return [q for q in sub if q["kind"].startswith("γραπτή") and (TODAY - q["date"]).days >= MIN_AGE]

    def answers(sub, label):
        sub = written_old(sub)
        d = sorted((q["answer"] - q["date"]).days for q in sub if q["answer"])
        line = f"   {label}: {len(sub)} ερωτήσεις, απαντήθηκαν {len(d)} ({100 * len(d) / max(1, len(sub)):.0f}%)"
        if d:
            line += (f", διάμεσος {statistics.median(d):.0f} ημέρες, "
                     f"εντός 6 εβδομάδων {100 * sum(x <= 42 for x in d) / len(d):.0f}% των απαντημένων")
        p(line)
    p(f"2. Απαντήσεις: γραπτές ερωτήσεις παλαιότερες από {MIN_AGE} ημέρες "
      "(προθεσμία της Επιτροπής 6 εβδομάδες, 3 για τις κατά προτεραιότητα)")
    answers(me, "Αναδιώτης")
    answers(qs.values(), "Όλες")
    answers([q for q in qs.values() if set(q["authors"]) & gr], "Με Έλληνα υπογράφοντα")
    p("")
    counts = sorted((by.get(i, 0) for i in meps), reverse=True)
    mine = by.get(ANADIOTIS, 0)
    rank = 1 + sum(c > mine for c in counts)
    p("3. Ερωτήσεις ανά σημερινό ευρωβουλευτή (μετρά κάθε υπογράφων)")
    p(f"   Όλοι ({len(counts)}): μέσος {statistics.mean(counts):.0f}, διάμεσος {statistics.median(counts):.0f}, "
      f"το 10% με τις περισσότερες ≥ {counts[len(counts) // 10]}, μέγιστο {counts[0]}")
    p(f"   Αναδιώτης: {mine}, θέση {rank} από {len(counts)} (περισσότερες από το {100 * sum(c < mine for c in counts) / len(counts):.0f}%)")
    grp = {}
    for i in meps:
        grp.setdefault(group(i), []).append(by.get(i, 0))
    p("   Ανά πολιτική ομάδα (μέσος / διάμεσος): " + ", ".join(
        f"{g} {statistics.mean(v):.0f}/{statistics.median(v):.0f} (n={len(v)})"
        for g, v in sorted(grp.items(), key=lambda kv: -statistics.mean(kv[1]))))
    p("")
    p("4. Έλληνες ευρωβουλευτές: ερωτήσεις και ομιλίες στην Ολομέλεια (ομιλίες όπως τις δίνει το API· 0 = καμία καταγραφή)")
    p(f"   {'':34}{'ομάδα':>10}{'ερωτήσεις':>11}{'ομιλίες':>9}  τελευταία ομιλία")
    rows = []
    for i in gr:
        sp = speeches(i)
        rows.append((by.get(i, 0), len(sp), name(i), group(i), max((s.get("activity_date", "") for s in sp), default="")))
    for n, s, nm, g, last in sorted(rows, reverse=True):
        p(f"   {nm:34}{g:>10}{n:>11}{s:>9}  {last}")
    p(f"   Διάμεσος Ελλήνων: ερωτήσεις {statistics.median(r[0] for r in rows):.0f}, "
      f"ομιλίες {statistics.median(r[1] for r in rows):.0f}")
    p("")
    p("5. Οι πιο πρόσφατες ερωτήσεις του Αναδιώτη")
    for q in sorted(me, key=lambda q: q["date"], reverse=True)[:15]:
        p(f"   {q['date']} {q['id']} → {', '.join(TO.get(t, t) for t in q['to'])}: {q['title']}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
