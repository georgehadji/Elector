"""Checks of analysis/pollster_record.py (firm names, the track-record table, the weights) and that nikh_polls.kfilter without
weights is unchanged by the optional `wt`."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import nikh_polls as NP
import pollster_record as PR


class PollsterRecord(unittest.TestCase):
    def test_firm_names(self):
        self.assertEqual(PR.firm_of("Μarc/Alpha"), "Marc")  # Greek capital M
        self.assertEqual(PR.firm_of("RealPolls/Dimokratia"), "Real Polls")
        self.assertEqual(PR.firm_of("Prorata"), "ProRata")
        self.assertEqual(PR.firm_of("Pulse"), "Pulse RC")

    def test_table(self):
        rows, bench = PR.table()
        self.assertGreaterEqual(len(rows), 8)
        self.assertTrue(0.5 < bench < 3)
        self.assertEqual([r["avg"] for r in rows], sorted(r["avg"] for r in rows))
        self.assertTrue(all(r["n"] == len(r["by"]) and set(r["by"]) <= set(PR.ELECTIONS) for r in rows))

    def test_same_parties_for_every_firm(self):
        errs = PR.errors()
        for el in PR.ELECTIONS:
            counts = {v[el][2] for v in errs.values() if el in v}
            self.assertEqual(len(counts), 1, el)  # one party set per election, so no firm gains by leaving a party out

    def test_house_check_has_every_firm(self):
        out, rho = PR.house_check()
        self.assertIn("ProRata", {o[0] for o in out})  # the poll file spells it "Prorata"
        self.assertTrue(-1 <= rho <= 1)

    def test_niki_misses(self):
        miss = PR.niki_misses()
        self.assertGreaterEqual(len(miss), 8)
        ballots = {**NP.BALLOT_2023, "2024/euro": NP.EURO}
        for by in miss.values():
            for el, (poll, ballot, end) in by.items():
                self.assertEqual(ballot, ballots[el][1])
                self.assertTrue(0 < (ballots[el][0] - end).days <= PR.WINDOW)
                self.assertTrue(0 < poll < 10)
        self.assertIn("ProRata", miss)  # "Prorata" in nikh_polls.csv

    def test_weights_are_mild(self):
        w = PR.weights()
        self.assertTrue(all(0.7 < v < 1.5 for v in w.values()))
        rows, _ = PR.table()
        self.assertGreater(w[rows[0]["firm"]], w[rows[-1]["firm"]])  # best record counts more than the worst

    def test_no_weights_is_unchanged(self):
        obs = [(date(2026, 1, d), f, 1000, y) for d, f, y in ((1, "A", 2.0), (5, "B", 2.4), (9, "A", 2.2))]
        plain = NP.kfilter(obs, {}, 0.001, 0.01)
        self.assertEqual(plain, NP.kfilter(obs, {}, 0.001, 0.01, wt={}))
        self.assertEqual(plain, NP.kfilter(obs, {}, 0.001, 0.01, wt={"A": 1.0, "B": 1.0}))
        for_b = NP.kfilter(obs, {}, 0.001, 0.01, wt={"B": 4.0})[0][-1][0]  # B is the one high poll (2.4): trusting it lifts the level
        against_b = NP.kfilter(obs, {}, 0.001, 0.01, wt={"B": 0.25})[0][-1][0]
        self.assertGreater(for_b, against_b)


if __name__ == "__main__":
    unittest.main()
