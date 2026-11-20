"""Unit tests for name matching (ministry genitive names -> ELSTAT nominative names).

Run: python -I -X utf8 -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # python -I drops the script dir
from matching import aliases, ep_label, find, norm, one_edit, phonetic, stems  # noqa: E402


class Norm(unittest.TestCase):
    def test_strips_accents_case_and_prefixes(self):
        self.assertEqual(norm("Τοπική Κοινότητα Πικέρνης"), "ΠΙΚΕΡΝΗΣ")
        self.assertEqual(norm("Ε.Δ. ΒΑΛΑΩΡΑΣ"), "ΒΑΛΑΩΡΑΣ")
        self.assertEqual(norm("ΙΕΡΑΣ ΠΟΛΗΣ ΜΕΣΟΛΟΓΓΙΟΥ"), "ΜΕΣΟΛΟΓΓΙΟΥ")

    def test_quote_as_capital_alpha_with_tonos(self):
        self.assertEqual(norm("’ργους"), "ΑΡΓΟΥΣ")

    def test_abbreviation_and_parentheses(self):
        self.assertEqual(norm("ΑΓΙΟΥ ΚΩΝ/ΝΟΥ"), "ΑΓΙΟΥ ΚΩΝΣΤΑΝΤΙΝΟΥ")
        self.assertEqual(norm("(ΚΑΣΤΡΑΚΙΟΥ)"), "ΚΑΣΤΡΑΚΙΟΥ")  # a settlement row keeps its own name
        self.assertEqual(norm("ΒΑΛΤΟΥ (ΠΑΛΙΟ)"), "ΒΑΛΤΟΥ")

    def test_empty(self):
        self.assertEqual(norm(None), "")


class Stems(unittest.TestCase):
    def test_case_endings(self):
        self.assertEqual(stems("ΠΙΚΕΡΝΙΟΥ"), stems("Πικέρνης"))
        self.assertEqual(stems("ΝΕΟΥ"), stems("Νέος"))

    def test_spelling(self):
        self.assertEqual(phonetic("ΧΩΤΟΥΣΑΣ"), phonetic("ΧΩΤΟΥΣΣΑΣ"))
        self.assertEqual(stems("ΒΛΙΣΙΔΙΑΣ"), stems("Βλησιδιά"))

    def test_one_edit(self):
        self.assertTrue(one_edit("ΒΑΣΙΛΙΚΑΔ", "ΒΑΣΙΛΙΚΙΑΔ"))
        self.assertFalse(one_edit("ΒΑΣΙΛ", "ΒΑΣΙΛΙΚΑ"))


class Known(unittest.TestCase):
    """Pairs met in the data (moved from build.py's self-check)."""
    def test_pairs(self):
        self.assertEqual(stems("Ε.Δ. ΠΙΚΕΡΝΙΟΥ"), ("ΠΙΚΕΡΝ",))
        self.assertEqual(stems("1 Ε.Δ. ΑΘΗΝΑΙΩΝ"), ("ΑΘΙΝ",))
        for ministry, elstat in [("’ργους", "Άργους"), ("(ΚΟΨΕΙΚΑ)", "Κοψαίικα"), ("Ε.Δ. ΙΕΡΑΣ ΠΟΛΗΣ ΜΕΣΟΛΟΓΓΙΟΥ", "Μεσολογγίου"),
                                 ("Ε.Δ. ΝΕΟΥ ΜΥΛΟΤΟΠΟΥ", "Νέος Μυλότοπος"), ("ΚΩΝ/ΝΟΥ", "Κωνσταντίνου"),
                                 ("Ε.Δ. ΧΩΤΟΥΣΑΣ", "Χωτούσσα"), ("Ε.Δ. ΒΛΙΣΙΔΙΑΣ", "Βλησιδιά"), ("(ΚΑΛΟΝΕΡΙ)", "Καλονέριον")]:
            self.assertEqual(stems(ministry), stems(elstat), ministry)

    def test_one_edit_pairs(self):
        self.assertTrue(one_edit("ΞΑΘΑΤ", "ΞΑΝΘΑΤ") and one_edit("ΚΑΛΟΓΡΕΑΝ", "ΚΑΛΟΓΡΙΑΝ"))
        self.assertFalse(one_edit("ΚΑΛΟΓΡ", "ΚΑΛΑΓΡΙ"))


class Aliases(unittest.TestCase):
    def test_split(self):
        self.assertEqual(aliases("Ωριάς ή Ωργιάς"), ["Ωριάς", "Ωργιάς"])
        self.assertEqual(aliases("Πικέρνης,ο"), ["Πικέρνης"])


class Find(unittest.TestCase):
    INDEX = [("Πικέρνης", "A"), ("Νέοι Ψαθάδες", "B"), ("Κάμπος", "C"), ("Νέα Χηλή", "D"),
             ("Βασιλικιάδες", "E"), ("Έξω Χώρα", "F")]

    def test_exact_and_stem(self):
        self.assertEqual(find("ΠΙΚΕΡΝΙΟΥ", self.INDEX), "A")

    def test_suffix_and_prefix_words(self):
        self.assertEqual(find("ΨΑΘΑΔΩΝ", self.INDEX), "B")
        self.assertEqual(find("Ν ΧΗΛΗΣ", self.INDEX), "D")

    def test_loose_only_when_asked(self):
        self.assertIsNone(find("ΚΑΜΠΟΥ ΒΟΙΩΝ", self.INDEX))
        self.assertEqual(find("ΚΑΜΠΟΥ ΒΟΙΩΝ", self.INDEX, loose=True), "C")
        self.assertEqual(find("ΕΞΩΧΩΡΑΣ", self.INDEX, loose=True), "F")

    def test_ambiguous_is_none(self):
        self.assertIsNone(find("ΑΓΙΟΥ ΓΕΩΡΓΙΟΥ", [("Άγιος Γεώργιος", "X"), ("Άγιος Γεώργιος", "Y")]))

    def test_no_hit(self):
        self.assertIsNone(find("ΑΘΗΝΩΝ", self.INDEX))


class Labels(unittest.TestCase):
    def test_ep_label(self):
        self.assertEqual(ep_label("Α' Αθηνών"), "Α΄ Αθηνών")
        self.assertEqual(ep_label("Β1' Βόρειου Τομέα Αθηνών"), "Β1΄ Βορείου Τομέα Αθηνών")
        self.assertEqual(ep_label("Αρτας"), "Άρτας")


if __name__ == "__main__":
    unittest.main()
