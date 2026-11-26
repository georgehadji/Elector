"""What if a new party of Antonis Samaras (SAM) got 4 to 14% of the national vote? Seats, majorities, the bonus.

No new forecasting: the draws of election-day shares are forecast.simulate (elections today, seed 2026), the seats are
forecast.spread + nikh_seats.allocate exactly as in forecast.seat_sims (same seeds, so the baseline here is the forecast's).
Each draw is changed in one way only: SAM is set to exactly L% (L = 4 to 14; the result is conditional on that level, SAM
has no polls and no ballot error of its own), and its L points are taken from the other parties by a source split (SPLITS).
Two assumptions, both judgement, neither from data (SAM has never run):
1. Source split, the share of SAM's L points that comes from each party. Main: mostly ND, some from the parties to its right.
   Alternatives: almost all ND; much more from the right. A party cannot fall below 0.05%; what it cannot give comes from ND.
   The split moves seats: the national seat totals depend only on the national shares.
2. Geography (SAM_GEO), how SAM's votes spread over the 59 constituencies. Main: ND June 2023 (SAM as a split from ND).
   Alternatives: the same with Messinia (Samaras' constituency) doubled; Elliniki Lysi Euro 2024 (the nationalist right);
   flat. The other parties keep forecast.GEO (their own geography does not shrink where SAM is strong; this only moves
   which constituency their seats land in). National seat totals do not depend on geography at all (Hare over 300 on
   national votes, full lists everywhere) up to vote rounding, so this check counts the draws whose totals differ and how
   many seats change constituency.
Bonus (law of June 2023): first party >= 25% gets 20 seats plus 1 per 0.5% above 25%, at most 50; below 25%, none.
Stands in only while the party has no polls: once its column in nikh_polls.csv has forecast.MIN_POLLS polls it is in
forecast.PARTIES (forecast.NEW), this script stops and out/forecast.html shows it as a party of the forecast.
Unofficial; party columns of the polls come from Wikipedia (polls_wiki.py).

Writes analysis/samaras.json too, for the scenario section of out/forecast.html (forecast_page.py): the main split at every
level of LEVELS (the chooser there), the two sensitivity checks at the levels of ALT.

  python -I -X utf8 analysis/samaras_scenarios.py data/stavroi.sqlite [N] > analysis/samaras_scenarios.txt
"""
import json
import random
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
import forecast as F
import seats_law as LAW

SAM = "SAM"
LEVELS = tuple(range(4, 15))  # every level of the chooser on the page: full statistics at each
ALT = (10, 11, 12)  # the levels the two sensitivity checks (source split, geography) are run at
MESSINIA = 46  # ep_id of Μεσσηνίας, June 2023
SEED = F.SEED
# share of SAM's points taken from each party [judgement]; each sums to 1
SPLITS = {"κύρια: κυρίως ΝΔ": {"ND": .70, "EL": .12, "NIKI": .04, "FL": .04, "SE": .03, "SPARTIATES": .02, F.OTHER: .05},
          "σχεδόν όλα ΝΔ": {"ND": .85, "EL": .08, F.OTHER: .07},
          "πολλά από τα δεξιά της ΝΔ": {"ND": .50, "EL": .25, "FL": .08, "NIKI": .06, "SE": .06, "SPARTIATES": .02, F.OTHER: .03}}
MAIN_SPLIT = next(iter(SPLITS))
OUT = Path(__file__).resolve().parent / "samaras.json"  # read by forecast_page.py
SAM_GEO = ("ΝΔ Ιούνιος 2023", "ΝΔ Ιούνιος 2023, Μεσσηνία ×2", "ΕΛ Ευρωεκλογές 2024", "ομοιόμορφα")
MAIN_GEO = SAM_GEO[0]
NAMES = {**{p: n for p, (_, n) in F.PARTIES.items()}, F.OTHER: "Άλλοι", SAM: "Σαμαράς"}
RIGHT = ("EL", "NIKI", "FL", "SE", "SPARTIATES")  # the smaller parties to ND's right, whose 3% SAM puts at risk


def shift(sh, level, split):
    """Shares of one draw with SAM at exactly `level`%, its points taken from the parties of `split` (sum still 100)."""
    out = dict(sh)
    short = 0.0
    for p, w in split.items():
        if p == "ND":
            continue
        take = min(w * level, max(0.0, out[p] - 0.05))
        out[p] -= take
        short += w * level - take
    out["ND"] -= split.get("ND", 0) * level + short
    assert out["ND"] > 0.05, out
    out[SAM] = level  # last key: the noise of spread() for the other parties stays that of the baseline
    return out


def sam_geo(name):
    """{ep: relative share} of SAM, or None (flat)."""
    S, (V, geo) = F.seats_module(), F.geography()
    if name == "ομοιόμορφα":
        return None
    if name == "ΕΛ Ευρωεκλογές 2024":
        return geo["EL"]
    past = S.ep_votes(F.JUNE)
    sh = {ep: past[ep].get(2, 0) / sum(past[ep].values()) for ep in V}  # ND = party 2
    if "Μεσσηνία" in name:
        sh[MESSINIA] *= 2
    mean = sum(sh[ep] * V[ep] for ep in V) / sum(V.values())
    return {ep: sh[ep] / mean for ep in V}


def bonus_of(nat):
    """Bonus seats of the first party for national votes {party: votes} (allocate's rule)."""
    return LAW.bonus_seats(100 * max(nat.values()) / sum(nat.values()))


def run(draws, level=0, split=None, geo_name=MAIN_GEO):
    """[(shares, {party: seats}, {party: {ep or 'state': seats}}, bonus)] as forecast.seat_sims; level 0 = no SAM."""
    S, (V, geo), rng = F.seats_module(), F.geography(), random.Random(SEED + 1)
    for ep, n in S.seats.items():
        S.cands[ep, SAM] = n
    g = sam_geo(geo_name) if level else None
    g = geo | ({SAM: g} if g else {})
    out = []
    for sh in draws:
        sh = shift(sh, level, split) if level else sh
        votes = {p: s for p, s in sh.items() if p not in (F.OTHER, SAM)} | {f"{F.OTHER}{i}": sh[F.OTHER] / 10 for i in range(10)}
        if level:
            votes[SAM] = sh[SAM]
        ep_v = F.spread(votes, V, g, rng)
        res, _ = S.allocate(ep_v)
        tot = {p: sum(v.values()) for p, v in res.items()}
        assert sum(tot.values()) == LAW.SEATS and not any(p.startswith(F.OTHER) for p in tot), tot
        nat = {}
        for pv in ep_v.values():
            for p, v in pv.items():
                nat[p] = nat.get(p, 0) + v
        out.append((sh, tot, res, bonus_of(nat)))
    return out


def p151(sims, parties):
    return sum(sum(st.get(p, 0) for p in parties) >= LAW.MAJORITY for _, st, _, _ in sims) / len(sims)


def coalitions(sims, size=(2, 3)):
    """{(parties): (P reaches 151, P reaches 151 with every member needed)} for every coalition with SAM."""
    seated = sorted({p for _, st, _, _ in sims for p in st if p != SAM}, key=lambda p: -sum(s[1].get(p, 0) for s in sims))
    out = {}
    for k in size:
        for rest in combinations(seated, k - 1):
            c = (SAM, *rest)
            hit = need = 0
            for _, st, _, _ in sims:
                s = sum(st.get(p, 0) for p in c)
                if s >= LAW.MAJORITY:
                    hit += 1
                    need += all(s - st.get(p, 0) < LAW.MAJORITY for p in c)
            if hit:
                out[c] = (hit / len(sims), need / len(sims))
    return out


def stats(sims):
    n = len(sims)
    b = sorted(x for *_, x in sims)
    return {"nd": p151(sims, ["ND"]), "nd_pasok": p151(sims, ["ND", "PASOK"]), "nd_elas": p151(sims, ["ND", "ELAS"]),
            "nd_sam": p151(sims, ["ND", SAM]), "nd_pasok_elas": p151(sims, ["ND", "PASOK", "ELAS"]),
            "bonus": sum(x > 0 for x in b) / n, "bonus_q": [F.q(b, f) for f in (.1, .5, .9)],
            "seats": {p: [F.q(sorted(st.get(p, 0) for _, st, _, _ in sims), f) for f in (.1, .5, .9)] for p in [*F.PARTIES, SAM]},
            "share": {p: [F.q(sorted(sh.get(p, 0) for sh, *_ in sims), f) for f in (.1, .5, .9)] for p in [*F.PARTIES, F.OTHER, SAM]},
            "in": {p: sum(sh.get(p, 0) >= LAW.THRESHOLD for sh, *_ in sims) / n for p in [*F.PARTIES, SAM]},
            "first": {p: sum(max(sh, key=sh.get) == p for sh, *_ in sims) / n for p in ("ND", "ELAS", SAM)}}


def ep_mean(sims, p, ep):
    return sum(res.get(p, {}).get(ep, 0) for _, _, res, _ in sims) / len(sims)


def pct(x):
    return f"{100 * x:.1f}%"


def selftest(draws):
    for split in SPLITS.values():
        assert abs(sum(split.values()) - 1) < 1e-9, split
        for L in LEVELS:
            s = shift(draws[0], L, split)
            assert abs(sum(s.values()) - 100) < 1e-9 and s[SAM] == L and min(s.values()) >= 0.05 - 1e-9, s
    s = shift({"ND": 30, "NIKI": 0.1, F.OTHER: 69.9}, 10, {"ND": .5, "NIKI": .5})  # NIKI can give only 0.05: ND gives the rest
    assert abs(s["NIKI"] - 0.05) < 1e-9 and abs(s["ND"] - 20.05) < 1e-9, s
    rest = {"B": 200, "C": 200, "D": 200}  # out of 1000 votes
    assert bonus_of({"A": 249, "E": 151} | rest) == 0 and bonus_of({"A": 250, "E": 150} | rest) == 20
    assert bonus_of({"A": 300, "B": 250, "C": 250, "D": 200}) == 30 and bonus_of({"A": 500, "B": 500}) == 50
    base = run(draws[:200])  # level 0 reproduces the forecast's own seat_sims
    assert [st for _, st, _, _ in base] == [st for _, st, _ in F.seat_sims(200, 0, seed=SEED)]


if __name__ == "__main__":
    if SAM in F.PARTIES:  # the party is in the polls: the forecast covers it and the page drops the scenario
        sys.exit(f"Το {F.PARTIES[SAM][1]} έχει πλέον ≥ {F.MIN_POLLS} δημοσκοπήσεις: το καλύπτει το forecast.py, το σενάριο δεν τρέχει.")
    N = int(sys.argv[2]) if len(sys.argv) > 2 else F.N_SIMS
    draws = F.simulate(N, 0, seed=SEED)
    selftest(draws)
    base = run(draws)
    main = {L: run(draws, L, SPLITS[MAIN_SPLIT]) for L in LEVELS}
    B, M = stats(base), {L: stats(s) for L, s in main.items()}
    order = sorted(F.PARTIES, key=lambda p: -B["share"][p][1])
    rows = [order[0], SAM, *order[1:]]
    js = {"as_of": str(F.NP.TODAY), "n": N, "seed": SEED, "names": NAMES, "levels": LEVELS, "alt_levels": ALT, "main_split": SPLITS[MAIN_SPLIT],
          "base": B, "by_level": {str(L): M[L] | {"coalitions": []} for L in LEVELS}, "splits": {}, "geo": {}}

    print(f"=== Κόμμα Σαμαρά στο 4–14%: έδρες με το μοντέλο του forecast.py (εκλογές σήμερα, {N:,} προσομοιώσεις, "
          f"σπόρος {SEED}, μέσος όρος δημοσκοπήσεων στις {F.NP.TODAY}) ===")
    print("Σε κάθε προσομοίωση ο Σαμαράς (ΣΑΜ) παίρνει ακριβώς L% και οι L μονάδες βγαίνουν από τα άλλα κόμματα με την κύρια "
          "κατανομή προέλευσης:")
    print("  " + ", ".join(f"{NAMES[p]} {100 * w:.0f}%" for p, w in SPLITS[MAIN_SPLIT].items()) + f"; γεωγραφία ΣΑΜ: {MAIN_GEO}.")
    print("Οι αβεβαιότητες των άλλων κομμάτων (μέσος όρος, λάθος κάλπης) μένουν όπως στο forecast. Διάμεσος και 10-90% των "
          "προσομοιώσεων. Ανεπίσημο· δύο υποθέσεις κρίσης, βλ. το docstring.")

    print("\n--- Σύγκριση με το forecast χωρίς Σαμαρά ---")
    print(f"{'':<28}{'χωρίς ΣΑΜ':>11}" + "".join(f"{f'ΣΑΜ {L}%':>11}" for L in LEVELS))
    for label, f, in_base in (("έδρες ΝΔ (διάμεσος)", lambda s: s["seats"]["ND"][1], True),
                              ("έδρες ΣΑΜ (διάμεσος)", lambda s: s["seats"][SAM][1], False),
                              ("ποσοστό ΝΔ (διάμεσος)", lambda s: f"{s['share']['ND'][1]:.1f}", True),
                              ("P αυτοδυναμία ΝΔ", lambda s: pct(s["nd"]), True),
                              ("P ΝΔ+ΠΑΣΟΚ ≥151", lambda s: pct(s["nd_pasok"]), True),
                              ("P ΝΔ+ΕΛΑΣ ≥151", lambda s: pct(s["nd_elas"]), True),
                              ("P ΝΔ+ΠΑΣΟΚ+ΕΛΑΣ ≥151", lambda s: pct(s["nd_pasok_elas"]), True),
                              ("P ΝΔ+ΣΑΜ ≥151", lambda s: pct(s["nd_sam"]), False),
                              ("P μπόνους (1ο ≥25%)", lambda s: pct(s["bonus"]), True),
                              ("έδρες μπόνους 10-50-90", lambda s: "-".join(map(str, s["bonus_q"])), True),
                              ("P 1ο κόμμα η ΝΔ", lambda s: pct(s["first"]["ND"]), True)):
        print(f"{label:<28}{f(B) if in_base else '—':>11}" + "".join(f"{f(M[L]):>11}" for L in LEVELS))

    for L in LEVELS:
        s, sims = M[L], main[L]
        print(f"\n--- ΣΑΜ {L}% (κύρια κατανομή, γεωγραφία {MAIN_GEO}) ---")
        print(f"  {'κόμμα':<20}{'ποσοστό 10-50-90':>20}{'P ≥3%':>8}{'έδρες 10-50-90':>16}{'χωρίς ΣΑΜ':>12}")
        for p in rows:
            sh, st = s["share"][p], s["seats"][p]
            was = "—" if p == SAM else F.fmt(B["seats"][p])
            print(f"  {NAMES[p]:<20}{f'{sh[0]:.1f}-{sh[1]:.1f}-{sh[2]:.1f}':>20}{pct(s['in'][p]):>8}{F.fmt(st):>16}{was:>12}")
        print(f"  P αυτοδυναμία ΝΔ {pct(s['nd'])}; ΝΔ+ΠΑΣΟΚ ≥151 {pct(s['nd_pasok'])}; ΝΔ+ΕΛΑΣ ≥151 {pct(s['nd_elas'])}")
        print(f"  Μπόνους: P {pct(s['bonus'])}, έδρες 10-50-90 {'-'.join(map(str, s['bonus_q']))} "
              f"(χωρίς ΣΑΜ: P {pct(B['bonus'])}, {'-'.join(map(str, B['bonus_q']))})")
        print("  Συνεργασίες με τον ΣΑΜ που φτάνουν 151 χωρίς περιττό μέλος (P ≥ 0,5%): P να φτάσει και να χρειάζεται κάθε μέλος"
              " / P να φτάσει")
        for c, (hit, need) in sorted(coalitions(sims).items(), key=lambda kv: -kv[1][1]):
            if need >= 0.005:
                js["by_level"][str(L)]["coalitions"].append([c, need, hit])
                print(f"    {' + '.join(NAMES[p] for p in c):<44}{pct(need):>7} / {pct(hit):>6}")

    print("\n--- Ευαισθησία 1: προέλευση των ψήφων του ΣΑΜ (γεωγραφία ΝΔ Ιούνιος 2023) ---")
    for k, sp in SPLITS.items():
        print(f"  {k}: " + ", ".join(f"{NAMES[p]} {100 * w:.0f}%" for p, w in sp.items()))
    print(f"  {'κατανομή':<28}{'L':>4}{'ΝΔ':>5}{'ΣΑΜ':>5}{'ΕΛ':>4}{'ΦΛ':>4}{'ΣΕ':>4}{'P ΦΛ≥3':>8}{'P ΣΕ≥3':>8}"
          f"{'P ΝΔ+ΣΑΜ':>9}{'P ΝΔ+ΠΑΣΟΚ':>11}{'P ΝΔ+ΕΛΑΣ':>10}{'P μπόνους':>10}")
    for k, sp in SPLITS.items():
        for L in ALT:
            s = M[L] if k == MAIN_SPLIT else stats(run(draws, L, sp))
            st = s["seats"]
            js["splits"].setdefault(k, {"split": sp})[str(L)] = {x: s[x] for x in ("nd", "nd_pasok", "nd_elas", "nd_sam", "bonus",
                                                                                   "seats", "in")}
            print(f"  {k:<28}{L:>4}{st['ND'][1]:>5}{st[SAM][1]:>5}{st['EL'][1]:>4}{st['FL'][1]:>4}{st['SE'][1]:>4}"
                  f"{pct(s['in']['FL']):>8}{pct(s['in']['SE']):>8}{pct(s['nd_sam']):>9}{pct(s['nd_pasok']):>11}"
                  f"{pct(s['nd_elas']):>10}{pct(s['bonus']):>10}")
    print("  (ΝΔ, ΣΑΜ, ΕΛ, ΦΛ, ΣΕ: διάμεσος εδρών)")

    print("\n--- Ευαισθησία 2: γεωγραφία του ΣΑΜ (κύρια κατανομή προέλευσης) ---")
    print("  Άλλα σύνολα: προσομοιώσεις όπου κάποιο κόμμα έχει άλλες έδρες στη χώρα / η μεγαλύτερη διαφορά (στρογγύλευση ψήφων "
          "ανά περιφέρεια). Έδρες που αλλάζουν περιφέρεια = ½ Σ_περιφέρειες |αναμενόμενες έδρες − κύρια|· Μεσσηνία: 5 έδρες.")
    print(f"  {'γεωγραφία':<30}{'L':>4}{'άλλα σύνολα':>12}{'μετακ. ΣΑΜ':>11}{'μετακ. ΝΔ':>10}{'ΣΑΜ Μεσσ.':>10}{'ΝΔ Μεσσ.':>9}"
          f"{'ΣΑΜ Επικρ.':>11}")
    eps = [*F.seats_module().seats, "state"]
    for g in SAM_GEO:
        for L in ALT:
            sims = main[L] if g == MAIN_GEO else run(draws, L, SPLITS[MAIN_SPLIT], g)
            diff = [max(abs(a[1].get(p, 0) - b[1].get(p, 0)) for p in {*a[1], *b[1]}) for a, b in zip(sims, main[L], strict=True)]
            moved = {p: sum(abs(ep_mean(sims, p, ep) - ep_mean(main[L], p, ep)) for ep in eps) / 2 for p in (SAM, "ND")}
            js["geo"].setdefault(g, {})[str(L)] = {"differ": sum(d > 0 for d in diff), "max_diff": max(diff),
                                                     "moved_sam": moved[SAM], "moved_nd": moved["ND"],
                                                     "sam_messinia": ep_mean(sims, SAM, MESSINIA)}
            print(f"  {g:<30}{L:>4}{f"{sum(d > 0 for d in diff)} / {max(diff)}":>12}{moved[SAM]:>11.1f}{moved['ND']:>10.1f}"
                  f"{ep_mean(sims, SAM, MESSINIA):>10.2f}{ep_mean(sims, 'ND', MESSINIA):>9.2f}{ep_mean(sims, SAM, 'state'):>11.2f}")
    print(f"  (χωρίς ΣΑΜ: ΝΔ Μεσσηνία {ep_mean(base, 'ND', MESSINIA):.2f})")
    OUT.write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
