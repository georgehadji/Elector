"""Checks of the classifier of analysis/nikh_control.py: ministry names merged across reshuffles, topic from
the title, places named in a title, and the ΝΙΚΗ signers of an act. No database or network needed."""
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
import nikh_control as C
from matching import stems


class Ministry(unittest.TestCase):
    def test_reshuffles_merge(self):
        for name in ("Παιδείας, Θρησκευμάτων και Αθλητισμού", "Παιδείας και Θρησκευμάτων"):
            self.assertEqual(C.ministry(name), "Παιδείας και Θρησκευμάτων")
        for name in ("Εθνικής Οικονομίας και Οικονομικών", "Οικονομικών"):
            self.assertEqual(C.ministry(name), "Οικονομικών")
        self.assertEqual(C.ministry("στον Πρωθυπουργό και Κυβερνητικός Εκπρόσωπος"), "Πρωθυπουργός, Επικρατείας")
        self.assertEqual(C.ministry("Κλιματικής Κρίσης και Πολιτικής Προστασίας"),
                         "Κλιματικής Κρίσης, Πολιτικής Προστασίας")

    def test_unknown_kept(self):
        self.assertEqual(C.ministry(" Κάτι νέο "), "Κάτι νέο")


class Category(unittest.TestCase):
    def test_titles(self):
        cases = {
            "Κλείσιμο σχολείων στην επαρχία.": "Παιδεία",
            "Ελλείψεις διερμηνέων στα δημόσια νοσοκομεία.": "Υγεία",
            "Διασφάλιση των εθνικών κυριαρχικών δικαιωμάτων στο Αιγαίο και τιμή στους πεσόντες των Ιμίων.":
                "Εθνικά θέματα, άμυνα, εξωτερική πολιτική",
            "Δημοσιονομικό κόστος χορήγησης αφορολογήτου ύψους 50.000 ευρώ σε πολύτεκνους και τρίτεκνους.":
                "Οικογένεια, δημογραφικό, κοινωνική πρόνοια",
            "Νομοθετημένη δυνατότητα αιμομιξίας κατά την υποβοηθούμενη αναπαραγωγή.":
                "Αξίες, ταυτότητα, ψηφιακός έλεγχος",
            "Βεβήλωση Ιερού Ναού στην Αθήνα.": "Εκκλησία και θρησκεία",
            "Για ποιον λόγο αυξάνονται τα διόδια το 2025;": "Οικονομία, φόροι, ακρίβεια",
        }
        for title, want in cases.items():
            self.assertEqual(C.category(title), want, title)

    def test_ministry_breaks_ties(self):  # parents of a school: family and education tie, the ministry decides
        title = "Διαμαρτυρία του Συλλόγου Γονέων του 45ου Δημοτικού Σχολείου για τη σύμπτυξη τμημάτων."
        self.assertEqual(C.category(title, ["Παιδείας και Θρησκευμάτων"]), "Παιδεία")
        self.assertEqual(C.category("Ζητήματα λειτουργίας.", ["Υγείας"]), "Υγεία")  # no keyword: the ministry
        self.assertEqual(C.category("Ζητήματα λειτουργίας.", ["Υγείας", "Εσωτερικών"]), C.OTHER)  # two: unknown
        self.assertEqual(C.category("Συμφωνία Ελλάδας_Τουρκίας."), "Εθνικά θέματα, άμυνα, εξωτερική πολιτική")

    def test_other(self):
        self.assertEqual(C.category("Ερώτηση."), C.OTHER)

    def test_word_start_only(self):  # "ΤΙΜΕΣ." must not match inside ΕΚΤΙΜΗΣΗ
        self.assertEqual(C.category("Εκτίμηση."), C.OTHER)

    def test_phrases_stay_whole(self):  # "ΜΗ_ΚΡΑΤΙΚ" (private colleges) must not fire on «μη» or «κρατικού» alone
        self.assertNotEqual(C.category("Αιτήσεις διεθνούς προστασίας από μη δικαιούχους"), "Παιδεία")
        self.assertEqual(C.category("Ετοιμότητα κρατικού μηχανισμού ενόψει επόμενης αντιπυρικής περιόδου."),
                         "Υποδομές, ενέργεια, περιβάλλον, πολιτική προστασία")
        self.assertEqual(C.category("Ενδεχόμενα μη κρατικά πανεπιστήμια"), "Παιδεία")


class Places(unittest.TestCase):
    gaz = {stems("Πατρέων"): {31}, stems("Σαμοθράκης"): {1}, stems("Θεσσαλονίκη"): {6, 7},
           stems("Αγίου Δημητρίου"): {62}}

    def test_match(self):
        self.assertEqual(C.places("Οδικό δίκτυο του Δήμου Πατρέων", self.gaz), {31})
        self.assertEqual(C.places("Το λιμάνι της Σαμοθράκης", self.gaz), {1})
        self.assertEqual(C.places("Μετρό Θεσσαλονίκης", self.gaz), {6, 7})
        self.assertEqual(C.places("Σχολεία στον Άγιο Δημήτριο", self.gaz), {62})

    def test_no_match(self):
        self.assertEqual(C.places("Κλείσιμο σχολείων στην επαρχία", self.gaz), set())
        self.assertEqual(C.places("Δημήτριος Αγίου", self.gaz), set())  # order matters


class AnswerDates(unittest.TestCase):
    def test_from_file_numbers(self):
        d = date(2025, 1, 1)
        acts = [{"date": d.replace(day=k), "question_ids": [100 * k], "answer_ids": []} for k in range(1, 11)]
        late = {"date": d, "question_ids": [50], "answer_ids": [705, 990]}  # first answer between days 7 and 8
        early = {"date": d.replace(day=9), "question_ids": [], "answer_ids": [150]}  # never before the act
        C.answer_dates([*acts, late, early])
        self.assertIn(late["answer_est"], (d.replace(day=7), d.replace(day=8)))
        self.assertEqual(early["answer_est"], d.replace(day=9))
        self.assertIsNone(acts[0]["answer_est"])


class Signers(unittest.TestCase):
    def test_nikh(self):
        self.assertEqual(C.nikh_signers(["Κουρουπάκη Ιωάννη Ασπασία", "Παπαδόπουλος  Δημητρίου Νικόλαος",
                                         "Παπαδόπουλος Αβραάμ Νικόλαος"]), ["Κουρουπάκη", "Παπαδόπουλος"])

    def test_expelled_order(self):
        self.assertTrue(C.EXPELLED["Παπαδόπουλος"] < C.EXPELLED["Βρεττός"] < date(2026, 1, 1))


if __name__ == "__main__":
    unittest.main()
