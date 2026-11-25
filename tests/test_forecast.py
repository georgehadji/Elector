"""Checks of analysis/seats_law.py (the law as data) and of the metric table of analysis/forecast.py. The check that
nikh_seats.allocate gives the same national totals as seats_law.national_seats needs the database and is skipped without it."""
import json
import random
import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
import forecast as F
import seats_law as L
from config import DB


class Law(unittest.TestCase):
    def test_bonus_steps(self):
        for share, want in ((24.99, 0), (25, 20), (25.49, 20), (25.5, 21), (29.1, 28), (39.99, 49), (40, 50), (45, 50)):
            self.assertEqual(L.bonus_seats(share), want, share)
        self.assertEqual(L.majority(), 151)

    def test_threshold_and_total(self):
        st = L.national_seats({"A": 40, "B": 30, "C": 27.1, "D": 2.9})
        self.assertNotIn("D", st)
        self.assertEqual(sum(st.values()), 300)
        self.assertEqual(st["A"] - L.hare({"A": 40, "B": 30, "C": 27.1}, 300 - 50)["A"], 50)  # 40%: full bonus

    def test_no_bonus_is_plain_hare(self):
        votes = {"A": 24, "B": 23, "C": 20, "D": 18, "E": 15}
        self.assertEqual(L.national_seats(votes), L.hare(votes, 300))

    def test_random_results_sum_to_300(self):
        rng = random.Random(7)
        for _ in range(500):
            votes = {p: rng.uniform(0.1, 30) for p in "ABCDEFGHIJ"}
            self.assertEqual(sum(L.national_seats(votes).values()), 300)

    def test_integer_votes_unchanged(self):  # nikh_seats passes integer votes: Hare must stay integer arithmetic
        self.assertEqual(L.hare({"A": 7, "B": 5, "C": 1}, 3), {"A": 2, "B": 1, "C": 0})


class Metrics(unittest.TestCase):
    def test_keys_of_forecast_json(self):  # the page and older readers use these names
        self.assertEqual(F.p_key(("ND",)), "p_nd_majority")
        self.assertEqual(F.p_key(("ND", "PASOK")), "p_nd_pasok_151")
        self.assertEqual(F.h_key(("ND", "PASOK", "ELAS")), "hist_nd_pasok_elas")
        self.assertEqual(set(F.METRICS), {"p_bonus", "p_nd_30", *map(F.p_key, F.COALITIONS)})

    def test_partners_gap_parliament(self):
        sims = [({"ND": 30, "PASOK": 12, "EL": 8}, {"ND": 140, "PASOK": 5, "EL": 12}),
                ({"ND": 28, "PASOK": 14, "EL": 7}, {"ND": 120, "PASOK": 40, "EL": 20}),
                ({"ND": 32, "PASOK": 13, "EL": 6}, {"ND": 155, "PASOK": 30, "EL": 10})]
        r = F.partners(sims, ("ND",))
        self.assertEqual(r["n_short"], 2)
        self.assertEqual(r["p"], {"PASOK": 0.5, "EL": 0.5})  # 140+12 and 120+40 reach 151
        self.assertEqual(F.second_gap(sims, "PASOK", "EL"), {4.0: 1, 7.0: 2})
        self.assertEqual(F.counts([3, 1, 3]), {1: 1, 3: 2})

    def test_rates(self):
        sims = [({"ND": 30, "PASOK": 15}, {"ND": 151, "PASOK": 30}),
                ({"ND": 24, "PASOK": 15}, {"ND": 100, "PASOK": 51}),
                ({"ND": 26, "PASOK": 15}, {"ND": 120, "PASOK": 30})]
        r = F.rates(sims)
        self.assertAlmostEqual(r["p_nd_majority"], 1 / 3)
        self.assertAlmostEqual(r["p_nd_pasok_151"], 2 / 3)  # 181, 151, 150
        self.assertAlmostEqual(r["p_bonus"], 2 / 3)
        self.assertAlmostEqual(r["p_nd_30"], 1 / 3)
        self.assertEqual(r["p_pasok_elas_151"], 0)


class AsOf(unittest.TestCase):
    def test_polls_known_then(self):  # a party with fewer than MIN_POLLS polls by the day is left out of the levels
        first = F.polls_to("ELAS")[F.MIN_POLLS - 1][0]
        self.assertTrue(all(o[0] <= first for o in F.polls_to("ND", first)))
        self.assertNotIn("ELAS", F.levels(as_of=first - timedelta(1)))
        self.assertIn("ELAS", F.levels(as_of=first))


class PageHelpers(unittest.TestCase):
    def test_ladder(self):  # P(>=1) = P(>=2) = 1, P(>=3) = 0.5, P(>=4) = 0.2
        import forecast_page as FP
        self.assertEqual(FP.ladder({"2": 50, "3": 30, "4": 20}), [2, 0, 0, 1, 1])

    def test_contested(self):  # A holds 2 of 4 seats, B holds 1 (its 2nd seat only 0.6): one toss-up seat
        import forecast_page as FP
        e = {"seats": 4, "dist": {"A": {"2": .7, "3": .3}, "B": {"1": .4, "2": .6}}}
        t = FP.contested(e, {"A": {"p_in": 1}, "B": {"p_in": .5}})
        self.assertEqual(t["n"], 1)
        self.assertEqual([c[:2] for c in t["cont"]], [("B", 2), ("A", 3)])
        self.assertEqual(t["edge"], ["B"])


class Backtest(unittest.TestCase):
    def test_law_gives_the_ministry_seats(self):  # forecast_backtest.json: votes and seats as the ministry's site gives them
        els = json.loads((ROOT / "analysis" / "forecast_backtest.json").read_text(encoding="utf-8"))["elections"]
        self.assertEqual([e["key"] for e in els], list(L.ELECTION_LAW))
        for e in els:
            site = {p["id"]: p["site"] for p in e["parties"] if p["site"]}
            self.assertEqual(L.national_seats({int(p): v for p, v in e["votes"].items()}, e["law"]), site, e["key"])
            self.assertEqual(e["state"], L.LAWS[e["law"]]["state"], e["key"])
            self.assertTrue(e["match"], e["key"])

    def test_flat_bonus(self):
        self.assertEqual([L.bonus_seats(s, "3636/2008") for s in (10, 35, 45)], [50, 50, 50])
        self.assertEqual(L.bonus_seats(45, "4406/2016"), 0)


@unittest.skipUnless(Path(DB).exists(), "needs data/stavroi.sqlite")
class AllocateMatchesLaw(unittest.TestCase):
    def test_national_totals(self):
        argv, sys.argv = sys.argv, [sys.argv[0], str(DB)]  # nikh_seats opens the database named by sys.argv[1]
        try:
            S = F.seats_module()
        finally:
            sys.argv = argv
        cases = [S.ep_votes("2023/june")]
        V, geo = F.geography()
        rng = random.Random(3)
        for sh in F.simulate(200):
            votes = {p: s for p, s in sh.items() if p != F.OTHER} | {f"{F.OTHER}{i}": sh[F.OTHER] / 10 for i in range(10)}
            cases.append(F.spread(votes, V, geo, rng))
        for ep_v in cases:
            nat = {}
            for pv in ep_v.values():
                for p, v in pv.items():
                    nat[p] = nat.get(p, 0) + v
            res, _ = S.allocate(ep_v)
            self.assertEqual({p: sum(v.values()) for p, v in res.items()}, L.national_seats(nat))


if __name__ == "__main__":
    unittest.main()
