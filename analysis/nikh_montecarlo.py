"""Monte Carlo: probability that NIKH (party 131) reaches 3%, and its seats, from the November 2026 polls.

Inputs (all random, seed fixed):
- Poll share p of valid votes: uniform 1.0-1.7% (NIKH.md section on the threshold).
- Ballot/poll multiplier m: polls understated NIKH in 2023. May 2023 ballot 2.9% vs polls 1.7-1.9% (m 1.53-1.71),
  June 2023 ballot 3.7% vs the same polls (m 1.95-2.18). Three cases: no hidden vote (m = 1), "May-like"
  (m uniform 1.53-1.71) and "2023 range" (m uniform 1.53-2.18). These ranges are kept as first written, but the upper
  one is wrong: the polls taken before June 2023 gave NIKH 2.1-4.1%, so that ballot was about 1.1x its polls. The
  second part of the output uses the measured ratios instead (nikh_polls.miss_2023, nikh_polls.euro_miss).
- Geography: NIKH share per constituency = Euro 2024 pattern x lognormal noise (sd 0.15), rescaled so the national
  share equals p*m. Other parties: June 2023 votes x one lognormal factor per party (sd 0.05), then shrunk
  proportionally (nikh_seats.scenario). This noise moves the seats only, not P(>=3%).
- Turnout does not enter P(>=3%) (the threshold is a share of valid votes). It sets the threshold in votes, so the
  "votes missing" table is given for the valid votes of June 2023 and of May 2023.
Not modelled: ties.
Seats come from nikh_seats.allocate (ν. 4654/2020, simplified as documented there). Unofficial results.

  python -I -X utf8 analysis/nikh_montecarlo.py data/stavroi.sqlite [N]
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
import nikh_seats as S

N = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
NIKH = S.NIKH
june, euro = S.ep_votes("2023/june"), S.ep_votes("2024/euro")
pattern = {ep: euro[ep].get(NIKH, 0) / sum(euro[ep].values()) for ep in june if ep in euro}
assert len(pattern) == len(june), "Euro 2024 missing for some constituency"
CASES = {"χωρίς κρυφή ψήφο (m = 1)": (1.0, 1.0), "όπως τον Μάιο 2023 (m 1,53-1,71)": (1.53, 1.71),
         "εύρος 2023 (m 1,53-2,18)": (1.53, 2.18)}


def seats_at(pct, rng, sd=0.15, sd_other=0.05):
    """NIKH seats (0 below the threshold) at national share pct, with noisy geography and noisy other parties."""
    if pct < 3.0001:  # scenario() rounds votes, so stay clear of exactly 3.0
        return 0
    pat = {ep: s * rng.lognormvariate(0, sd) for ep, s in pattern.items()}
    f = {}  # one factor per party, the same in every constituency
    base = {ep: {p: v * f.setdefault(p, rng.lognormvariate(0, sd_other)) for p, v in pv.items()} for ep, pv in june.items()}
    r, _ = S.allocate(S.scenario(base, pct, pat))
    return sum(r[NIKH].values()) if NIKH in r else 0


def q(xs, f):
    return xs[min(len(xs) - 1, int(f * len(xs)))]


if __name__ == "__main__":
    assert seats_at(2.5, random.Random(1)) == 0  # below the threshold: no seats
    r, _ = S.allocate(S.scenario(june, 3.5, pattern))
    assert sum(r[NIKH].values()) >= 1  # above it: at least the State seat or a constituency one
    assert seats_at(3.5, random.Random(1), 0, 0) == sum(r[NIKH].values())  # zero noise = nikh_seats.scenario
    print(f"N = {N} επαναλήψεις ανά περίπτωση, σπόρος 2026. Δημοσκοπήσεις 1,0-1,7% των έγκυρων.")

    def report(name, pcts, rng):
        pcts = sorted(pcts)
        seats = sorted(s for s in (seats_at(x, rng) for x in pcts) if s)
        print(f"\n{name}\n  ποσοστό κάλπης: διάμεσος {q(pcts, .5):.2f}%, 10%-90%: {q(pcts, .1):.2f}-{q(pcts, .9):.2f}%")
        print(f"  P(≥3%) = {100 * sum(x >= 3 for x in pcts) / N:.1f}%")
        if seats:
            print(f"  έδρες όταν περνά: διάμεσος {q(seats, .5)}, 10%-90%: {q(seats, .1)}-{q(seats, .9)}")
        return pcts

    for name, (lo, hi) in CASES.items():
        rng = random.Random(2026)
        report(name, [rng.uniform(1.0, 1.7) * rng.uniform(lo, hi) for _ in range(N)], rng)

    # poll average of nikh_polls.py (analysis 8): p ~ Normal(average, sd), floor 0.2%; m from the three elections where
    # the miss was measured (per-poll ratios, 10%-90%), not from the ranges of CASES: those compared the June 2023 ballot
    # with polls taken before May 2023
    import nikh_polls as P
    h, qd, tau2, _ = P.fit(P.load())
    m_euro, per = P.euro_miss(h, qd, tau2, P.load())
    k = len(per)
    euro = (per[int(.1 * k)], per[min(k - 1, int(.9 * k))])
    print(f"\n=== Μέσος όρος δημοσκοπήσεων (nikh_polls.py), Ευρωεκλογές 2024: κάλπη/δημοσκοπήσεις 10%-90% {euro[0]:.2f}-{euro[1]:.2f} ===")
    today = {}
    m23 = {e: (per[int(.1 * k3)], per[min(k3 - 1, int(.9 * k3))]) for e, (_, per, k3) in P.miss_2023().items()}
    print("Μάιος 2023: {:.2f}-{:.2f}, Ιούνιος 2023: {:.2f}-{:.2f}".format(*m23["2023/may"], *m23["2023/june"]))
    MEASURED = {"χωρίς σφάλμα (m = 1)": [(1.0, 1.0)], "όπως Ευρωεκλογές 2024": [euro], "όπως Ιούνιος 2023": [m23["2023/june"]],
                "όπως Μάιος 2023": [m23["2023/may"]], "οι τρεις εκλογές ισοπίθανες": [euro, *m23.values()]}
    # stage 4 of NIKH_plan2.md: m drawn from the ballot/poll ratios of the other small parties (nikh_pollerror.py, 23 pairs),
    # alone, with NIKH's own three ratios added, and only the parties polled below 2%
    import nikh_pollerror as E
    emp, low = E.ratios(), E.ratios("lt2")
    own = [r for r, _, _ in P.miss_2023().values()] + [m_euro]
    assert len(emp) >= 20 and len(low) >= 3 and len(own) == 3
    MEASURED.update({"εμπειρική: 23 μικρά κόμματα": [(r, r) for r in emp],
                     "εμπειρική + 3 της ΝΙΚΗΣ": [(r, r) for r in emp + own],
                     "εμπειρική, κάτω από 2% (5 κόμματα)": [(r, r) for r in low]})
    for horizon in (0, 180):
        mu, sd = P.estimate(horizon)
        print(f"\nΜέσος όρος {mu:.2f}%, τυπική απόκλιση {sd:.2f}, σε {horizon} ημέρες από σήμερα")
        for name, ranges in MEASURED.items():
            rng = random.Random(2026)
            pcts = report(name, [max(0.2, rng.gauss(mu, sd)) * rng.uniform(*rng.choice(ranges)) for _ in range(N)], rng)
            if horizon == 0:
                today[name] = pcts
    VJ, VM = (sum(sum(pv.values()) for pv in v.values()) for v in (june, S.ep_votes("2023/may")))
    print(f"\nΨήφοι που λείπουν για το 3% (σήμερα), με έγκυρα Ιουνίου 2023 ({VJ:,}, όριο {.03 * VJ:,.0f}) / Μαΐου 2023 ({VM:,}, όριο {.03 * VM:,.0f})")
    for name, pcts in today.items():
        print(f"  {name}: στη διάμεσο {max(0, 3 - q(pcts, .5)) / 100 * VJ:,.0f} / {max(0, 3 - q(pcts, .5)) / 100 * VM:,.0f}, "
              f"στο 80ό εκατοστημόριο {max(0, 3 - q(pcts, .8)) / 100 * VJ:,.0f} / {max(0, 3 - q(pcts, .8)) / 100 * VM:,.0f}")
    print("\nΕυαισθησία: P(≥3%) αν προστεθούν ψήφοι πάνω από το αποτέλεσμα κάθε επανάληψης (έγκυρα Ιουνίου 2023)")
    adds = (0, 5000, 10000, 20000, 40000, 80000)
    print(f"  {'':<36}" + "".join(f"{f'+{a:,}':>9}" for a in adds))
    for name, pcts in today.items():
        print(f"  {name:<36}" + "".join(f"{100 * sum(x + 100 * a / VJ >= 3 for x in pcts) / N:>8.1f}%" for a in adds))
    print("\nΑπαιτούμενος πολλαπλασιαστής m για να περάσει το 3%, ανά ποσοστό δημοσκόπησης:")
    for p in (1.0, 1.2, 1.4, 1.7):
        print(f"  δημοσκόπηση {p:.1f}% -> m ≥ {3 / p:.2f}")
