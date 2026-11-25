"""Backtest of the electoral law: seats_law.national_seats, the step the forecast uses for national seats, applied to the
national votes of each past election under the law it was held under (seats_law.ELECTION_LAW), against the seats the
Ministry of the Interior's results site gives each party (dyn1/v/epik_1.js: Edres + EdresEpik; the same site fetch.py
reads). Also checks the law's number of state seats against the site's EdresEpik. 2012 is not on that site.

Writes forecast_backtest.json, which forecast_page.py shows and tests/test_forecast.py recomputes (no network):
{"source", "elections": [{"key", "label", "law", "url", "valid", "state", "match", "votes" {party id: votes, every party},
 "parties": [{"id", "name", "votes", "site", "law"}]}]}   (parties with a seat on the site or by the law, by votes)

    python -I -X utf8 analysis/forecast_backtest.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import seats_law as L
from config import BASE, PARTY_SHORT
from fetch import get

OUT = HERE / "forecast_backtest.json"
PATHS = {"2015/jan": "v2015a", "2015/sep": "v2015b"}  # older elections live under these paths of the same site
LABELS = {"2015/jan": "25 Ιανουαρίου 2015", "2015/sep": "20 Σεπτεμβρίου 2015", "2019": "7 Ιουλίου 2019",
          "2023/may": "21 Μαΐου 2023", "2023/june": "25 Ιουνίου 2023"}
SHORT = {1: "ΠΑΣΟΚ", 57: "ΑΝΕΛ", 75: "Το Ποτάμι", 105: "Δημοκρατική Συμπαράταξη"}  # 2015 parties not in PARTY_SHORT


def check(key):
    url = BASE.format(election=PATHS.get(key, key)) + "/dyn1/v/epik_1.js"
    r = get(url)
    votes = {p["PARTY_ID"]: p["VOTES"] for p in r["party"]}
    assert sum(votes.values()) == r["Egkyra"], (key, sum(votes.values()), r["Egkyra"])  # every valid vote is a party's
    site = {p["PARTY_ID"]: p["Edres"] + p["EdresEpik"] for p in r["party"]}
    law = L.ELECTION_LAW[key]
    mine = L.national_seats(votes, law)
    state = sum(p["EdresEpik"] for p in r["party"])
    ids = sorted({p for p, s in site.items() if s} | set(mine), key=votes.get, reverse=True)
    return {"key": key, "label": LABELS[key], "law": law, "url": url, "valid": r["Egkyra"], "state": state, "votes": votes,
            "match": all(site[p] == mine.get(p, 0) for p in site) and state == L.LAWS[law]["state"],
            "parties": [{"id": p, "name": PARTY_SHORT.get(p) or SHORT[p], "votes": votes[p], "site": site[p],
                         "law": mine.get(p, 0)} for p in ids]}


def main():
    els = [check(k) for k in L.ELECTION_LAW]
    for e in els:
        print(f"{e['label']:>22}  ν. {e['law']}  {'ίδιες' if e['match'] else 'ΔΙΑΦΟΡΑ'}  "
              + "  ".join(f"{p['name']} {p['site']}" + ("" if p["site"] == p["law"] else f"(νόμος {p['law']})")
                          for p in e["parties"]))
    OUT.write_text(json.dumps({"source": BASE.format(election=""), "elections": els}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"wrote {OUT.name}: {sum(e['match'] for e in els)} από {len(els)} εκλογές ίδιες")


if __name__ == "__main__":
    main()
