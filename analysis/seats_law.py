"""Greek electoral law as data (LAWS) and the national seat count of one result (national_seats). Pure: no database.

The law lives here and only here: nikh_seats.allocate takes its national step from national_seats, and the forecast
pages (trend, scenarios, backtest, the rules section) read their numbers from LAWS. National seat totals depend only on
the national votes of the parties past the threshold (Hare over them, plus the bonus), not on how the votes spread over
constituencies, so national_seats alone is enough wherever only national totals are needed.

Implemented: ν. 4654/2020 (π.δ. 26/2012 art. 99-100 as amended; elections from June 2023 on). The other laws of past
elections join LAWS with the backtest, each checked against the official seats of its elections.
Simplification (as nikh_seats): ties are broken arbitrarily.
"""
import math

LAWS = {
    "4654/2020": {"seats": 300, "state": 15, "threshold": 3.0,
                  # first party at `from`% or more: `base` seats, plus 1 per full `step` points above `from`, at most `cap`
                  "bonus": {"from": 25.0, "base": 20, "step": 0.5, "cap": 50}},
}
CURRENT = "4654/2020"


def majority(law=CURRENT):
    """Seats for a majority: 151 of 300."""
    return LAWS[law]["seats"] // 2 + 1


def hare(votes, n):
    """Largest-remainder split of n seats in proportion to votes (integers or floats)."""
    tot = sum(votes.values())
    base = {p: int(v * n // tot) for p, v in votes.items()}
    for p in sorted(votes, key=lambda p: -(votes[p] * n / tot - base[p]))[:n - sum(base.values())]:
        base[p] += 1
    return base


def qualifying(votes, law=CURRENT):
    """{party: votes} of the parties at the threshold or above, in the order of votes."""
    valid = sum(votes.values())
    return {p: v for p, v in votes.items() if v >= LAWS[law]["threshold"] / 100 * valid}


def bonus_seats(first_share, law=CURRENT):
    """Bonus seats of a first party with first_share % of the valid votes."""
    b = LAWS[law]["bonus"]
    if not b or first_share < b["from"]:
        return 0
    return min(b["cap"], b["base"] + math.floor((first_share - b["from"]) / b["step"]))


def national_seats(votes, law=CURRENT):
    """{party: seats} of the qualifying parties from national votes or shares {party: votes}; sums to the law's seats."""
    qual = qualifying(votes, law)
    first = max(qual, key=qual.get)
    bonus = bonus_seats(100 * qual[first] / sum(votes.values()), law)
    total = hare(qual, LAWS[law]["seats"] - bonus)
    total[first] += bonus
    assert sum(total.values()) == LAWS[law]["seats"], total
    return total
