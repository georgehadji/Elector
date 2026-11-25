"""Download per-polling-station results and preference votes for one constituency into SQLite.

Usage: python fetch.py 2023/may 45
       python fetch.py 2023/may all     (every constituency with seats; about 22,000 stations)

Source: the Ministry of Interior results site (built by SingularLogic). The site marks these
results as unofficial; official results are issued later by the courts.
Re-running resumes: stations already stored are skipped.
"""
import json
import re
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
from config import DB, SCHEMA, accented, source  # noqa: E402

WORKERS = 4  # keep the load on a public site low


def get(url, as_json=True):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8")
            return json.loads(body) if as_json else body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"failed after retries: {url}: {err}")


def statics(base, k, table):
    """Lookup table from statics.js: 'party' -> [id, order, name, color, ...],
    'ep' -> [id, name, stations, order, seats, crosses]."""
    text = get(f"{base}/stat/{k}/statics.js", as_json=False)
    m = re.search(table + r"\s*:\s*(\[\[.*?\]\])\s*,?\s*\n", text, re.S)
    return json.loads(m.group(1))


def fetch_station(base, ep, tm_id, k="v"):
    meta = get(f"{base}/stat/{k}/{ep}/tm_{tm_id}.js")
    if meta is None:
        return None
    party = get(f"{base}/dyn/{k}/{ep}/tm_{tm_id}.js")
    if party is None and meta["EP_ID"] != ep:  # a station of voters registered elsewhere: some elections file its
        ep = meta["EP_ID"]                       # results under the constituency of registration (2019, June 2023)
        party = get(f"{base}/dyn/{k}/{ep}/tm_{tm_id}.js")
    return meta, party, get(f"{base}/dyn/{k}/{ep}/tm_vc_{tm_id}.js")


def main(election, ep):
    base, k = source(election)
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)

    for pid, _order, name, color, *_ in statics(base, k, "party"):
        db.execute("INSERT OR REPLACE INTO party VALUES (?,?,?,?)", (election, pid, accented(name), color))

    cands = get(f"{base}/stat/{k}/cd_{ep}.js") or {}
    for pid, by_id in cands.items():
        for cid, c in by_id.items():
            db.execute("INSERT OR REPLACE INTO candidate VALUES (?,?,?,?,?)",
                       (election, ep, int(pid), int(cid), accented(c.get("TvDescr") or c["Descr"])))

    totals = get(f"{base}/dyn/{k}/ep_vc_{ep}.js") or {"party": {}}
    for pid, rows in totals["party"].items():
        for r in rows:
            db.execute("INSERT OR REPLACE INTO ep_total VALUES (?,?,?,?,?)",
                       (election, ep, int(pid), r["CAND_ID"], r["VOTES"]))
    db.commit()

    # Station ids are constituency id * 10000 + sequence; CountTmGeo covers every station
    # located in this constituency, including those of voters registered elsewhere.
    ep_meta = get(f"{base}/stat/{k}/ep_{ep}.js")
    db.execute("INSERT OR REPLACE INTO ep VALUES (?,?,?)", (election, ep, accented(ep_meta["Descr"])))
    count = ep_meta["CountTmGeo"]
    # a station saved before its results were published has valid NULL: fetch it again
    done = {r[0] for r in db.execute("SELECT tm_id FROM station WHERE election=? AND valid IS NOT NULL", (election,))}
    todo = [ep * 10000 + s for s in range(1, count + 1) if ep * 10000 + s not in done]
    print(f"{election} EP {ep}: {count} stations, {len(todo)} to fetch", flush=True)
    # Euro 2024 station files omit den_Descr/dhm_Descr; the names are in statics.js.
    den, dhm = ({r[0]: r[1] for r in statics(base, k, t)} for t in ("den", "dhm"))

    with ThreadPoolExecutor(WORKERS) as pool:
        for n, res in enumerate(pool.map(lambda t: fetch_station(base, ep, t, k), todo), 1):
            if res is None:
                continue
            meta, party, cand = res
            tm = meta["TM_ID"]
            db.execute("INSERT OR REPLACE INTO station VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                election, tm, meta["EP_ID"], meta["EP_ID_GEO"], meta["TM_KIND"],
                meta["EKD_ID"], accented(meta.get("ekd_Descr") or meta.get("EKD_Descr")),
                meta["DEN_ID"], accented(meta.get("den_Descr") or den.get(meta["DEN_ID"])),
                meta["DHM_ID"], accented(meta.get("dhm_Descr") or dhm.get(meta["DHM_ID"])),
                accented(meta["Descr"]), meta.get("CATAL_V"), (party or {}).get("Egkyra")))
            for p in (party or {}).get("party", []):
                db.execute("INSERT OR REPLACE INTO party_votes VALUES (?,?,?,?)",
                           (election, tm, p["PARTY_ID"], p["VOTES"]))
            for pid, rows in ((cand or {}).get("party") or {}).items():
                for r in rows:
                    db.execute("INSERT OR REPLACE INTO cand_votes VALUES (?,?,?,?,?)",
                               (election, tm, int(pid), r["CAND_ID"], r["VOTES"]))
            if n % 100 == 0:
                db.commit()
                print(f"  {n}/{len(todo)}", flush=True)
    # Postal votes (Euro 2024) are published only as constituency totals (VOTES_T in ep_{ep}.js):
    # store them as one pseudo-station of kind Τ, sequence 9999.
    tot = get(f"{base}/dyn/{k}/ep_{ep}.js") or {}
    if tot.get("EgkyraT"):
        tm = ep * 10000 + 9999
        db.execute("INSERT OR REPLACE INTO station VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            election, tm, ep, ep, "Τ", None, None, None, None, None, None,
            "Επιστολική ψήφος (σύνολο περιφέρειας)", tot["GramenoiT"], tot["EgkyraT"]))
        for p in tot["party"]:
            db.execute("INSERT OR REPLACE INTO party_votes VALUES (?,?,?,?)", (election, tm, p["PARTY_ID"], p["VOTES_T"]))
        print(f"postal: {tot['EgkyraT']} valid")
    db.commit()
    print("done")


if __name__ == "__main__":
    election, which = sys.argv[1], sys.argv[2]
    if which == "all":
        eps = [e[0] for e in statics(*source(election), "ep") if e[4] > 0]  # skip abroad (no seats)
        for i, ep in enumerate(eps, 1):
            print(f"[{i}/{len(eps)}]", end=" ")
            main(election, ep)
    else:
        main(election, int(which))
