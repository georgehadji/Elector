"""Targeting map for NIKH (party 131) per ELSTAT community -> out/nikh_targets.html.

Classes (June 2023 share s, Euro 2024 share e, Ελλ. Λύση June share pool):
  0 κάστρο σε φθορά   s >= 6% and e < s
  1 κάστρο            s >= 6%
  2 βάση σε φθορά     3% <= s < 6% and e < s
  3 βάση              3% <= s < 6%
  4 δεξαμενή          s < 3% and pool >= 4.5% (about its national share)
  5 υπόλοιπα
Euro 2024 had far lower turnout, which raised small parties' shares nationally (NIKH 3.7% -> 4.4%), so a share
that fell in a community means NIKH kept fewer voters there than turnout alone explains.
Seat tiers per constituency come from analysis/nikh_seats.py (core = elected in every scenario 3.1-5%).

Run build.py <election> all for 2023/may, 2023/june, 2024/euro first, then:
  python -I -X utf8 analysis/nikh_targets_map.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from build import communities
from config import HERE, OUT
from matching import ep_label
from web import INDEX_DARK, INDEX_LIGHT, fill, secure

NIKH, POOL = 131, (108,)  # Σπαρτιάτες left out: NIKH took almost none of their voters in 2024 (nikh_competition.py)
STRONG, BASE, POOL_MIN, MIN_VALID = 6.0, 3.0, 4.5, 50  # 4.5%: national June share of the pool
CORE = ["Α' Θεσσαλονίκης", "Β' Θεσσαλονίκης", "Β1' Βόρειου Τομέα Αθηνών", "Β3' Νότιου Τομέα Αθηνών",
        "Α' Ανατολικής Αττικής", "Αχαΐας", "Πιερίας"]
MARGINAL = ["Α' Αθηνών", "Β2' Δυτικού Τομέα Αθηνών", "Λάρισας", "Πέλλας", "Κοζάνης", "Αιτωλοακαρνανίας"]
TIER = {ep_label(n): 0 for n in CORE} | {ep_label(n): 1 for n in MARGINAL}


def pct(x):
    return 100 * x[0] / x[1] if x and x[1] else None


features, summary = [], [{"areas": 0, "votes": 0, "pool": 0} for _ in range(6)]
for c in communities(["2023/may", "2023/june", "2024/euro"]).values():
    if "2023-june" not in c["e"]:
        continue
    valid, pv = c["e"]["2023-june"]
    j = [pv.get(NIKH, 0), valid]
    m = [c["e"]["2023-may"][1].get(NIKH, 0), c["e"]["2023-may"][0]] if "2023-may" in c["e"] else None
    e = [c["e"]["2024-euro"][1].get(NIKH, 0), c["e"]["2024-euro"][0]] if "2024-euro" in c["e"] else None
    pool = sum(pv.get(p, 0) for p in POOL)
    s, es, ps = pct(j), pct(e), 100 * pool / valid if valid else 0
    if s is None or valid < MIN_VALID:
        k = 5
    elif s >= STRONG:
        k = 0 if es is not None and es < s else 1
    elif s >= BASE:
        k = 2 if es is not None and es < s else 3
    else:
        k = 4 if ps >= POOL_MIN else 5
    summary[k]["areas"] += 1
    summary[k]["votes"] += j[0]
    summary[k]["pool"] += pool
    features.append({"type": "Feature", "geometry": c["geometry"],
                     "properties": {"n": c["n"], "u": c["u"], "ep": c["ep"], "k": k, "t": TIER.get(c["ep"], 2),
                                    "m": m, "j": j, "e": e, "p": pool}})

assert len(TIER) == len(CORE) + len(MARGINAL)
assert TIER.keys() <= {f["properties"]["ep"] for f in features}, set(TIER) - {f["properties"]["ep"] for f in features}
for k, s in enumerate(summary):
    print(k, s)
data = {"summary": summary, "geo": {"type": "FeatureCollection", "features": features}}
template = fill((HERE / "analysis" / "nikh_targets_template.html").read_text(encoding="utf-8"),
                INDEX_LIGHT | {"panel": "#ffffffee", "on": "#1d1d1b", "on-ink": "#fff"},
                INDEX_DARK | {"panel": "#1d2430ee", "on": "#e8edf5", "on-ink": "#171c24"},
                skip="#map", compact=True)
out = OUT / "nikh_targets.html"
out.write_text(secure(template.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))),
               encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(features)} areas)")
