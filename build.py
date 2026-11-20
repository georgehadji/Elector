"""Build an HTML map of preference votes per electoral district (Ε.Δ.) for one constituency.

Usage: python build.py 2023/may 45   ->   out/2023-may_45.html

Reads data/stavroi.sqlite (filled by fetch.py) and the ELSTAT 2021 boundaries in data/.
Each Ε.Δ. is matched to an ELSTAT local community inside its municipal unit: by community
name, or through a settlement of that community (ELSTAT settlements list). Names are compared
by word stems, because the ministry uses the genitive ("ΠΙΚΕΡΝΙΟΥ") and ELSTAT the nominative
("Πικέρνης"). Urban municipal units with a single community (e.g. Athens) show as one area.
"""
import contextlib
import io
import os
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
from config import DB, ELECTION_NAMES, OUT, SCHEMA, accented, slug  # noqa: E402
from geo import silhouette  # noqa: E402
from matching import boundaries, ep_label, label, match_areas, norm  # noqa: E402
from web import (  # noqa: E402
    FONTS,
    header,
    common_css,
    secure,
    entry,
    fill,
    footer,
    links,
    record,
    render_page,
    write_index,
)

WORKERS = max(1, (os.cpu_count() or 2) - 1)


def main(election, ep):
    db = sqlite3.connect(DB)
    q = lambda sql, *a: db.execute(sql, (election, *a)).fetchall()

    parties = {pid: (name, "#" + color[2:] if color else "#888") for pid, name, color in
               q("SELECT party_id, name, color FROM party WHERE election=?")}
    cands = q("SELECT c.party_id, c.cand_id, c.name, COALESCE(t.votes,0) FROM candidate c "
              "LEFT JOIN ep_total t USING(election, ep_id, party_id, cand_id) "
              "WHERE c.election=? AND c.ep_id=? ORDER BY c.party_id, t.votes DESC", ep)
    # The source writes a capital alpha with tonos as a right quote ("’ννα" = "Άννα").
    cands = [(pid, cid, accented(name), total) for pid, cid, name, total in cands]
    # No published preference votes (June 2023 results site): map party votes / valid instead.
    # (Party leaders still get a constituency total there, so test the per-station data.)
    party_mode = not q("SELECT 1 FROM cand_votes WHERE election=? AND tm_id BETWEEN ? AND ? AND votes > 0 LIMIT 1",
                       ep * 10000, ep * 10000 + 9999)
    if party_mode and not q("SELECT 1 FROM station WHERE election=? AND ep_id=? LIMIT 1", ep):
        sys.exit(f"no stations for {election} EP {ep}: run fetch.py first")

    # Only ordinary stations of this constituency located in it can be placed on the map.
    stations = q("SELECT tm_id, den_descr, ekd_descr, registered, valid FROM station "
                 "WHERE election=? AND ep_id=? AND ep_geo=? AND kind='Κ' ORDER BY tm_id", ep, ep)
    area_of = {tm: (den, ekd) for tm, den, ekd, *_ in stations}
    # A settlement in parentheses follows its own Ε.Δ. in station order: "Ε.Δ. ΒΑΛΑΩΡΑΣ", "(ΚΑΣΤΡΑΚΙΟΥ)".
    parent, last = {}, {}
    for tm, den, ekd, *_ in stations:
        if ekd.startswith("("):
            parent.setdefault((den, ekd), last.get(den))
        else:
            last[den] = ekd
    areas = defaultdict(lambda: {"reg": 0, "valid": 0, "pv": defaultdict(int), "cv": defaultdict(int), "tm": 0})
    for tm, den, ekd, reg, valid in stations:
        a = areas[(den, ekd)]
        a["reg"] += reg or 0
        a["valid"] += valid or 0
        a["tm"] += 1
    lo, hi = ep * 10000, ep * 10000 + 9999  # station ids of this constituency's directory
    for tm, pid, v in q("SELECT tm_id, party_id, votes FROM party_votes WHERE election=? AND tm_id BETWEEN ? AND ?", lo, hi):
        if tm in area_of:
            areas[area_of[tm]]["pv"][pid] += v
    for tm, pid, cid, v in q("SELECT tm_id, party_id, cand_id, votes FROM cand_votes "
                             "WHERE election=? AND tm_id BETWEEN ? AND ?", lo, hi):
        if tm in area_of:
            areas[area_of[tm]]["cv"][f"{pid}:{cid}"] += v

    _, comm_by_code, _ = boundaries()
    hit_of, seat_fallbacks = match_areas(list(areas), parent)
    by_code, unmatched = {}, []
    for (den, ekd), a in sorted(areas.items(), key=lambda kv: (kv[0][1].startswith("("), kv[0])):
        hit = hit_of.get((den, ekd))
        if hit is None:
            unmatched.append({"name": norm(ekd).title() or den, "unit": den, **a})
            continue
        # Several Ε.Δ. can fall in one community (settlements, urban units): sum them.
        if hit not in by_code:
            c = comm_by_code[hit]
            by_code[hit] = {"type": "Feature", "geometry": c["geometry"], "properties": {
                "code": hit, "name": den if label(c).isupper() else label(c), "unit": den, "reg": 0, "valid": 0,
                "tm": 0, "incl": [], "pv": defaultdict(int), "cv": defaultdict(int)}}
        p = by_code[hit]["properties"]
        p["incl"].append(norm(ekd).title())
        for fld in ("reg", "valid", "tm"):
            p[fld] += a[fld]
        for fld in ("pv", "cv"):
            for k, v in a[fld].items():
                p[fld][k] += v
    features = list(by_code.values())

    # Self-check: votes on the map never exceed the official constituency totals.
    mapped = defaultdict(int)
    for f in features:
        for k, v in f["properties"]["cv"].items():
            mapped[k] += v
    cand_list = []
    if party_mode:  # one pseudo-candidate per party, "pid:0"; the template divides by valid votes
        for f in features:
            for pid, v in f["properties"]["pv"].items():
                mapped[f"{pid}:0"] += v
        for pid, total in q("SELECT p.party_id, SUM(p.votes) FROM party_votes p JOIN station s USING(election, tm_id) "
                            "WHERE p.election=? AND s.ep_id=? GROUP BY 1 HAVING SUM(p.votes) > 0", ep):
            k = f"{pid}:0"
            assert mapped[k] <= total, (parties[pid][0], mapped[k], total)
            cand_list.append({"k": k, "party": pid, "name": parties[pid][0], "total": total, "mapped": mapped[k],
                              "partial": False})
        cands = []
    for pid, cid, name, total in cands:
        k = f"{pid}:{cid}"
        assert mapped[k] <= total or total == 0, (name, mapped[k], total)
        # The ministry publishes most of a party leader's crosses only as a constituency total
        # (e.g. Mitsotakis, A' Thessaloniki 2023: 5,017 of 112,971 per station).
        partial = total > 0 and mapped[k] < 0.5 * total
        cand_list.append({"k": k, "party": pid, "name": name, "total": total, "mapped": mapped[k],
                          "partial": partial})
    full = [c for c in cand_list if not c["partial"]]
    coverage = sum(c["mapped"] for c in full) / (sum(c["total"] for c in full) or 1)
    partial_names = [c["name"] for c in cand_list if c["partial"]]
    print(f"areas: {len(areas)} Ε.Δ. -> {len(features)} map areas, {len(unmatched)} unmatched; "
          f"{'party' if party_mode else 'preference'} votes on map: {coverage:.1%}"
          + (f"; no per-station data: {', '.join(partial_names)}" if partial_names else ""))
    if unmatched:
        print("unmatched:", ", ".join(f'{u["name"]} ({u["unit"]})' for u in unmatched))

    ep_name = ep_label((q("SELECT name FROM ep WHERE election=? AND ep_id=?", ep) or [[str(ep)]])[0][0])
    data = {
        "election": election, "ep": ep, "ep_name": ep_name, "mode": "party" if party_mode else "cand",
        "parties": {pid: {"name": parties[pid][0], "color": parties[pid][1]} for pid in {c["party"] for c in cand_list}},
        "cands": cand_list, "unmatched": [{"name": u["name"], "unit": u["unit"]} for u in unmatched],
        "coverage": coverage, "geo": {"type": "FeatureCollection", "features": features},
    }
    out = OUT / f"{slug(election)}_{ep}.html"
    out.parent.mkdir(exist_ok=True)
    data["links"] = links(out.name, election, ep)
    out.write_text(render_page("template.html", data), encoding="utf-8")
    print(f"wrote {out}")
    label_ = "Ανά περιοχή · κόμματα (% εγκύρων)" if party_mode else "Ανά περιοχή · όλοι οι υποψήφιοι"
    return {"ep": ep, "name": ep_name, "file": out.name, "areas": len(areas), "map_areas": len(features),
            "unmatched": len(unmatched), "seat": seat_fallbacks, "coverage": coverage,
            "entry": {out.name: entry(election, ep, ep_name, label_, silhouette([f["geometry"] for f in features]))},
            "matches": [(tm, hit_of[k]) for tm, k in area_of.items() if k in hit_of]}


def save(election, results):
    """The parent process records what the builds produced: maps.json entries and area_match rows."""
    record({f: m for r in results if r.get("file") for f, m in r["entry"].items()})
    with sqlite3.connect(DB, timeout=60) as db:
        db.executescript(SCHEMA)
        for r in results:
            if r.get("file"):
                lo = r["ep"] * 10000
                db.execute("DELETE FROM area_match WHERE election=? AND tm_id BETWEEN ? AND ?", (election, lo, lo + 9999))
                db.executemany("INSERT INTO area_match VALUES (?,?,?)", [(election, tm, c) for tm, c in r["matches"]])


def communities(elections):
    """Mapped results per ELSTAT community, read back from area_match (build.py <election> all first):
    {code: {"n": name, "u": municipal unit, "ep": constituency, "geometry",
            "e": {election slug: [valid votes, {party id: votes}]}}}. Feeds the nationwide pages."""
    _, comm_by_code, _ = boundaries()
    out = {}
    with sqlite3.connect(DB) as db:
        for e in elections:
            if not db.execute("SELECT 1 FROM area_match WHERE election=? LIMIT 1", (e,)).fetchone():
                sys.exit(f"no area_match rows for {e}: run build.py {e} all")
            for code, den, ep_name, valid in db.execute("""
                    SELECT a.comm_code, MIN(s.den_descr), MIN(ep.name), SUM(s.valid) FROM area_match a
                    JOIN station s USING(election, tm_id) JOIN ep ON ep.election = s.election AND ep.ep_id = s.ep_id
                    WHERE a.election=? GROUP BY 1""", (e,)):
                c = comm_by_code[code]
                a = out.setdefault(code, {"n": den if label(c).isupper() else label(c), "u": den,
                                          "ep": ep_label(ep_name), "geometry": c["geometry"], "e": {}})
                a["e"][slug(e)] = [valid or 0, {}]
            for code, pid, v in db.execute("""
                    SELECT a.comm_code, p.party_id, SUM(p.votes) FROM area_match a JOIN party_votes p USING(election, tm_id)
                    WHERE a.election=? GROUP BY 1, 2""", (e,)):
                out[code]["e"][slug(e)][1][pid] = v or 0
    return out


def parties(elections):
    """{party id: {"name", "color"}}; a later election's name wins."""
    out = {}
    with sqlite3.connect(DB) as db:
        for e in elections:
            for pid, name, color in db.execute("SELECT party_id, name, color FROM party WHERE election=?", (e,)):
                out[pid] = {"name": name, "color": "#" + color[2:] if color else "#888"}
    return out


def _build_quiet(election, ep):
    """One constituency in a worker process; its log comes back with the result, so logs stay in order."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            r = main(election, ep)
        except (SystemExit, Exception) as e:  # one bad constituency must not stop the rest
            print(f"FAILED EP {ep}: {e!r}")
            r = {"ep": ep, "name": str(ep), "file": None, "error": repr(e)}
    return r, buf.getvalue()


def build_all(election):
    """Build every fetched constituency and an index page listing them with match quality."""
    eps = [r[0] for r in sqlite3.connect(DB).execute(
        "SELECT ep_id FROM ep WHERE election=? ORDER BY name", (election,))]
    rows = []
    # Constituencies are independent: build them in parallel, each worker loads the boundaries once.
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for ep, (r, log) in zip(eps, pool.map(_build_quiet, [election] * len(eps), eps)):
            print(f"--- EP {ep}\n{log}", end="")
            rows.append(r)
    save(election, rows)
    write_index()
    tr = "".join(
        f'<tr><td><a href="{r["file"]}">{r["name"]}</a></td><td class="n">{r["areas"]}</td>'
        f'<td class="n">{r["map_areas"]}</td><td class="n">{r["unmatched"]}</td><td class="n">{r["seat"]}</td>'
        f'<td class="n">{r["coverage"]:.1%}</td></tr>' if r.get("file") else
        f'<tr><td>{r["name"]}</td><td colspan="5">σφάλμα: {r["error"]}</td></tr>' for r in rows)
    (OUT / f"index_{slug(election)}.html").write_text(secure(fill(f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Κάλυψη χαρτών · {ELECTION_NAMES.get(election, election)}</title>
{FONTS}
<script>/*THEME_JS*/</script><style>{common_css()}
main{{max-width:900px}} p{{color:var(--ink-2)}} .wrap{{overflow-x:auto}}
@media (max-width:599px){{th,td{{padding:6px 4px}} th{{font-size:11px}} td{{font-size:13px}}}}
@media (pointer:coarse){{td a{{display:inline-block;padding:13px 0}}}}</style></head><body><main id="main">
{header()}
<h1>Κάλυψη χαρτών · {ELECTION_NAMES.get(election, election)}</h1>
<p>Ε.Δ.: εκλογικά διαμερίσματα · Περιοχές: κοινότητες στον χάρτη · Έδρα: διαμερίσματα που μπήκαν στην κοινότητα-έδρα
χωρίς αντιστοίχιση ονόματος · Κάλυψη: σταυροί στον χάρτη ως ποσοστό του συνόλου.</p>
<div class="wrap"><table><thead><tr><th>Περιφέρεια</th><th class="n">Ε.Δ.</th><th class="n">Περιοχές</th><th class="n">Χωρίς χάρτη</th>
<th class="n">Έδρα</th><th class="n">Κάλυψη</th></tr></thead><tbody>{tr}</tbody></table></div>
{footer()}</main></body></html>""")),
                                                                                          encoding="utf-8")
    ok = [r for r in rows if r.get("file")]
    print(f"\n{len(ok)}/{len(rows)} built; unmatched Ε.Δ.: {sum(r['unmatched'] for r in ok)}, "
          f"seat fallbacks: {sum(r['seat'] for r in ok)}, lowest coverage: "
          + ", ".join(f"{r['name']} {r['coverage']:.1%}" for r in sorted(ok, key=lambda r: r["coverage"])[:5]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "index":  # rewrite out/index.html from out/maps.json
        write_index()
    elif sys.argv[2] == "all":
        build_all(sys.argv[1])
    else:
        r = main(sys.argv[1], int(sys.argv[2]))
        save(sys.argv[1], [r])
        write_index()
