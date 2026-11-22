"""Monte Carlo: probability that NIKH (party 131) reaches 3%, and its seats, from the November 2026 polls.

Inputs (all random, seed fixed):
- Poll share p of valid votes: uniform 1.0-1.7% (NIKH.md section on the threshold).
- Ballot/poll multiplier m: polls understated NIKH in 2023. May 2023 ballot 2.9% vs polls 1.7-1.9% (m 1.53-1.71),
  June 2023 ballot 3.7% vs the same polls (m 1.95-2.18). Three cases: no hidden vote (m = 1), "May-like"
  (m uniform 1.53-1.71) and "2023 range" (m uniform 1.53-2.18).
- Geography: NIKH share per constituency = Euro 2024 pattern x lognormal noise (sd 0.15), rescaled so the national
  share equals p*m. Other parties keep their June 2023 shares, shrunk proportionally (nikh_seats.scenario).
Not modelled: turnout (the threshold is a share of valid votes), noise in the other parties, ties.
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


def seats_at(pct, rng):
    """NIKH seats (0 below the threshold) at national share pct, with noisy geography."""
    if pct < 3.0001:  # scenario() rounds votes, so stay clear of exactly 3.0
        return 0
    pat = {ep: s * rng.lognormvariate(0, 0.15) for ep, s in pattern.items()}
    r, _ = S.allocate(S.scenario(june, pct, pat))
    return sum(r[NIKH].values()) if NIKH in r else 0


def q(xs, f):
    return xs[min(len(xs) - 1, int(f * len(xs)))]


if __name__ == "__main__":
    assert seats_at(2.5, random.Random(1)) == 0  # below the threshold: no seats
    r, _ = S.allocate(S.scenario(june, 3.5, pattern))
    assert sum(r[NIKH].values()) >= 1  # above it: at least the State seat or a constituency one
    print(f"N = {N} επαναλήψεις ανά περίπτωση, σπόρος 2026. Δημοσκοπήσεις 1,0-1,7% των έγκυρων.")

    def report(name, pcts, rng):
        pcts = sorted(pcts)
        seats = sorted(s for s in (seats_at(x, rng) for x in pcts) if s)
        print(f"\n{name}\n  ποσοστό κάλπης: διάμεσος {q(pcts, .5):.2f}%, 10%-90%: {q(pcts, .1):.2f}-{q(pcts, .9):.2f}%")
        print(f"  P(≥3%) = {100 * sum(x >= 3 for x in pcts) / N:.1f}%")
        if seats:
            print(f"  έδρες όταν περνά: διάμεσος {q(seats, .5)}, 10%-90%: {q(seats, .1)}-{q(seats, .9)}")

    for name, (lo, hi) in CASES.items():
        rng = random.Random(2026)
        report(name, [rng.uniform(1.0, 1.7) * rng.uniform(lo, hi) for _ in range(N)], rng)

    # poll average of nikh_polls.py (analysis 8): p ~ Normal(average, sd), floor 0.2%; m as above plus Euro 2024's miss
    import nikh_polls as P
    h, qd, tau2, _ = P.fit(P.load())
    m_euro, per = P.euro_miss(h, qd, tau2, P.load())
    k = len(per)
    euro = (per[int(.1 * k)], per[min(k - 1, int(.9 * k))])
    print(f"\n=== Μέσος όρος δημοσκοπήσεων (nikh_polls.py), Ευρωεκλογές 2024: κάλπη/δημοσκοπήσεις 10%-90% {euro[0]:.2f}-{euro[1]:.2f} ===")
    for horizon in (0, 180):
        mu, sd = P.estimate(horizon)
        print(f"\nΜέσος όρος {mu:.2f}%, τυπική απόκλιση {sd:.2f}, σε {horizon} ημέρες από σήμερα")
        for name, (lo, hi) in {**CASES, "όπως Ευρωεκλογές 2024 (m 10%-90%)": euro}.items():
            rng = random.Random(2026)
            report(f"{name}", [max(0.2, rng.gauss(mu, sd)) * rng.uniform(lo, hi) for _ in range(N)], rng)
    print("\nΑπαιτούμενος πολλαπλασιαστής m για να περάσει το 3%, ανά ποσοστό δημοσκόπησης:")
    for p in (1.0, 1.2, 1.4, 1.7):
        print(f"  δημοσκόπηση {p:.1f}% -> m ≥ {3 / p:.2f} (2023: 1,53-2,18)")
