"""Municipal units (δημοτικές ενότητες) and the zones A/B/C: the one definition used by nikh_pareto.py and nikh_backtest.py.
Also the valid votes and the 3% threshold in votes (valid_votes, threshold), used by nikh_pareto.py, nikh_floor.py and
nikh_montecarlo.py.

A unit = (station.ep_id, station.den_descr). Registered and valid voters are those of June 2023.
Zones: units sorted by a score (best first); A = first 20% of the registered voters, B = next 30%, C = the rest.
"""
from config import NIKH


def valid_votes(c, election="2023/june"):
    """Valid votes of an election, all stations."""
    return c.execute("SELECT SUM(valid) FROM station WHERE election=?", (election,)).fetchone()[0]


def threshold(c, election="2023/june"):
    """The 3% threshold in votes: 3% of the valid votes (June 2023 unless another election is given), from the DB."""
    return round(.03 * valid_votes(c, election))


def load_units(c, elections, party=NIKH):
    """[{"k": (ep, den), "reg": registered, "valid": valid, "v": {election: party votes}}] for units with registered voters.
    Order = SQL GROUP BY order of the June 2023 stations (kept, so that stable sorts give the same ties as before)."""
    reg = {(ep, den): (r, v) for ep, den, r, v in c.execute(
        "SELECT ep_id, den_descr, SUM(registered), SUM(valid) FROM station WHERE election='2023/june' AND den_descr IS NOT NULL "
        "GROUP BY 1, 2")}
    votes = {e: {(ep, den): n for ep, den, n in c.execute(
        "SELECT s.ep_id, s.den_descr, SUM(p.votes) FROM station s JOIN party_votes p ON p.election=s.election "
        "AND p.tm_id=s.tm_id AND p.party_id=? WHERE s.election=? GROUP BY 1, 2", (party, e))} for e in elections}
    return [{"k": k, "reg": r, "valid": v, "v": {e: votes[e].get(k, 0) for e in elections}} for k, (r, v) in reg.items() if r]


def assign_tiers(units):
    """Set u["tier"] on a list already sorted best first: A while the running registered total is <= 20% of all, B <= 50%, else C."""
    total, acc = sum(u["reg"] for u in units), 0
    for u in units:
        acc += u["reg"]
        u["tier"] = "A" if acc <= 0.2 * total else "B" if acc <= 0.5 * total else "C"
    return total
