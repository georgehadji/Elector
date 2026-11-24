"""Majorline (majorline.eu) Greek parliamentary forecast -> analysis/majorline_runs.csv, analysis/majorline_parties.csv.

PROTOTYPE, NOT SCHEDULED, NOT RUN AGAINST THE SITE. Plan, legal position and open questions: analysis/majorline_plan.md.
Run it against the network only after the site owner has agreed (or the user has decided to use it privately and locally).

Source: https://majorline.eu/data/greece.json, the file the public page greece.html loads itself (robots.txt: Allow: /).
Undocumented; no terms of use or licence found (24 Nov 2026). Their estimate is published weekly (Sunday as_of date, file
changes Monday); the fetch is a conditional GET, so a run with nothing new is one 304.
- robots.txt is read first and the fetch stops if it disallows the path for us. At most one request per second.
- Raw response bytes are kept in data/majorline/raw/ (git-ignored): the CSVs can be rebuilt from them.
- Fails closed: a missing top-level key stops the run before anything is written; new keys only print a warning.
- majorline_runs.csv: one row per run (as_of, run_id, their sha256, method, n_polls, three headline probabilities).
- majorline_parties.csv: one row per (as_of, party). src=run: the current run (share, P(>=3%), P(first), P(second), P(third
  party enough for 151), median seats and range with / without the bonus). src=trend: the 15 earlier estimates of the file's
  `trend` list (share, P(>=3%), P(second)); a run row replaces a trend row of the same date.
- Probabilities are fractions 0-1, shares are % of valid votes, as in the source. Unofficial; attribute: "Majorline".

  python -I -X utf8 analysis/majorline_fetch.py [--force]    # --force ignores the saved ETag
  python -I -X utf8 analysis/majorline_fetch.py --selftest   # offline, no network
"""
import csv
import json
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "majorline"
BASE = "https://majorline.eu"
URL = BASE + "/data/greece.json"
UA = "elections-research-script/1.0 (public aggregate poll data)"
RUNS, PARTIES = HERE / "majorline_runs.csv", HERE / "majorline_parties.csv"
RUN_COLS = ["as_of", "run_id", "sha256", "method", "n_polls", "single_party_majority", "no_bonus", "nd_pasok_151"]
PARTY_COLS = ["as_of", "party", "src", "share", "p_in", "p_first", "p_second", "p_third_enough",
              "seats_bonus", "lo_bonus", "hi_bonus", "seats_nobonus", "lo_nobonus", "hi_nobonus"]
KEYS = {"run", "method", "n_polls", "vote", "out", "scen", "trend"}  # the ones flatten() reads


def flatten(j):
    """(run row, {(as_of, party): party row}) from the parsed file."""
    missing = KEYS - j.keys()
    if missing:
        raise SystemExit(f"schema changed, missing {sorted(missing)}; nothing written")
    run, out, scen = j["run"], j["out"], j["scen"]
    a = run["as_of"]
    runrow = {"as_of": a, "run_id": run["run_id"], "sha256": run["sha256"], "method": j["method"], "n_polls": j["n_polls"],
              **{k: out[k] for k in RUN_COLS[5:]}}
    rows = {}
    for t in j["trend"]:
        for p, share in t["vote"].items():
            rows[t["d"], p] = {"as_of": t["d"], "party": p, "src": "trend", "share": share,
                               "p_in": t["pass3"].get(p), "p_second": t["second"].get(p)}
    share = {v["e"]: v["share"] for v in j["vote"]}
    for k in out:
        if not k.startswith("threshold_"):
            continue
        p = k[len("threshold_"):]
        r = {"as_of": a, "party": p, "src": "run", "share": share.get(p), "p_in": out[k], "p_first": out.get("first_" + p),
             "p_second": out.get("second_" + p), "p_third_enough": out.get("third_party_enough_" + p)}
        for sc, tag in (("bonus", "bonus"), ("no_bonus", "nobonus")):
            lo_hi = scen[sc]["rin"].get(p, [None, None])
            r["seats_" + tag], r["lo_" + tag], r["hi_" + tag] = scen[sc]["parl"].get(p), lo_hi[0], lo_hi[1]
        rows[a, p] = r
    return runrow, rows


def merge(path, cols, key, new):
    """Upsert `new` ({key tuple: row}) into the csv at `path`; a run row beats a trend row. Sorted, so reruns are stable."""
    old = {}
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            old = {tuple(r[c] for c in key): r for r in csv.DictReader(f)}
    for k, r in new.items():
        k = tuple(str(x) for x in k)
        if k in old and r.get("src") == "trend" and old[k].get("src") == "run":
            continue
        old[k] = {c: "" if r.get(c) is None else r[c] for c in cols}
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols, lineterminator="\n")
        w.writeheader()
        w.writerows(old[k] for k in sorted(old))


def fetch(force):
    """Raw bytes of greece.json, or None when the server says 304. Reads robots.txt first; 1 request per second."""
    rp = urllib.robotparser.RobotFileParser(BASE + "/robots.txt")
    rp.read()
    if not rp.can_fetch(UA, URL):
        raise SystemExit("robots.txt disallows " + URL)
    time.sleep(1)
    state_file = DATA / "state.json"
    state = {} if force or not state_file.exists() else json.loads(state_file.read_text(encoding="utf-8"))
    hdr = {"User-Agent": UA, "Accept-Encoding": "identity"}  # identity: no zstd/gzip to decode
    if state.get("etag"):
        hdr["If-None-Match"] = state["etag"]
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers=hdr), timeout=30) as r:
            body, etag = r.read(), r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None
        raise
    DATA.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"etag": etag}), encoding="utf-8")
    return body


def main(force=False):
    body = fetch(force)
    if body is None:
        print("no change (304)")
        return
    j = json.loads(body)
    runrow, rows = flatten(j)
    extra = set(j) - KEYS - {"pollsters", "N", "M", "labels", "fr", "tog", "hist", "blocs", "tsplit", "second"}
    if extra:
        print("warning: new top-level keys", sorted(extra), file=sys.stderr)
    raw = DATA / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"greece_{runrow['as_of']}_{runrow['sha256'][:8]}.json").write_bytes(body)
    merge(RUNS, RUN_COLS, ("as_of",), {(runrow["as_of"],): runrow})
    merge(PARTIES, PARTY_COLS, ("as_of", "party"), rows)
    print("run", runrow["run_id"], "->", len(rows), "party rows")


def selftest():
    j = {"run": {"run_id": "r1", "as_of": "2026-11-22", "sha256": "ab" * 32}, "method": "m", "n_polls": 341,
         "vote": [{"e": "ND", "share": 29.1}, {"e": "NIKI", "share": 1.3}],
         "out": {"single_party_majority": 0.029, "no_bonus": 0.216, "nd_pasok_151": 0.56,
                 "threshold_ND": 1.0, "first_ND": 0.986, "second_ND": 0.013, "threshold_NIKI": 0.048, "first_NIKI": 0.0,
                 "second_NIKI": 0.0, "third_party_enough_NIKI": 0.018, "threshold_NEW_ENTRANT": 0.253},
         "scen": {"bonus": {"parl": {"ND": 117}, "rin": {"ND": [104, 141]}},
                  "no_bonus": {"parl": {"ND": 74, "NIKI": 0}, "rin": {"ND": [68, 87], "NIKI": [9, 12]}}},
         "trend": [{"d": "2026-11-15", "vote": {"ND": 28.8}, "pass3": {"ND": 1}, "second": {"ND": 0.01}},
                   {"d": "2026-11-22", "vote": {"ND": 29.0}, "pass3": {"ND": 1}, "second": {"ND": 0.02}}]}
    runrow, rows = flatten(j)
    assert runrow["nd_pasok_151"] == 0.56 and runrow["n_polls"] == 341
    assert set(rows) == {("2026-11-15", "ND"), ("2026-11-22", "ND"), ("2026-11-22", "NIKI"), ("2026-11-22", "NEW_ENTRANT")}
    nd = rows["2026-11-22", "ND"]  # the run row, not the trend row of the same date
    assert nd["src"] == "run" and nd["share"] == 29.1 and (nd["lo_bonus"], nd["hi_nobonus"]) == (104, 87), nd
    assert rows["2026-11-22", "NIKI"]["seats_bonus"] is None and rows["2026-11-22", "NIKI"]["p_in"] == 0.048
    try:
        flatten({"run": {}})
    except SystemExit as e:
        assert "schema changed" in str(e)
    else:
        raise AssertionError("schema check")
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main("--force" in sys.argv)
