"""Targeting map for NIKH (party 131, or --party) per ELSTAT community -> out/nikh_targets.html.

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
Hot clusters: Getis-Ord Gi* of the June 2023 share, z >= 2.58, the method of analysis/nikh_spatial.py (one community more here:
that script also drops communities without registered voters).

Run build.py <election> all for 2023/may, 2023/june, 2024/euro first, then:
  python -I -X utf8 analysis/nikh_targets_map.py [--party=ID] [--rival=ID] [--out=PATH]

NIKH-only: the seat tiers (hand-entered CORE/MARGINAL from nikh_seats.py; the "Έδρες" tab and tooltip row are dropped for
another party, since nikh_seats.scenario is not called here), the template's NIKH figures and links, the 4.5% pool bar
(national June share of Ελλ. Λύση). Another party needs --out=PATH outside out/ (published); NIKH writes out/nikh_targets.html.
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
import party
from build import communities
from config import HERE, PARTY_GEN
from matching import ep_label
from web import INDEX_DARK, INDEX_LIGHT, fill, meta, secure

out = party.page_path("nikh_targets.html")  # fails early for another party without --out
POOL = (party.RIVAL,)  # Σπαρτιάτες left out: NIKH took almost none of their voters in 2024 (nikh_competition.py)
STRONG, BASE, POOL_MIN, MIN_VALID = 6.0, 3.0, 4.5, 50  # 4.5%: national June share of the pool
HOT, TOP = 2.58, 6  # Gi* z threshold; clusters named in the legend, the rest share one colour
CORE = ["Α' Θεσσαλονίκης", "Β' Θεσσαλονίκης", "Β1' Βόρειου Τομέα Αθηνών", "Β3' Νότιου Τομέα Αθηνών",
        "Α' Ανατολικής Αττικής", "Αχαΐας", "Πιερίας"]
MARGINAL = ["Α' Αθηνών", "Β2' Δυτικού Τομέα Αθηνών", "Λάρισας", "Πέλλας", "Κοζάνης", "Αιτωλοακαρνανίας"]
TIER = {ep_label(n): 0 for n in CORE} | {ep_label(n): 1 for n in MARGINAL} if party.IS_NIKH else {}


def pct(x):
    return 100 * x[0] / x[1] if x and x[1] else None


def hot_clusters(share, geom):
    """Connected groups of hot communities, each a list of codes. share: {code: June share}. Neighbours share a
    boundary vertex; communities without neighbours are left out. Gi* with binary weights including the place itself."""
    verts = defaultdict(set)
    for code in share:
        g = geom[code]
        for poly in g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]:
            for ring in poly:
                for pt in ring:
                    verts[tuple(pt)].add(code)
    adj = defaultdict(set)
    for s in verts.values():
        for a in s:
            adj[a] |= s - {a}
    n = len(adj)
    mean = sum(share[k] for k in adj) / n
    sd = math.sqrt(sum((share[k] - mean) ** 2 for k in adj) / n)
    hot = set()
    for k, nb in adj.items():
        w = 1 + len(nb)
        if (share[k] + sum(share[j] for j in nb) - mean * w) / (sd * math.sqrt((n * w - w * w) / (n - 1))) >= HOT:
            hot.add(k)
    groups, seen = [], set()
    for k in hot:
        if k in seen:
            continue
        seen.add(k)
        group, stack = [], [k]
        while stack:
            a = stack.pop()
            group.append(a)
            for b in adj[a] & hot - seen:
                seen.add(b)
                stack.append(b)
        groups.append(group)
    return groups


features, summary = [], [{"areas": 0, "votes": 0, "pool": 0} for _ in range(6)]
comms = communities(["2023/may", "2023/june", "2024/euro"])
by_code = {}
for code, c in comms.items():
    if "2023-june" not in c["e"]:
        continue
    valid, pv = c["e"]["2023-june"]
    j = [pv.get(party.ID, 0), valid]
    m = [c["e"]["2023-may"][1].get(party.ID, 0), c["e"]["2023-may"][0]] if "2023-may" in c["e"] else None
    e = [c["e"]["2024-euro"][1].get(party.ID, 0), c["e"]["2024-euro"][0]] if "2024-euro" in c["e"] else None
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
    by_code[code] = features[-1]["properties"]

# same population as nikh_spatial.py: at least 50 valid votes in June 2023 and in Euro 2024
share = {k: pct(a["j"]) for k, a in by_code.items() if a["j"][1] >= MIN_VALID and a["e"] and a["e"][1] >= MIN_VALID}
groups = sorted(hot_clusters(share, {k: comms[k]["geometry"] for k in share}),
                key=lambda g: -sum(by_code[k]["j"][0] for k in g))
clusters = []
for i, g in enumerate(groups):
    eps, units = defaultdict(int), defaultdict(int)
    for k in g:
        by_code[k]["h"] = i  # the page names the first TOP in the legend and draws the rest in one colour
        eps[by_code[k]["ep"]] += by_code[k]["j"][0]
        units[by_code[k]["u"]] += by_code[k]["j"][0]
    top = lambda d, n: ", ".join(sorted(d, key=d.get, reverse=True)[:n])  # noqa: E731
    # small clusters sit inside one constituency, so their constituency name repeats: name them by municipal unit
    name = top(eps, 3) if i < TOP else f"{top(units, 2)} ({top(eps, 1)})"
    clusters.append({"name": name, "areas": len(g),
                     "votes": sum(by_code[k]["j"][0] for k in g)})
print(f"hot: {sum(len(g) for g in groups)} communities in {len(groups)} clusters, "
      f"{sum(c['votes'] for c in clusters):,} {'NIKH' if party.IS_NIKH else party.NAME} votes")
for c in clusters:
    print(" ", c)

assert len(TIER) == (len(CORE) + len(MARGINAL)) * party.IS_NIKH
assert TIER.keys() <= {f["properties"]["ep"] for f in features}, set(TIER) - {f["properties"]["ep"] for f in features}
for k, s in enumerate(summary):
    print(k, s)
data = {"summary": summary, "clusters": clusters, "top": TOP, "geo": {"type": "FeatureCollection", "features": features}}
text = (HERE / "analysis" / "nikh_targets_template.html").read_text(encoding="utf-8")
if not party.IS_NIKH:  # the template is written for NIKH: swap the names, drop what only holds for NIKH
    rival_gen = PARTY_GEN.get(party.RIVAL, party.RIVAL_NAME)
    for old, new in (
            ('<p class="rel">Δες και: <a href="nikh_2023-2024.html">χάρτης ανά εκλογικό διαμέρισμα, 2019–2024</a> · '
             '<a href="NIKH_eklegmenoi_2023.html">αναφορά Μαΐου–Ιουνίου</a></p>\n', ""),
            ('  seats: "Έδρες",\n', ""),
            (' + row("Περιφέρεια", TIERS[a.t][0])', ""),
            (" (ΝΙΚΗ 3,7% → 4,4%)", ""),
            (", του κόμματος πιο κοντά στη ΝΙΚΗ. Οι Σπαρτιάτες δεν μετρούν: το 2024 η ΝΙΚΗ δεν πήρε σχεδόν τίποτα από αυτούς.", "."),
            ("Ελλ. Λύσης", rival_gen), ("Ελληνικής Λύσης", rival_gen), ("Ελλ. Λύση", party.RIVAL_NAME),
            ("ΝΙΚΗΣ", party.GEN), ("ΝΙΚΗ", party.NAME)):
        assert old in text, old
        text = text.replace(old, new)
template = fill(text,
                INDEX_LIGHT | {"panel": "#ffffffee", "on": "#1d1d1b", "on-ink": "#fff"},
                INDEX_DARK | {"panel": "#1d2430ee", "on": "#e8edf5", "on-ink": "#171c24"},
                skip="#map")
out.write_text(secure(template.replace("<!--META-->", meta(f"{party.NAME}: χάρτης στόχευσης ανά κοινότητα", f"Πού το κόμμα {party.NAME} έχει περιθώριο να κερδίσει ψήφους: ποσοστό και στόχοι ανά κοινότητα.")).replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))), out),
               encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(features)} areas)")
