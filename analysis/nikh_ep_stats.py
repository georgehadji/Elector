"""Statistical checks of the ΝΙΚΗ MEP's record (§ 24 of NIKH.md), on the cache of nikh_ep.py:
  1. does his rank hold when shared questions are split, when only solo ones count, per month of mandate, and under bootstrap;
  2. are answers to his questions slower than to comparable ones (Kaplan–Meier, log-rank stratified by addressee, kind and quarter);
  3. which topics set him apart (keywords on the English titles of all questions; log-odds with an informative Dirichlet prior);
  4. whom he signs with (co-signing network of all current MEPs);
  5. when he asks more than the Parliament's own calendar predicts (Poisson test per month);
  6. how often he votes in roll calls (share of the roll-call votes held during each MEP's mandate);
  7. how many plenary speeches he makes, against all current MEPs.
  Amendments are not here: the API does not say who tabled an amendment.

  python -I -X utf8 analysis/nikh_ep_stats.py      # -> analysis/nikh_ep_stats.txt (needs `nikh_ep.py fetch` first)
"""
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
import nikh_ep as ep  # noqa: E402

OUT = Path(__file__).with_suffix(".txt")
ME = ep.ANADIOTIS
RNG = np.random.default_rng(2026)
BOOT = 2000
# English stems; a title goes to the first theme it matches (checked against his Greek titles in section 3)
THEMES_EN = {"Τουρκία, Κύπρος, Αλβανία, Πρέσπες": ("turk", "cyprus", "cypriot", "albania", "prespa", "north macedonia", "skopje",
                                                    "blue homeland", "erdo", "occupied", "occupation", "himara", "chimara", "minority in"),
             "Χριστιανοί, Ορθοδοξία, θρησκεία": ("christian", "orthodox", "religio", "church", "monaster"),
             "Μετανάστευση, Σένγκεν": ("migra", "schengen", "asylum", "refugee")}
STOP = set("""a an the of and or to in on for by with from at as is are be its it this that into against after over under about between
eu european union commission member state states question questions new regarding concerning via within than not no more need
use how why what whether""".split())


def theme_of(title, themes):
    t = title.lower()
    return next((k for k, keys in themes.items() if any(w in t for w in keys)), None)


def rank_of(values, who):
    """1 + number of MEPs strictly above `who` (ties share the better rank)."""
    return 1 + sum(v > values[who] for v in values.values())


def km_median(times, events):
    """Kaplan–Meier median: first time the survival curve reaches 0.5 or below (None if it never does)."""
    order = np.lexsort((-np.asarray(events), np.asarray(times)))
    t, e = np.asarray(times)[order], np.asarray(events)[order]
    s, n = 1.0, len(t)
    for i, (ti, ei) in enumerate(zip(t, e)):
        if ei:
            s *= 1 - 1 / (n - i)
            if s <= 0.5:
                return float(ti)
    return None


def logrank(times, events, group, strata):
    """Log-rank test of group 1 vs 0, summed over strata. Returns (observed, expected, chi2, p)."""
    obs = expd = var = 0.0
    by = defaultdict(list)
    for t, e, g, s in zip(times, events, group, strata):
        by[s].append((t, e, g))
    for rows in by.values():
        if len({g for _, _, g in rows}) < 2:
            continue
        rows.sort()
        at_risk, at_risk1 = len(rows), sum(g for _, _, g in rows)
        i = 0
        while i < len(rows):
            t = rows[i][0]
            j = i
            d = d1 = 0
            while j < len(rows) and rows[j][0] == t:
                d += rows[j][1]
                d1 += rows[j][1] and rows[j][2]
                j += 1
            if d and at_risk > 1:
                obs += d1
                expd += d * at_risk1 / at_risk
                var += d * (at_risk1 / at_risk) * (1 - at_risk1 / at_risk) * (at_risk - d) / (at_risk - 1)
            at_risk -= j - i
            at_risk1 -= sum(r[2] for r in rows[i:j])
            i = j
    chi2 = (obs - expd) ** 2 / var if var else float("nan")
    return obs, expd, chi2, stats.chi2.sf(chi2, 1)


def fightin_words(target, rest, prior, top=15):
    """Monroe, Colaresi & Quinn (2008): log-odds of each word in target vs rest, with an informative Dirichlet prior; z-scores."""
    a0, n1, n2 = sum(prior.values()), sum(target.values()), sum(rest.values())
    scale = 1000 / a0  # prior worth 1,000 words
    A = a0 * scale
    z = {}
    for w in set(target) | set(rest):
        a = prior.get(w, 0) * scale + 0.01
        y1, y2 = target.get(w, 0), rest.get(w, 0)
        d = math.log((y1 + a) / (n1 + A - y1 - a)) - math.log((y2 + a) / (n2 + A - y2 - a))
        z[w] = d / math.sqrt(1 / (y1 + a) + 1 / (y2 + a))
    return sorted(z.items(), key=lambda kv: -kv[1])[:top]


def words(title):
    return [w for w in re.findall(r"[a-z]+", title.lower()) if len(w) > 2 and w not in STOP]


def main():
    meps, qs = ep.load()
    en = {}  # English title of every question (the API gives one for all)
    for f in sorted((ep.CACHE / "q").glob("*.json")):
        for q in json.loads(f.read_text(encoding="utf-8")).get("data", []):
            if q["identifier"] in qs:
                en[q["identifier"]] = (q.get("title_dcterms") or {}).get("en", "")
    ids = sorted(meps)
    pos = {m: i for i, m in enumerate(ids)}
    gr = {m for m in ids if meps[m].get("api:country-of-representation") == "GR"}
    grp = {m: meps[m].get("api:political-group", "?") for m in ids}
    name = lambda m: meps[m].get("officialFamilyName") if m in gr else meps[m]["label"]
    mand = ep.mandates(ids)
    lines = []
    p = lines.append
    p(f"Στατιστικοί έλεγχοι για τον Αναδιώτη στο Ευρωκοινοβούλιο, ως {ep.TODAY:%d.%m.%Y} ({len(qs)} ερωτήσεις, {len(ids)} σημερινοί ευρωβουλευτές)")

    # 1. rank under other counts
    full, solo, frac = Counter(), Counter(), Counter()
    for q in qs.values():
        for m in q["authors"]:
            if m in pos:
                full[m] += 1
                frac[m] += 1 / len(q["authors"])
                if len(q["authors"]) == 1:
                    solo[m] += 1
    months = {m: max(1.0, ep.months_in_office(mand[m])) for m in ids}
    per_month = {m: frac[m] / months[m] for m in ids}
    p("")
    p("1. Αντέχει η θέση του; (θέση στους 720· η κοινή ερώτηση μετρά 1 σε κάθε υπογράφοντα, ή 1/k στην κλασματική)")
    for label, c in [("Όλες, 1 σε κάθε υπογράφοντα", full), ("Μόνο όσες υπογράφει μόνος", solo),
                     ("Κλασματική (1/k)", frac), ("Κλασματική ανά μήνα θητείας", per_month)]:
        vals = {m: c.get(m, 0) for m in ids}
        p(f"   {label:30} {vals[ME]:7.1f}  θέση {rank_of(vals, ME):3}  (διάμεσος {statistics.median(vals.values()):.1f})")
    # bootstrap of the fractional rank: resample questions with replacement
    qlist = list(qs.values())
    qi, mi, w = [], [], []
    for k, q in enumerate(qlist):
        for m in q["authors"]:
            if m in pos:
                qi.append(k)
                mi.append(pos[m])
                w.append(1 / len(q["authors"]))
    qi, mi, w = np.array(qi), np.array(mi), np.array(w)
    ranks = []
    for _ in range(BOOT):
        draws = np.bincount(RNG.integers(0, len(qlist), len(qlist)), minlength=len(qlist))
        c = np.bincount(mi, weights=w * draws[qi], minlength=len(ids))
        ranks.append(1 + int((c > c[pos[ME]]).sum()))
    lo, hi = np.percentile(ranks, [2.5, 97.5])
    p(f"   Bootstrap {BOOT} επαναδειγματοληψιών των ερωτήσεων (κλασματική): θέση 95% από {lo:.0f} ως {hi:.0f}, διάμεσος {np.median(ranks):.0f}")
    gr_frac = {m: frac.get(m, 0) for m in gr}
    p(f"   Στους 21 Έλληνες, κλασματική: θέση {rank_of(gr_frac, ME)}· μόνο οι δικές του: θέση {rank_of({m: solo.get(m, 0) for m in gr}, ME)}")
    late = [m for m in ids if mand[m][0][0] > "2024-08-01"]
    p(f"   {len(late)} σημερινοί ευρωβουλευτές μπήκαν μετά τον Ιούλιο 2024· η ανά μήνα μέτρηση τους δίνει δίκαιη σύγκριση.")

    # 2. answer time
    p("")
    p(f"2. Αργούν οι απαντήσεις στις δικές του; (γραπτές ερωτήσεις παλαιότερες από {ep.MIN_AGE} ημέρες, Kaplan–Meier, αναπάντητες ως σήμερα)")
    T, Ev, G, S = [], [], [], []
    for q in qs.values():
        if not q["kind"].startswith("γραπτή") or (ep.TODAY - q["date"]).days < ep.MIN_AGE:
            continue
        T.append((q["answer"] - q["date"]).days if q["answer"] else (ep.TODAY - q["date"]).days)
        Ev.append(1 if q["answer"] else 0)
        G.append(1 if ME in q["authors"] else 0)
        S.append((tuple(sorted(q["to"])), q["kind"], q["date"].year, (q["date"].month - 1) // 3))
    T, Ev, G = np.array(T), np.array(Ev), np.array(G)
    for label, mask in [("Αναδιώτης", G == 1), ("Όλοι οι άλλοι", G == 0)]:
        p(f"   {label:14} n = {mask.sum():5}, διάμεσος KM {km_median(T[mask], Ev[mask]):.0f} ημέρες, αναπάντητες {100 * (1 - Ev[mask].mean()):.1f}%")
    obs, expd, chi2, pv = logrank(T, Ev, G, [0] * len(T))
    p(f"   Log-rank χωρίς στρώματα: απαντήσεις {obs:.0f} παρατηρούμενες / {expd:.1f} αναμενόμενες (λόγος {obs / expd:.2f}), χ² = {chi2:.2f}, p = {pv:.3f}")
    obs, expd, chi2, pv = logrank(T, Ev, G, S)
    p(f"   Log-rank με στρώματα (αποδέκτης × είδος × τρίμηνο κατάθεσης): {obs:.0f} / {expd:.1f} (λόγος {obs / expd:.2f}), χ² = {chi2:.2f}, p = {pv:.3f}")
    p("   Λόγος κάτω από 1 σημαίνει ότι οι απαντήσεις του έρχονται πιο αργά από ό,τι σε συγκρίσιμες ερωτήσεις.")
    by_t = defaultdict(list)
    for q in qs.values():
        if q["answer"] and q["kind"].startswith("γραπτή") and ME in q["authors"]:
            by_t[theme_of(en[q["id"]], THEMES_EN) or "Άλλα"].append((q["answer"] - q["date"]).days)
    p("   Διάμεσες ημέρες των απαντημένων του ανά θέμα: " + ", ".join(f"{t} {statistics.median(v):.0f} (n={len(v)})" for t, v in sorted(by_t.items())))

    # 3. topics
    p("")
    p("3. Τι τον ξεχωρίζει θεματικά (λέξεις του αγγλικού τίτλου, σε όλες τις ερωτήσεις)")
    mine = [q for q in qs.values() if ME in q["authors"]]
    agree = sum((theme_of(en[q["id"]], THEMES_EN) or "Άλλα") == (theme_of(q["title"], ep.THEMES) or "Άλλα") for q in mine)
    p(f"   Συμφωνία αγγλικών και ελληνικών λέξεων-κλειδιών στις {len(mine)} ερωτήσεις του: {agree} ({100 * agree / len(mine):.0f}%)")
    share = {}
    for m in gr:
        mq = [q for q in qs.values() if m in q["authors"]]
        share[m] = Counter(theme_of(en[q["id"]], THEMES_EN) or "Άλλα" for q in mq), len(mq)
    nat = next(iter(THEMES_EN))
    allq = Counter(theme_of(en[q["id"]], THEMES_EN) or "Άλλα" for q in qs.values())
    p("   Όλο το Ευρωκοινοβούλιο: " + ", ".join(f"{k} {100 * v / len(qs):.1f}%" for k, v in allq.most_common()))
    rows = sorted(((100 * c[nat] / n, name(m), grp[m], n) for m, (c, n) in share.items() if n), reverse=True)
    p(f"   Μερίδιο «{nat}» ανά Έλληνα ευρωβουλευτή:")
    for s_, nm, g_, n in rows:
        p(f"     {nm:24}{g_:>9} {s_:5.1f}%  (n={n})")
    c_me, n_me = share[ME]
    o_n = sum(n for m, (c, n) in share.items() if m != ME)
    for t in THEMES_EN:
        o_t = sum(c[t] for m, (c, n) in share.items() if m != ME)
        odds, fp = stats.fisher_exact([[c_me[t], n_me - c_me[t]], [o_t, o_n - o_t]])
        p(f"   «{t}»: Αναδιώτης {100 * c_me[t] / n_me:.1f}% έναντι {100 * o_t / o_n:.1f}% στους άλλους Έλληνες, λόγος πιθανοτήτων {odds:.2f}, Fisher p = {fp:.4f}")
    prior = Counter(w for q in qs.values() for w in words(en[q["id"]]))
    tgt = Counter(w for q in mine for w in words(en[q["id"]]))
    rest = Counter(w for q in qs.values() if ME not in q["authors"] and set(q["authors"]) & gr for w in words(en[q["id"]]))
    p("   Λέξεις που τον ξεχωρίζουν από τους άλλους Έλληνες (z του log-odds, prior όλο το Ευρωκοινοβούλιο):")
    p("     " + ", ".join(f"{w} {z:.1f}" for w, z in fightin_words(tgt, rest, prior)))
    p("   Λέξεις των άλλων Ελλήνων που σπανίζουν σε αυτόν:")
    p("     " + ", ".join(f"{w} {z:.1f}" for w, z in fightin_words(rest, tgt, prior)))

    # 4. co-signing network
    p("")
    p("4. Με ποιους υπογράφει (δίκτυο συνυπογραφών όλων των σημερινών ευρωβουλευτών)")
    g = nx.Graph()
    g.add_nodes_from(ids)
    for q in qs.values():
        a = [m for m in q["authors"] if m in pos]
        for i in range(len(a)):
            for j in range(i + 1, len(a)):
                g.add_edge(a[i], a[j], weight=g.get_edge_data(a[i], a[j], {"weight": 0})["weight"] + 1)
    co_share = {m: sum(len(q["authors"]) > 1 for q in qs.values() if m in q["authors"]) / full[m] for m in ids if full.get(m)}
    p(f"   Μερίδιο κοινών ερωτήσεων: Αναδιώτης {100 * co_share[ME]:.0f}%, διάμεσος ευρωβουλευτής {100 * statistics.median(co_share.values()):.0f}%· "
      f"{sum(v < co_share[ME] for v in co_share.values())} από {len(co_share)} έχουν μικρότερο")
    p(f"   Συνυπογράφοντες: {g.degree(ME)} διαφορετικοί (διάμεσος ευρωβουλευτής {statistics.median(d for _, d in g.degree()):.0f})")
    by_g = Counter()
    for nb in g.neighbors(ME):
        by_g[grp[nb]] += g[ME][nb]["weight"]
    p("   Συνυπογραφές ανά ομάδα του άλλου: " + ", ".join(f"{k} {v}" for k, v in by_g.most_common()))
    p(f"   Έλληνες συνυπογράφοντες: {sum(1 for nb in g.neighbors(ME) if nb in gr)}")
    comms = nx.community.louvain_communities(g, weight="weight", seed=2026)
    mc = next(c for c in comms if ME in c)
    p(f"   Κοινότητα Louvain του: {len(mc)} ευρωβουλευτές, ομάδες " + ", ".join(f"{k} {v}" for k, v in Counter(grp[m] for m in mc).most_common(6))
      + "· Έλληνες: " + (", ".join(name(m) for m in mc if m in gr and m != ME) or "κανένας άλλος"))
    gg = g.subgraph(gr)
    p("   Δεσμοί μεταξύ Ελλήνων (κοινές ερωτήσεις): " + (", ".join(
        f"{name(a)}–{name(b)} {d['weight']}" for a, b, d in sorted(gg.edges(data=True), key=lambda e: -e[2]["weight"])[:10]) or "κανένας"))

    # 5. timing
    p("")
    p("5. Πότε ρωτά περισσότερο απ' ό,τι προβλέπει το ημερολόγιο του Κοινοβουλίου (Poisson ανά μήνα)")
    all_m = Counter(q["date"].strftime("%Y-%m") for q in qs.values())
    me_m = Counter(q["date"].strftime("%Y-%m") for q in mine)
    span = sorted(m for m in all_m if m >= "2024-09")
    tot_me, tot_all = sum(me_m[m] for m in span), sum(all_m[m] for m in span)
    exp = {m: tot_me * all_m[m] / tot_all for m in span}
    chi2 = sum((me_m[m] - exp[m]) ** 2 / exp[m] for m in span)
    p(f"   Από τον Σεπτέμβριο 2024 ({len(span)} μήνες): χ² καλής προσαρμογής {chi2:.1f}, {len(span) - 1} β.ε., p = {stats.chi2.sf(chi2, len(span) - 1):.4f}")
    p(f"   Οι τρεις μεγαλύτερες αποκλίσεις (* = p < 0,05 μετά από διόρθωση Bonferroni για {len(span)} ελέγχους):")
    rows = []
    for m in span:
        hi_p, lo_p = stats.poisson.sf(me_m[m] - 1, exp[m]), stats.poisson.cdf(me_m[m], exp[m])
        rows.append((min(hi_p, lo_p), m, me_m[m], exp[m], "πάνω" if hi_p < lo_p else "κάτω"))
    rows.sort()
    for k, (pv, m, o, e, side) in enumerate(rows):
        if pv * len(span) < 0.05 or k < 3:
            p(f"     {m}: {o} ερωτήσεις, αναμενόμενες {e:.1f} ({side}), p = {pv:.4f}{'  *' if pv * len(span) < 0.05 else ''}")
            for q in sorted((q for q in mine if q["date"].strftime("%Y-%m") == m), key=lambda q: q["date"])[:6]:
                p(f"        {q['date']} {q['title'][:100]}")
    days = Counter(q["date"] for q in mine)
    p(f"   Ημέρες με 3+ ερωτήσεις: {sum(v >= 3 for v in days.values())}· η μεγαλύτερη: {max(days.values())} στις {max(days, key=days.get)}")

    # 6. roll-call votes: share of the votes held during each MEP's mandate in which he is on a voter list
    vts = [v for v in ep.votes() if v["favor"] or v["against"] or v["abstention"]]  # some roll calls come without voter lists
    held, cast, how = Counter(), Counter(), defaultdict(Counter)
    for v in vts:
        for m in ids:
            if ep.in_office(mand[m], v["date"]):
                held[m] += 1
        for k in ("favor", "against", "abstention"):
            for m in v[k]:
                if m in pos:
                    cast[m] += 1
                    how[m][k] += 1
    part = {m: 100 * cast[m] / held[m] for m in ids if held[m]}
    p("")
    p(f"6. Συμμετοχή στις ονομαστικές ψηφοφορίες ({len(vts):,} ψηφοφορίες σε {len({v['date'] for v in vts})} ημέρες Ολομέλειας· "
      "μετρά όσες έγιναν όσο ήταν ευρωβουλευτής)".replace(",", "."))
    p(f"   Αναδιώτης: ψήφισε σε {cast[ME]:,} από {held[ME]:,}".replace(",", ".") + f", {part[ME]:.1f}%· θέση {rank_of(part, ME)} στους {len(part)} "
      f"(κάτω από αυτόν {sum(v < part[ME] for v in part.values())})")
    for label, grp_ids in [("Όλοι", list(part)), ("Έλληνες", [m for m in part if m in gr]), ("Μη εγγεγραμμένοι (NI)", [m for m in part if grp[m] == "NI"])]:
        vals = [part[m] for m in grp_ids]
        p(f"   {label:24} διάμεσος {statistics.median(vals):.1f}%  (n = {len(vals)})")
    tot = sum(how[ME].values())
    p(f"   Συμμετοχή έξω από 0–100%: {sum(not 0 <= v <= 100 for v in part.values())}· η χαμηλότερη {min(part.values()):.1f}%, η υψηλότερη {max(part.values()):.1f}%")
    p("   Πώς ψηφίζει: " + ", ".join(f"{k} {100 * how[ME][k] / tot:.1f}%" for k in ("favor", "against", "abstention"))
      + "· όλοι μαζί: " + ", ".join(f"{k} {100 * sum(how[m][k] for m in ids) / sum(cast.values()):.1f}%" for k in ("favor", "against", "abstention")))
    p("   Έλληνες: " + ", ".join(f"{name(m)} {part[m]:.1f}" for m in sorted((m for m in part if m in gr), key=lambda m: -part[m])))
    me_month = Counter()
    me_held = Counter()
    for v in vts:
        me_held[v["date"][:7]] += 1
        me_month[v["date"][:7]] += any(ME in v[k] for k in ("favor", "against", "abstention"))
    p("   Ανά μήνα (%): " + ", ".join(f"{m} {100 * me_month[m] / me_held[m]:.0f}" for m in sorted(me_held)))

    # 7. plenary speeches of all current MEPs
    sp = {m: len(ep.speeches(m)) for m in ids}
    sp_month = {m: sp[m] / months[m] for m in ids}
    p("")
    p("7. Ομιλίες στην Ολομέλεια (όλοι οι 720)")
    p(f"   Αναδιώτης: {sp[ME]} ομιλίες, θέση {rank_of(sp, ME)} στους {len(ids)}· ανά μήνα θητείας {sp_month[ME]:.2f}, θέση {rank_of(sp_month, ME)}")
    for label, grp_ids in [("Όλοι", ids), ("Έλληνες", [m for m in ids if m in gr]), ("Μη εγγεγραμμένοι (NI)", [m for m in ids if grp[m] == "NI"])]:
        p(f"   {label:24} διάμεσος {statistics.median(sp[m] for m in grp_ids):.0f}, μέσος όρος {statistics.mean(sp[m] for m in grp_ids):.1f}  (n = {len(grp_ids)})")
    p(f"   Λιγότερες από αυτόν έχουν {sum(v < sp[ME] for v in sp.values())} ευρωβουλευτές· καμία ομιλία {sum(v == 0 for v in sp.values())}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
