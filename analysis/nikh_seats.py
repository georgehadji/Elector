"""Seat allocation simulation (π.δ. 26/2012 art. 99-100 as amended by ν. 4654/2020) and NIKH scenarios.

Rules implemented (June 2023 version: 285 constituency + 15 State seats):
- 3% national threshold; if the first party has >= 25%, 280 seats minus 1 per 0.5% above 25% (max 30)
  are shared by Hare quota + largest remainder among qualifying parties; the rest is the first party's bonus.
- State seats: quota = floor(qualifying votes / 15), integer parts, then largest remainders.
- Constituencies: quota = floor(all valid / seats); integer parts for qualifying parties; single-member
  seats to the top qualifying party; 2-3 seat leftovers to the largest unused remainders, excess removed;
  then, from the smallest qualifying party up, one seat per constituency in descending order of its unused
  remainder until it reaches its national total; anything left is the first party's.
- A party never gets more seats in a constituency than it has candidates there (art. 100 §5).
Simplification: ties are broken arbitrarily.

  python -I -X utf8 analysis/nikh_seats.py data/stavroi.sqlite
"""
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from config import ELECTED, NIKH, PARTY_SHORT, source
from fetch import statics

STATE = 15
c = sqlite3.connect(sys.argv[1])
seats = {e[0]: e[4] for e in statics(*source("2023/june"), "ep") if e[4] > 0}
ep_name = dict(c.execute("SELECT ep_id, name FROM ep WHERE election='2023/june'"))
assert sum(seats.values()) == 300 - STATE, sum(seats.values())
cands = {}  # {(ep, party): candidates on the June 2023 constituency list}
for ep, p, n in c.execute("SELECT ep_id, party_id, COUNT(*) FROM candidate WHERE election='2023/june' GROUP BY 1, 2"):
    cands[ep, p] = n


def ep_votes(e):
    """{ep: {party: votes}} over all stations."""
    out = {}
    for ep, pid, v in c.execute("SELECT s.ep_id, pv.party_id, SUM(pv.votes) FROM station s JOIN party_votes pv "
                                "ON pv.election=s.election AND pv.tm_id=s.tm_id WHERE s.election=? GROUP BY 1, 2", (e,)):
        out.setdefault(ep, {})[pid] = v
    return out


def hare(votes, n):
    """Largest-remainder split of n seats in proportion to votes."""
    tot = sum(votes.values())
    base = {p: v * n // tot for p, v in votes.items()}
    for p in sorted(votes, key=lambda p: -(votes[p] * n / tot - base[p]))[:n - sum(base.values())]:
        base[p] += 1
    return base


def allocate(ep_v):
    """{party: {ep or 'state': seats}} for one election given {ep: {party: votes}}."""
    nat = {}
    for pv in ep_v.values():
        for p, v in pv.items():
            nat[p] = nat.get(p, 0) + v
    valid = sum(nat.values())
    qual = {p: v for p, v in nat.items() if v >= 0.03 * valid}
    first = max(qual, key=qual.get)
    share = 100 * qual[first] / valid
    prop = 300 if share < 25 else 280 - min(30, math.floor((share - 25) / 0.5))
    total = hare(qual, prop)
    total[first] += 300 - prop

    sq = sum(qual.values()) // STATE
    state = {p: v // sq for p, v in qual.items()}
    for p in sorted(qual, key=lambda p: -(qual[p] - state[p] * sq))[:STATE - sum(state.values())]:
        state[p] += 1
    target = {p: total[p] - state[p] for p in qual}

    won = {ep: {p: 0 for p in qual} for ep in ep_v}
    rem = {}
    for ep, pv in ep_v.items():
        s = seats[ep]
        if s == 1:
            won[ep][max((p for p in qual if cands.get((ep, p))), key=lambda p: pv.get(p, 0))] = 1
            continue
        q = sum(pv.values()) // s
        for p in qual:
            won[ep][p] = min(pv.get(p, 0) // q, cands.get((ep, p), 0))
        rem[ep] = {p: pv.get(p, 0) - won[ep][p] * q for p in qual}

    def free(ep):
        return seats[ep] - sum(won[ep].values())

    def have(p):
        return sum(w[p] for w in won.values())

    def room(ep, p):
        return won[ep][p] < cands.get((ep, p), 0)

    for ep in rem:  # 2-3 seat constituencies: leftovers to the largest remainders
        if seats[ep] <= 3:
            for p in sorted((p for p in qual if room(ep, p)), key=lambda p: -rem[ep][p])[:free(ep)]:
                won[ep][p] += 1
    for p in qual:  # remove excess where the remainder is smallest, 3-seat before 2-seat
        while have(p) > target[p]:
            eps = [ep for ep in rem if seats[ep] in (2, 3) and won[ep][p] > 0]
            ep = min(eps, key=lambda ep: (-seats[ep], rem[ep][p]))
            won[ep][p] -= 1
    for p in sorted(qual, key=qual.get):  # smallest party first
        while have(p) < target[p] and any(free(ep) and room(ep, p) for ep in rem):
            for ep in sorted((ep for ep in rem if free(ep) and room(ep, p)), key=lambda ep: -rem[ep][p]):
                if have(p) >= target[p]:
                    break
                won[ep][p] += 1
                rem[ep][p] -= sum(ep_v[ep].values()) // seats[ep]
    for ep in ep_v:  # leftovers: first party
        won[ep][first] += free(ep)
    return {p: {"state": state[p], **{ep: won[ep][p] for ep in ep_v if won[ep][p]}} for p in qual}, valid


def scenario(base, pct, pattern=None, party=NIKH):
    """party (default NIKH; may be a party absent from base) scaled to pct of valid votes nationally, other parties
    shrunk proportionally per constituency. pattern: {ep: share of the party} to use instead of base's geography
    (e.g. Euro 2024)."""
    pat = pattern or {ep: pv.get(party, 0) / sum(pv.values()) for ep, pv in base.items()}
    valid = {ep: sum(pv.values()) for ep, pv in base.items()}
    k = pct / 100 * sum(valid.values()) / sum(pat[ep] * valid[ep] for ep in base)
    out = {}
    for ep, pv in base.items():
        n = round(k * pat[ep] * valid[ep])
        others = valid[ep] - pv.get(party, 0)
        out[ep] = {p: round(v * (valid[ep] - n) / others) for p, v in pv.items() if p != party} | {party: n}
    return out


if __name__ == "__main__":
    june = ep_votes("2023/june")
    res, _ = allocate(june)
    print("Ιούνιος 2023, προσομοίωση:", ", ".join(f"{PARTY_SHORT.get(p, p)} {sum(s.values())}" for p, s in
                                                  sorted(res.items(), key=lambda x: -sum(x[1].values()))))
    nikh_eps = {ep for ep in res[NIKH] if ep != "state"}
    print(f"ΝΙΚΗ: Επικρατείας {res[NIKH]['state']}, περιφέρειες: " + ", ".join(ep_name[ep] for ep in nikh_eps))
    print(f"Ίδιες με τις πραγματικές (config.ELECTED): {len(nikh_eps & set(ELECTED))}/{len(ELECTED)}; "
          f"διαφορές: +{[ep_name[e] for e in nikh_eps - set(ELECTED)]} -{[ep_name[e] for e in set(ELECTED) - nikh_eps]}")

    euro = ep_votes("2024/euro")
    euro_pat = {ep: pv.get(NIKH, 0) / sum(pv.values()) for ep, pv in euro.items() if ep in june}
    for label, pat in (("γεωγραφία Ιουνίου 2023", None), ("γεωγραφία Ευρωεκλογών 2024", euro_pat)):
        print(f"\nΣενάρια ({label}; τα άλλα κόμματα όπως τον Ιούνιο 2023):")
        for pct in (2.9, 3.1, 3.5, 4.0, 4.5, 5.0):  # 3.1: exactly 3.0 rounds under the threshold
            r, _ = allocate(scenario(june, pct, pat))
            s = r.get(NIKH)
            if not s:
                print(f"  {pct:.1f}%: κάτω από το όριο, 0 έδρες")
                continue
            eps = sorted((ep for ep in s if ep != "state"), key=lambda ep: ep_name[ep])
            print(f"  {pct:.1f}%: {sum(s.values())} έδρες (Επικρατείας {s['state']}): " + ", ".join(ep_name[e] for e in eps))


    def has_seat(base, ep, delta):
        """Does NIKH hold a seat in ep after delta votes are added to (or taken from) it there, all else unchanged?"""
        v = {e: dict(pv) for e, pv in base.items()}
        v[ep][NIKH] = max(0, v[ep].get(NIKH, 0) + delta)
        return ep in allocate(v)[0].get(NIKH, {})


    def margin(base, ep, sign, cap=40000):
        """Smallest vote change (added if sign=1, removed if sign=-1) that flips NIKH's seat in ep; None above cap.
        shortcut: bisection assumes one flip point, which holds because only ep's own remainder moves much."""
        start = has_seat(base, ep, 0)
        if has_seat(base, ep, sign * cap) == start:
            return None
        lo, hi = 0, cap
        while hi - lo > 10:
            mid = (lo + hi) // 2
            lo, hi = (lo, mid) if has_seat(base, ep, sign * mid) != start else (mid, hi)
        return hi


    for pct in (3.1, 3.5, 4.0):
        base = scenario(june, pct)
        held = {ep for ep in allocate(base)[0][NIKH] if ep != "state"}
        print(f"\nΠεριθώρια εδρών στο {pct}% (γεωγραφία Ιουνίου 2023· ψήφοι ΝΙΚΗΣ μόνο σε αυτή την περιφέρεια, ±10):")
        rows = [(margin(base, ep, -1), ep) for ep in held]
        print("  Έδρες που έχει, και πόσες ψήφους αντέχει να χάσει εκεί:")
        for m, ep in sorted(rows, key=lambda x: x[0] or 10 ** 9):
            n = base[ep][NIKH]
            print(f"    {ep_name[ep]:<32}{'>40.000' if m is None else f'{m:>7,}'}  ({n:,} ψήφοι ΝΙΚΗΣ"
                  + ("" if m is None else f", {100 * m / n:.0f}%") + ")")
        gains = sorted((m, ep) for ep in base if ep not in held and seats[ep] > 1 if (m := margin(base, ep, 1)) is not None)
        print("  Φθηνότερες επιπλέον έδρες, και πόσες ψήφους θέλει ακόμη εκεί:")
        for m, ep in gains[:10]:
            n = base[ep][NIKH]
            print(f"    {ep_name[ep]:<32}{m:>7,}  ({n:,} ψήφοι ΝΙΚΗΣ, +{100 * m / n:.0f}%)")
