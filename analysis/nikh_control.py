"""Parliamentary oversight of the MPs elected with ΝΙΚΗ (party 131): classify every act and count.

Input: the cache of nikh_control_fetch.py (data/parl_control/: Parliament listing and act pages, Vouliwatch JSON),
the results db (place names: municipalities and municipal units per constituency, June 2023) and
nikh_control_baseline.csv (acts per MP of every group, from Vouliwatch's «Πιο δραστήριοι βουλευτές»,
groups as on the day it was saved).
Output: nikh_control.csv (one row per act), nikh_control.txt (the tables).

Classification (all rules in this file, from the titles only):
  - ministry: the Parliament's ministry names, merged across reshuffles into one name per portfolio (MINISTRIES);
  - topic: a fixed list of categories (CATEGORIES), each a set of word beginnings; the category with the most
    hits wins; a tie that includes the first two categories (church, values) goes to them; any other tie or a
    title with no hit is settled by the category of the act's ministry (MINISTRY_CATEGORY),
    else the tie goes to the one listed first and no hit is «Άλλο»;
  - place: a municipality, municipal unit or constituency named in the title (stems, as matching.py) → its
    constituencies; «own» only when the place lies in one constituency, that of a ΝΙΚΗ MP who signed (names of
    wider areas, WIDE, are counted apart).
Group at filing: Παπαδόπουλος and Βρεττός were expelled (EXPELLED dates); an act they filed on or after that
day is not counted as ΝΙΚΗ group work. Answers: the Parliament page lists answer files (answered yes/no) but no
date; the day of the first answer is estimated from the file numbers (answer_dates) and checked against the few
dates Vouliwatch gives, the «last change» day of acts with one answer file, and the letter date of a random
sample of answer PDFs (sample_report, from nikh_control_fetch.py answers), which also gives who signed. Vouliwatch's grade of each answer is its own, made with AI.

  python -I -X utf8 analysis/nikh_control.py data/stavroi.sqlite
"""
import bisect
import csv
import html
import json
import re
import sqlite3
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # python -I drops the script dir
sys.path.insert(0, str(HERE))
from nikh_control_fetch import CACHE, MPS, START

from matching import norm, stems

OUT_CSV, OUT_TXT, BASELINE = HERE / "nikh_control.csv", HERE / "nikh_control.txt", HERE / "nikh_control_baseline.csv"
# Expelled from ΝΙΚΗ (party announcement / notice to Parliament); they kept their seats as independents.
EXPELLED = {"Παπαδόπουλος": date(2025, 5, 5), "Βρεττός": date(2025, 9, 28)}
WRITTEN = {"Ερωτήσεις", "Ερώτηση σε συνδυασμό με Α.Κ.Ε.", "Α.Κ.Ε.", "Α.Κ.Ε. σε συνδυασμό με ερώτηση", "Αναφορές"}
KIND_SHORT = {"Ερωτήσεις": "Ερώτηση", "Ερώτηση σε συνδυασμό με Α.Κ.Ε.": "Ερώτηση με ΑΚΕ", "Α.Κ.Ε.": "ΑΚΕ",
              "Α.Κ.Ε. σε συνδυασμό με ερώτηση": "ΑΚΕ με ερώτηση", "Αναφορές": "Αναφορά",
              "Επίκαιρες Ερωτήσεις": "Επίκαιρη ερώτηση", "Επερωτήσεις": "Επερώτηση",
              "Επίκαιρες Επερωτήσεις": "Επίκαιρη επερώτηση", "Α.Κ.Ε. που μετατράπηκε σε επερώτηση": "ΑΚΕ → επερώτηση"}
MIN_AGE = 60  # days: acts younger than this are left out of answer rates (the deadline is 25 days for questions)

# Portfolio: first pattern that matches the normalised ministry name (norm(): no accents, upper case).
MINISTRIES = [
    ("Πρωθυπουργός, Επικρατείας", r"ΠΡΩΘΥΠΟΥΡΓ|ΕΠΙΚΡΑΤΕΙΑΣ|ΑΝΤΙΠΡΟΕΔΡΟΣ ΤΗΣ ΚΥΒΕΡΝΗΣΗΣ"),
    ("Οικονομικών", r"ΟΙΚΟΝΟΜΙΚΩΝ|ΟΙΚΟΝΟΜΙΑΣ"),
    ("Παιδείας και Θρησκευμάτων", r"ΠΑΙΔΕΙΑΣ"),
    ("Υγείας", r"ΥΓΕΙΑΣ"),
    ("Εξωτερικών", r"ΕΞΩΤΕΡΙΚΩΝ"),
    ("Εθνικής Άμυνας", r"ΑΜΥΝΑΣ"),
    ("Εσωτερικών", r"ΕΣΩΤΕΡΙΚΩΝ"),
    ("Προστασίας του Πολίτη", r"ΠΡΟΣΤΑΣΙΑΣ ΤΟΥ ΠΟΛΙΤΗ"),
    ("Δικαιοσύνης", r"ΔΙΚΑΙΟΣΥΝΗΣ"),
    ("Αγροτικής Ανάπτυξης", r"ΑΓΡΟΤΙΚΗΣ"),
    ("Περιβάλλοντος και Ενέργειας", r"ΠΕΡΙΒΑΛΛΟΝΤΟΣ|ΕΝΕΡΓΕΙΑΣ"),
    ("Υποδομών και Μεταφορών", r"ΥΠΟΔΟΜΩΝ|ΜΕΤΑΦΟΡΩΝ"),
    ("Εργασίας", r"ΕΡΓΑΣΙΑΣ"),
    ("Κοινωνικής Συνοχής και Οικογένειας", r"ΚΟΙΝΩΝΙΚΗΣ ΣΥΝΟΧΗΣ|ΟΙΚΟΓΕΝΕΙΑΣ|ΙΣΟΤΗΤΑΣ"),
    ("Μετανάστευσης", r"ΜΕΤΑΝΑΣΤΕΥΣΗΣ"),
    ("Ναυτιλίας", r"ΝΑΥΤΙΛΙΑΣ"),
    ("Κλιματικής Κρίσης, Πολιτικής Προστασίας", r"ΚΛΙΜΑΤΙΚΗΣ|ΠΟΛΙΤΙΚΗΣ ΠΡΟΣΤΑΣΙΑΣ"),
    ("Ανάπτυξης", r"ΑΝΑΠΤΥΞΗΣ"),
    ("Πολιτισμού", r"ΠΟΛΙΤΙΣΜΟΥ"),
    ("Τουρισμού", r"ΤΟΥΡΙΣΜΟΥ"),
    ("Ψηφιακής Διακυβέρνησης", r"ΨΗΦΙΑΚΗΣ"),
    ("Κοινωνικής Ασφάλισης", r"ΑΣΦΑΛΙΣΗΣ"),
    ("Μακεδονίας και Θράκης", r"ΜΑΚΕΔΟΝΙΑΣ"),
    ("Κοινοβουλευτικού Έργου", r"ΚΟΙΝΟΒΟΥΛΕΥΤΙΚΟΥ"),
]

# Topic: word beginnings in norm() form; "_" joins the words of a phrase, "*" is the rest of a word,
# a final "." means the whole word.
# The category with most distinct hits wins; order breaks ties (more specific first).
CATEGORIES = [
    ("Εκκλησία και θρησκεία", (
        "ΕΚΚΛΗΣΙ ΘΡΗΣΚ ΙΕΡΑ ΙΕΡΟ ΙΕΡΕ ΙΕΡΩΝ ΚΛΗΡΙΚ ΜΟΝΑΣΤ ΜΗΤΡΟΠΟΛ ΝΑΟ. ΝΑΟΥ. ΝΑΩΝ. ΝΑΟΥΣ. ΟΡΘΟΔΟΞ ΑΓΙΟ_ΟΡΟΣ "
        "ΑΓΙΟΥ_ΟΡΟΥΣ ΑΓΙΟΡΕΙΤ ΠΑΤΡΙΑΡΧ ΑΡΧΙΕΠΙΣΚΟΠ ΧΡΙΣΤΙΑΝ ΧΡΙΣΤΟΥΓΕΝΝ ΠΑΣΧΑ ΠΑΣΧΑΛΙΝ ΕΙΚΟΝΑ. ΕΙΚΟΝΕΣ. ΕΙΚΟΝΩΝ. "
        "ΑΓΙΟΓΡΑΦ ΘΕΟΛΟΓ ΙΣΛΑΜ ΤΖΑΜΙ ΜΟΥΦΤ ΒΛΑΣΦΗΜ ΒΕΒΗΛ ΣΑΤΑΝ ΑΓΙΑΣ_ΣΟΦΙΑΣ ΚΑΤΗΧΗΤ")),
    ("Αξίες, ταυτότητα, ψηφιακός έλεγχος", (
        "ΑΜΒΛΩΣ ΕΚΤΡΩΣ ΠΑΡΕΝΘΕΤ ΟΜΟΦΥΛ ΛΟΑΤΚΙ ΦΥΛΟΥ ΦΥΛΟ. ΤΡΑΝΣ ΑΙΜΟΜΙΞ ΥΠΟΒΟΗΘΟΥΜΕΝ ΣΕΞΟΥΑΛΙΚ ΔΙΑΠΑΙΔΑΓΩΓ ΤΑΥΤΟΤΗΤ "
        "ΨΗΦΙΑΚ ΠΡΟΣΩΠΙΚ_ΔΕΔΟΜΕΝ ΚΑΜΕΡ ΕΠΙΤΗΡΗΣ ΤΕΧΝΗΤΗΣ?_ΝΟΗΜΟΣΥΝ ΠΟΡΝΟΓΡΑΦ ΕΘΙΣΜ ΚΙΝΗΤ*_ΤΗΛΕΦΩΝ ΚΟΙΝΩΝΙΚ*_ΔΙΚΤΥ "
        "ΕΥΘΑΝΑΣ ΛΟΓΟΚΡΙΣ ΕΛΕΥΘΕΡΙΑΣ?_ΤΟΥ_ΛΟΓΟΥ ΤΖΟΓ ΚΑΖΙΝΟ ΤΥΧΕΡΑ?_ΠΑΙΓΝ ΤΥΧΕΡΩΝ_ΠΑΙΓΝ ΜΑΣΚ ΠΡΟΣΩΠΙΚ*_ΑΡΙΘΜ ΜΕΤΡΗΤ "
        "ΔΕΔΟΜΕΝΩΝ. EUROPRIDE PRIDE ΚΥΗΣ ΗΘΙΚ")),
    ("Εθνικά θέματα, άμυνα, εξωτερική πολιτική", (
        "ΤΟΥΡΚ ΑΙΓΑΙ ΚΥΠΡ ΚΑΤΕΧΟΜΕΝ ΣΚΟΠΙΑ ΣΚΟΠΙΑΝ ΣΚΟΠΙΩΝ ΜΑΚΕΔΟΝ ΠΡΕΣΠ ΑΛΒΑΝ ΒΟΡΕΙΟΗΠΕΙΡ ΒΟΡΕΙΟΥ_ΗΠΕΙΡΟΥ ΝΑΤΟ. "
        "ΣΤΡΑΤΟ ΣΤΡΑΤΙΩΤ ΣΤΡΑΤΕΥΣ ΕΝΟΠΛ ΑΜΥΝ ΕΞΟΠΛΙΣΤΙΚ ΦΡΕΓΑΤ ΚΥΡΙΑΡΧ ΑΟΖ. ΥΦΑΛΟΚΡΗΠΙΔ ΧΩΡΙΚ*_ΥΔΑΤ ΓΚΡΙΖ ΙΜΙΑ ΙΜΙΩΝ "
        "ΠΡΕΣΒΕΙ ΔΙΠΛΩΜΑΤ ΟΥΚΡΑΝ ΡΩΣΙ ΙΣΡΑΗΛ ΓΑΖΑ ΠΑΛΑΙΣΤΙΝ ΓΕΝΟΚΤΟΝ ΠΟΝΤΙ ΟΜΟΓΕΝ ΑΠΟΔΗΜ ΘΑΛΑΣΣΙ*_ΠΑΡΚ ΣΥΝΟΡ ΕΦΕΔΡ "
        "ΘΗΤΕΙ ΝΕΟΣΥΛΛΕΚΤ ΑΞΙΩΜΑΤΙΚ ΙΡΑΝ ΛΙΒΥ ΚΑΛΩΔΙ ΠΕΣΟΝΤ ΑΜΕΡΙΚ ΕΥΡΩΠΑΪΚ_ΕΝΩΣ ΚΩΝΣΤΑΝΤΙΝΟΥΠΟΛ ΣΜΥΡΝ ΜΙΚΡΑΣΙΑΤ "
        "ΚΕΜΑΛ ΒΟΥΛΓΑΡ ΣΑΜΟΥΗΛ ΝΕΙΓΥ ΜΑΔΡΙΤ ΕΛΙΑΜΕΠ ΥΠΕΞ. ΕΘΝΙΚ*_ΑΣΦΑΛ ΕΘΝΙΚ*_ΕΠΕΤΕ NAVTEX ΥΔΡΟΓΡΑΦΙΚ ΚΛΗΡΩΤ ΦΡΟΥΡ "
        "ΚΙΕΦ ΑΡΔΑ ΔΙΑΚΡΑΤΙΚ DRONE ΕΙΡΗΝΗ ΝΑΥΤΙΚ*_ΔΙΟΙΚΗΣ ΛΕΙΨΑΝ ΠΟΛΕΜΙΚ*_ΝΑΥΤΙΚ ΠΟΛΕΜΙΚ*_ΑΕΡΟΠΟΡ")),
    ("Μεταναστευτικό", (
        "ΜΕΤΑΝΑΣΤ ΠΡΟΣΦΥΓ ΑΣΥΛ ΑΙΤΟΥΝΤ ΑΛΛΟΔΑΠ ΛΑΘΡΟ ΔΟΜ*_ΦΙΛΟΞΕΝΙΑΣ ΚΛΕΙΣΤ*_ΕΛΕΓΧΟΜΕΝ ΡΟΕΣ. ΙΘΑΓΕΝ ΑΔΕΙΕΣ_ΔΙΑΜΟΝΗΣ "
        "ΑΔΕΙΩΝ_ΔΙΑΜΟΝΗΣ ΑΣΥΝΟΔΕΥΤ ΜΚΟ. ΔΙΕΘΝΟΥΣ_ΠΡΟΣΤΑΣΙΑΣ ΑΠΕΛΑΣ ΕΠΙΣΤΡΟΦΩΝ ΛΑΜΠΕΝΤΟΥΖ ΔΕΞΑΜΕΝ*_ΑΛΛΗΛΕΓΓΥ ΠΑΚΙΣΤΑΝ")),
    ("Οικογένεια, δημογραφικό, κοινωνική πρόνοια", (
        "ΟΙΚΟΓΕΝ ΠΟΛΥΤΕΚΝ ΤΡΙΤΕΚΝ ΔΗΜΟΓΡΑΦ ΓΕΝΝΗΤΙΚ ΥΠΟΓΕΝΝ ΜΗΤΕΡ ΜΗΤΡΟΤ ΠΑΤΡΟΤ ΓΟΝΙΚ ΓΟΝΕ ΠΑΙΔΙ ΠΑΙΔΙΚ ΑΝΗΛΙΚ ΒΡΕΦ "
        "ΥΙΟΘΕΣ ΑΝΑΔΟΧ ΕΠΙΔΟΜ ΑΜΕΑ. ΑΝΑΠΗΡ ΑΥΤΙΣ ΗΛΙΚΙΩΜΕΝ ΓΗΡΟΚΟΜ ΚΑΠΗ. ΦΤΩΧ ΑΣΤΕΓ ΕΝΔΟΟΙΚΟΓΕΝ ΣΤΕΓΑΣ ΠΡΟΝΟΙ ΟΠΕΚΑ "
        "ΚΙΒΩΤ ΠΑΙΔΟΠΟΛ ΠΡΟΣΩΠΙΚ*_ΒΟΗΘ ΤΕΚΝ ΚΟΙΝΩΝΙΚ*_ΟΙΚΙΑΚ ΚΟΙΝΩΝΙΚ*_ΤΙΜΟΛΟΓ")),
    ("Παιδεία", (
        "ΣΧΟΛ ΕΚΠΑΙΔΕΥ ΜΑΘΗΤ ΠΑΝΕΠΙΣΤΗΜ ΑΕΙ. ΤΕΙ. ΦΟΙΤΗΤ ΝΗΠΙΑΓΩΓ ΓΥΜΝΑΣΙ ΛΥΚΕΙ ΠΑΝΕΛΛΑΔΙΚ ΠΤΥΧΙ ΔΙΔΑΣΚ ΚΑΘΗΓΗΤ "
        "ΑΝΑΠΛΗΡΩΤ ΙΕΚ. ΕΠΑΛ. ΒΙΒΛΙ ΜΑΘΗΜΑ ΑΝΑΛΥΤΙΚ*_ΠΡΟΓΡΑΜΜ ΔΙΔΑΚΤ ΦΡΟΝΤΙΣΤ ΦΟΙΤΗΣ ΕΣΤΙΕΣ ΕΣΤΙΩΝ ΚΟΛΛΕΓ ΜΗ_ΚΡΑΤΙΚ "
        "ΕΚΦΟΒΙΣΜ ΕΙΔΙΚΗΣ_ΑΓΩΓΗΣ ΕΠΙΜΟΡΦΩΣ ΡΟΜΠΟΤΙΚ ΙΚΥ. ΥΠΟΤΡΟΦ")),
    ("Υγεία", (
        "ΝΟΣΟΚΟΜ ΥΓΕΙ ΙΑΤΡ ΓΙΑΤΡ ΝΟΣΗΛΕΥΤ ΕΚΑΒ ΕΟΠΥΥ ΦΑΡΜΑΚ ΑΣΘΕΝ ΚΑΡΚΙΝ ΟΓΚΟΛΟΓ ΚΛΙΝΙΚ ΧΕΙΡΟΥΡΓ ΨΥΧΙΑΤΡ ΨΥΧΙΚ*_ΥΓΕΙ "
        "ΚΑΡΔΙ ΔΙΑΒΗΤ ΑΙΜΟΚΑΘΑΡ ΠΑΘΟΛΟΓ ΑΘΕΝΟΦΟΡ ΕΟΔΥ. ΜΕΘ. ΛΟΙΜΩΞ ΕΠΙΔΗΜ ΠΑΝΔΗΜ ΚΟΡΩΝΟΙ COVID ΑΝΑΙΣΘΗΣΙΟΛΟΓ ΤΕΠ. "
        "ΟΔΟΝΤΙΑΤΡ ΕΜΒΟΛΙ ΜΑΙΕΥΤ ΓΥΝΑΙΚΟΛΟΓ ΝΕΦΡΟΠΑΘ ΑΝΟΙΑ ALZHEIMER ΔΥΤΙΚΟΥ_ΝΕΙΛΟΥ ΦΥΣΙΚΟΘΕΡΑΠ ΣΑΛΜΟΝΕΛ ΔΙΑΣΩΣΤ "
        "ΑΕΡΟΔΙΑΚΟΜΙΔ")),
    ("Δημόσια τάξη και δικαιοσύνη", (
        "ΑΣΤΥΝΟΜ ΕΛΑΣ. ΕΓΚΛΗΜ ΦΥΛΑΚ ΚΡΑΤΟΥΜΕΝ ΔΙΚΑΣΤ ΔΙΚΑΙΟΣΥΝ ΕΙΣΑΓΓΕΛ ΠΟΙΝΙΚ ΚΛΟΠ ΛΗΣΤ ΔΟΛΟΦΟΝ ΝΑΡΚΩΤ ΒΙΑ. ΒΙΑΣ "
        "ΑΝΟΜΙ ΡΟΜΑ. ΣΥΜΜΟΡΙ ΟΠΛΑ. ΟΠΛΩΝ. ΟΠΛΟΦΟΡ ΕΚΡΗΞ ΤΡΟΜΟΚΡΑΤ ΔΙΚΗΓΟΡ ΣΥΜΒΟΛΑΙΟΓΡΑΦ ΑΠΑΤ ΔΙΑΦΘΟΡ ΣΚΑΝΔΑΛ ΟΠΕΚΕΠΕ "
        "ΤΕΜΠ ΕΦΕΤΕΙ ΔΙΚΑΣΤΗΡΙ ΕΓΚΛΗΜΑΤΙΚΟΤΗΤ ΑΣΦΑΛΕΙΑ_ΤΩΝ_ΠΟΛΙΤΩΝ ΥΠΟΘΗΚΟΦΥΛΑΚ ΚΑΤΑΠΑΤΗΣ ΕΝΝΟΜ*_ΠΡΟΣΤΑΣ ΝΟΜΙΜΟΤΗΤ "
        "ΛΙΜΕΝΙΚ")),
    ("Αγροτικά, κτηνοτροφία, αλιεία", (
        "ΑΓΡΟΤ ΚΤΗΝΟΤΡΟΦ ΚΤΗΝΙΑΤΡ ΑΙΓΟΠΡΟΒ ΠΡΟΒΑΤ ΕΥΛΟΓΙ ΠΑΝΩΛ ΖΩΙΚ ΑΛΙΕ ΑΛΙΕΥΤ ΕΛΓΑ. ΚΑΛΛΙΕΡΓ ΣΟΔΕΙ ΕΛΑΙΟΛΑΔ "
        "ΕΛΑΙΟΠΑΡΑΓ ΕΛΙΕΣ. ΕΛΙΑΣ. ΒΑΜΒΑΚ ΣΙΤΑΡ ΑΜΠΕΛ ΚΡΑΣΙ ΓΑΛΑΚΤ ΜΕΛΙΣΣ ΛΙΠΑΣΜ ΑΡΔΕΥ ΓΕΩΡΓΙΚ ΦΥΤΟΠΡΟΣΤΑΤ ΚΑΠ. "
        "ΑΝΑΔΑΣΜ ΤΡΟΦΙΜ ΦΡΟΥΤ ΚΗΠΕΥΤ ΑΚΤΙΝΙΔ ΡΟΔΑΚΙΝ ΕΣΠΕΡΙΔΟΕΙΔ ΣΥΝΔΕΔΕΜΕΝ*_ΕΝΙΣΧΥΣ ΠΑΤΑΤ ΠΡΩΤΟΓΕΝ*_ΤΟΜΕ ΒΙΟΛΟΓΙΚ "
        "ΟΙΚΟΛΟΓΙΚ*_ΣΧΗΜ ΣΥΝΕΤΑΙΡ ΠΟΥΛΕΡΙΚ ΣΠΑΝΙΑΣ_ΦΥΛΗΣ")),
    ("Οικονομία, φόροι, ακρίβεια", (
        "ΦΟΡΟΛΟΓ ΦΟΡΟ ΦΟΡΟΥ ΦΟΡΩΝ ΕΝΦΙΑ ΦΠΑ. ΑΦΟΡΟΛΟΓ ΑΑΔΕ ΤΕΛΩΝ ΤΡΑΠΕΖ ΔΑΝΕΙ SERVICER ΟΦΕΙΛ ΧΡΕΟΣ ΧΡΕΟΥΣ ΧΡΕΩΝ. "
        "ΥΠΕΡΧΡΕ ΠΛΕΙΣΤΗΡΙΑΣ ΑΚΡΙΒΕΙ ΤΙΜΕΣ. ΤΙΜΩΝ. ΑΝΑΤΙΜΗΣ ΠΛΗΘΩΡΙΣΜ ΚΑΥΣΙΜ ΔΙΟΔΙ ΕΠΙΧΕΙΡΗΣΗ. ΕΠΙΧΕΙΡΗΣΕ ΕΠΙΧΕΙΡΗΜΑΤ "
        "ΕΠΙΧΟΡΗΓΗΣ ΕΣΠΑ. ΤΑΜΕΙ*_ΑΝΑΚΑΜΨ ΠΡΟΥΠΟΛΟΓΙΣΜ ΔΗΜΟΣΙΟΝΟΜ ΑΓΟΡ ΚΑΤΑΝΑΛΩΤ ΑΣΦΑΛΙΣΤΙΚ ΣΥΝΤΑΞ ΕΦΚΑ. ΜΙΣΘ "
        "ΕΡΓΑΖΟΜΕΝ ΕΡΓΑΣΙΑΚ ΑΠΑΣΧΟΛ ΑΝΕΡΓ ΔΥΠΑ. ΤΟΥΡΙΣΜ ΙΔΙΩΤΙΚΟΠΟΙΗΣ ΥΠΕΡΤΑΜΕΙ ΣΥΜΒΑΣ ΔΙΑΓΩΝΙΣΜ ΠΡΟΜΗΘΕΙ "
        "ΑΠΕΥΘΕΙΑΣ_ΑΝΑΘΕΣ ΕΝΟΙΚΙ ΧΡΗΜΑΤΙΣΤΗΡΙ ΔΩΡΕ ΕΙΣΟΔΗΜ ΚΟΝΔΥΛΙ ΧΡΗΜΑΤΟΔΟΤ ΣΥΝΘΗΚΕΣ_ΕΡΓΑΣΙΑΣ ΘΕΣΕ*_ΕΡΓΑΣΙΑΣ "
        "ΚΟΙΝΩΦΕΛ ΠΡΟΥΠΗΡΕΣΙ ΔΕΔΟΥΛΕΥΜΕΝ ΒΑΡΕ*_ΚΑΙ_ΑΝΘΥΓΙΕΙΝ ΑΠΟΛΥΣ ΑΠΟΛΥΘ ΕΜΠΟΡΙ ΚΑΡΤΕΛ ΜΕΤΑΠΟΙΗΣ ΠΑΡΑΟΙΚΟΝΟΜ "
        "ΙΣΟΖΥΓΙ ΕΠΕΝΔΥΣ ΝΟΜΙΣΜΑΤΙΚ ΠΛΗΡΩΜ ΡΕΥΣΤΟΤΗΤ ΔΑΠΑΝ ΣΠΑΤΑΛ ΠΡΟΣΩΠΙΚ*_ΔΙΑΦΟΡ ΜΝΗΜΟΝΙ ΥΠΕΡΚΟΣΤΟΛΟΓ ΛΙΑΝΙΚ "
        "ΝΑΥΠΗΓΕΙ")),
    ("Υποδομές, ενέργεια, περιβάλλον, πολιτική προστασία", (
        "ΟΔΙΚ ΟΔΟΣ. ΟΔΟΥ. ΟΔΩΝ. ΔΡΟΜ ΑΥΤΟΚΙΝΗΤΟΔΡΟΜ ΓΕΦΥΡ ΣΙΔΗΡΟΔΡΟΜ ΟΣΕ. HELLENIC_TRAIN ΜΕΤΡΟ ΛΕΩΦΟΡΕΙ ΚΤΕΛ "
        "ΣΥΓΚΟΙΝΩΝ ΜΕΤΑΦΟΡ ΜΕΤΑΚΙΝΗΣ ΛΙΜΑΝ ΑΕΡΟΔΡΟΜ ΑΕΡΟΛΙΜΕΝ ΕΝΑΕΡΙ ΑΚΤΟΠΛΟ ΠΛΟΙ ΝΗΣΙΩΤ ΕΝΕΡΓΕΙ ΡΕΥΜΑ ΔΕΗ. "
        "ΗΛΕΚΤΡΙΚ*_ΕΝΕΡΓ ΗΛΕΚΤΡΟΔΟΤ ΑΝΕΜΟΓΕΝΝΗΤ ΑΙΟΛΙΚ ΦΩΤΟΒΟΛΤ ΑΠΕ. ΥΔΡΟΓΟΝΑΝΘΡΑΚ ΦΥΣΙΚΟ*_ΑΕΡΙ ΠΥΡΚΑΓ ΠΥΡΚΑΙ ΑΝΤΙΠΥΡ "
        "ΠΥΡΟΠΡΟΣΤΑΣ ΠΛΗΜΜΥΡ ΣΕΙΣΜ ΚΑΤΟΛΙΣΘ ΥΔΡΕΥΣ ΝΕΡΟ. ΝΕΡΟΥ. ΛΕΙΨΥΔΡ ΑΠΟΧΕΤΕΥΣ ΑΠΟΡΡΙΜ ΧΥΤΑ. ΑΝΑΚΥΚΛ ΡΥΠΑΝΣ "
        "ΠΕΡΙΒΑΛΛΟΝΤ ΔΑΣΟ ΔΑΣΙΚ ΔΑΣΩΝ ΔΑΣΗ. ΑΙΓΙΑΛ ΠΑΡΑΛΙ ΧΩΡΟΤΑΞ ΠΟΛΕΟΔΟΜ ΑΥΘΑΙΡΕΤ ΚΤΗΜΑΤΟΛΟΓ ΠΥΡΟΣΒΕΣΤ "
        "ΠΟΛΙΤΙΚΗΣ_ΠΡΟΣΤΑΣΙΑΣ ΚΛΙΜΑΤΙΚ ΕΡΓΟ. ΕΡΓΟΥ. ΕΡΓΩΝ. ΚΑΤΑΣΚΕΥ ΔΙΑΒΡΩΣ ΑΔΕΣΠΟΤ ΖΩΩΝ_ΣΥΝΤΡΟΦΙΑΣ ΚΑΤΑΦΥΓΙ ΚΤΙΡΙ "
        "ΚΤΗΡΙ ΚΑΘΙΖΗΣ ΥΔΑΤ ΥΔΡΟΔΟΤ ΑΠΟΒΛΗΤ ΚΟΛΠ LNG ΔΙΥΛΙΣΤΗΡΙ ΑΔΜΗΕ ΛΙΓΝΙΤ ΚΤΗΜΑΤΟΓΡΑΦ ΦΡΑΓΜ ΚΕΝΤΡ*_ΔΕΔΟΜΕΝΩΝ ΛΑΤΟΜ "
        "ΝΑΥΤΙΛ ΟΦΥΠΕΚΑ ΠΡΟΣΤΑΤΕΥΟΜΕΝ ΕΥΔΑΠ ΕΥΑΘ ΠΑΤΙΝ")),
    ("Δημόσια διοίκηση, αυτοδιοίκηση, πολιτισμός", (
        "ΔΗΜΟΣΙΩΝ_ΥΠΑΛΛΗΛ ΥΠΑΛΛΗΛ ΑΣΕΠ. ΠΡΟΣΛΗΨ ΥΠΟΣΤΕΛΕΧΩΣ ΚΕΝΕΣ_ΘΕΣΕΙΣ ΟΡΓΑΝΙΚ*_ΘΕΣ ΚΕΠ. ΔΗΜΑΡΧ ΔΗΜΟΤΙΚ*_ΣΥΜΒΟΥΛ "
        "ΠΕΡΙΦΕΡΕΙΑΚ*_ΣΥΜΒΟΥΛ ΟΤΑ. ΑΥΤΟΔΙΟΙΚΗΣ ΓΡΑΦΕΙΟΚΡΑΤ ΠΟΛΙΤΙΣΜ ΑΡΧΑΙΟ ΜΝΗΜΕΙ ΜΟΥΣΕΙ ΕΡΤ. ΜΜΕ. ΑΘΛΗΤ ΓΗΠΕΔ ΓΛΩΣΣ "
        "ΙΣΤΟΡΙ ΕΚΛΟΓ ΔΗΜΟΣΚΟΠ ΤΥΠΟΥ. ΔΗΜΟΣΙΟΓΡΑΦ ΔΗΜΟΣΙΟΥ_ΤΟΜΕΑ ΘΕΑΤΡ ΦΕΣΤΙΒΑΛ ΑΠΟΚΟΜΜΑΤΙΚΟΠΟΙΗΣ ΘΕΣΕ*_ΕΥΘΥΝΗΣ "
        "ΓΕΝΙΚ*_ΓΡΑΜΜΑΤΕΙ ΚΟΛΥΜΒΗΤΗΡΙ ΠΟΔΗΛΑΤΟΔΡΟΜ ΡΑΔΙΟΦΩΝ ΠΡΟΓΡΑΜΜΑΤΟΣ ΔΗΜΟΣΙ*_ΠΕΡΙΟΥΣΙ EUROVISION")),
]


def _pattern(words):
    """One regex for a category: each token at a word start; "_" whitespace, "*" rest of a word, final "." word end."""
    out = []
    for w in words.split():
        whole = w.endswith(".")
        out.append(w.rstrip(".").replace("*", r"\w*").replace("_", r"\s+") + (r"\b" if whole else ""))
    return re.compile(r"\b(?:" + "|".join(out) + ")")


_CAT = [(name, _pattern(words)) for name, words in CATEGORIES]
OTHER = "Άλλο"


def ministry(name):
    n = norm(name)
    for canon, pat in MINISTRIES:
        if re.search(pat, n):
            return canon
    return name.strip()


# The category a ministry's acts usually belong to: breaks ties between categories, and names the topic of a
# title with no keyword when all its ministries point to one category.
MINISTRY_CATEGORY = {
    "Οικονομικών": "Οικονομία, φόροι, ακρίβεια", "Εργασίας": "Οικονομία, φόροι, ακρίβεια",
    "Ανάπτυξης": "Οικονομία, φόροι, ακρίβεια", "Τουρισμού": "Οικονομία, φόροι, ακρίβεια",
    "Κοινωνικής Ασφάλισης": "Οικονομία, φόροι, ακρίβεια",
    "Παιδείας και Θρησκευμάτων": "Παιδεία", "Υγείας": "Υγεία",
    "Εξωτερικών": "Εθνικά θέματα, άμυνα, εξωτερική πολιτική",
    "Εθνικής Άμυνας": "Εθνικά θέματα, άμυνα, εξωτερική πολιτική",
    "Προστασίας του Πολίτη": "Δημόσια τάξη και δικαιοσύνη", "Δικαιοσύνης": "Δημόσια τάξη και δικαιοσύνη",
    "Μετανάστευσης": "Μεταναστευτικό", "Αγροτικής Ανάπτυξης": "Αγροτικά, κτηνοτροφία, αλιεία",
    "Κοινωνικής Συνοχής και Οικογένειας": "Οικογένεια, δημογραφικό, κοινωνική πρόνοια",
    "Περιβάλλοντος και Ενέργειας": "Υποδομές, ενέργεια, περιβάλλον, πολιτική προστασία",
    "Υποδομών και Μεταφορών": "Υποδομές, ενέργεια, περιβάλλον, πολιτική προστασία",
    "Κλιματικής Κρίσης, Πολιτικής Προστασίας": "Υποδομές, ενέργεια, περιβάλλον, πολιτική προστασία",
    "Ναυτιλίας": "Υποδομές, ενέργεια, περιβάλλον, πολιτική προστασία",
    "Εσωτερικών": "Δημόσια διοίκηση, αυτοδιοίκηση, πολιτισμός",
    "Πολιτισμού": "Δημόσια διοίκηση, αυτοδιοίκηση, πολιτισμός",
}


FIRST = {CATEGORIES[0][0], CATEGORIES[1][0]}


def category(title, ministries=()):
    """Topic of an act: the category with most distinct keyword hits in its title. A tie goes to the first listed
    if that is church or values (FIRST), else to the category of the act's ministries if it is among the tied,
    else to the first listed; no hit at all takes the ministries'
    category when they all have the same one, else «Άλλο». `ministries` are merged names (ministry())."""
    t = norm(title).replace("_", " ")  # the Parliament writes "_" for a dash: «Ελλάδας_Τουρκίας»
    hits = {name: len(set(pat.findall(t))) for name, pat in _CAT}
    top = max(hits.values())
    by_min = {MINISTRY_CATEGORY[m] for m in ministries if m in MINISTRY_CATEGORY}
    if not top:
        return by_min.pop() if len(by_min) == 1 else OTHER
    tied = [name for name, n in hits.items() if n == top]
    if tied[0] in FIRST:  # their ministry (Παιδείας, Ψηφιακής, ...) says nothing about them: they keep priority
        return tied[0]
    return next((c for c in tied if c in by_min), tied[0])


# Names of more than one constituency, and names that are also ordinary words or name a national issue.
WIDE = {"Θεσσαλονίκη": (6, 7), "Αθήνα": (38, 60, 61, 62), "Πειραιάς": (40, 41),
        "Αττική": (38, 40, 41, 60, 61, 62, 63, 64), "Κρήτη": (53, 54, 55, 56), "Θεσσαλία": (22, 23, 24, 25),
        "Θράκη": (1, 2, 3), "Πελοπόννησος": (43, 44, 45, 46, 47), "Επτάνησα": (26, 27, 28, 29),
        "Δωδεκάνησα": (52,), "Κυκλάδες": (51,), "Σαμοθράκη": (1,)}
# Place names that are also ordinary words or name a national issue: never read as a place.
STOP = {stems(w) for w in "Νίκης Ειρήνης Ελπίδας Αγίου Αγίας Μέσης Κεντρικής Άνω Κάτω Νέας Νέου Παλαιάς Ελληνικού "
        "Ηπείρου Μακεδονίας Αιγαίου Ολύμπου Δημοκρατίας Ελευθερίας Σωτήρος Προφήτη Ταξιαρχών Κάμπου Πύργου "
        "Κάστρου Λίμνης Πηγής Βρύσης Ποταμού Ακρόπολης Σταδίου Κρίνου Άσπρου Ζωής Αγάπης Πίστεως Σοφίας Λόγου "
        "Χώρας Νήσων Αμύνης Αρετής Δόξας Ελάτης Πεύκων Δάφνης Ορφανών Μαργαρίτας".split()}


def gazetteer(db):
    """{name stems: constituency ids} from the June 2023 stations (municipality, municipal unit, constituency)."""
    c = sqlite3.connect(db)
    g = defaultdict(set)
    for ep, dhm, den in c.execute("SELECT DISTINCT ep_id, dhm_descr, den_descr FROM station "
                                  "WHERE election='2023/june' AND kind='Κ' AND ep_id != 57"):
        for name in (dhm, den):
            s = stems(name)
            if s and s not in STOP and sum(map(len, s)) >= 5:
                g[s].add(ep)
    for ep, name in c.execute("SELECT ep_id, name FROM ep WHERE election='2023/june' AND ep_id != 57"):
        s = stems(re.sub(r"^[^ ]*['΄] ", "", name))  # "Α' Θεσσαλονίκης" -> Θεσσαλονίκης
        g[s].add(ep)
    for k, eps in WIDE.items():
        g[stems(k)] = set(eps)
    names = dict(c.execute("SELECT ep_id, name FROM ep WHERE election='2023/june'"))
    return dict(g), names


def place_hits(title, gaz):
    """Constituency sets of the places a title names: the stems of a place name, in order, among the title's stems."""
    ts = stems(title)
    return [eps for key, eps in gaz.items() if any(ts[i:i + len(key)] == key for i in range(len(ts) - len(key) + 1))]


def places(title, gaz):
    return set().union(*place_hits(title, gaz))


def file_ids(block):
    return [int(x) for x in re.findall(r'/(\d+)\.pdf"', block)]


def answer_dates(acts):
    """Estimated day of the first answer of each answered act. The Parliament numbers every uploaded file in one
    sequence, so the act files (number, filing day) date the sequence: the first answer file gets the median day of
    the 7 act files with the nearest numbers, never before the act itself. Sets a["answer_est"]."""
    pts = sorted((i, a["date"]) for a in acts for i in a["question_ids"])
    ids = [i for i, _ in pts]
    for a in acts:
        a["answer_est"] = None
        if a["answer_ids"] and pts:
            k = bisect.bisect_left(ids, min(a["answer_ids"]))
            near = sorted(d for _, d in pts[max(0, k - 3):k + 4])
            a["answer_est"] = max(a["date"], near[len(near) // 2])


def field(page, label):
    m = re.search(r"<dt>" + label + r":</dt>\s*<dd>(.*?)</dd>", page, re.DOTALL)
    return m[1] if m else ""


def cells(block):
    return [html.unescape(re.sub(r"\s+", " ", x)).strip() for x in re.findall(r"<td>(.*?)</td>", block, re.DOTALL)]


def _day(block):
    m = re.search(r"(\d{2}/\d{2}/\d{4})", block)
    return datetime.strptime(m[1], "%d/%m/%Y").date() if m else None


def parse_act(page):
    return {
        "number": re.sub(r"<[^>]+>", "", field(page, "Αριθμός")).strip(),
        "kind": re.sub(r"<[^>]+>", "", field(page, "Τύπος")).strip(),
        "title": html.unescape(re.sub(r"\s+", " ", field(page, "Θέμα"))).strip(),
        "groups": cells(field(page, "Κοινοβουλευτική Ομάδα")),
        "date": datetime.strptime(re.sub(r"<[^>]+>", "", field(page, "Ημερομηνία")).strip(), "%d/%m/%Y").date(),
        "signers": cells(field(page, "Καταθέτοντες")),
        "ministries": cells(field(page, "Υπουργεία")),
        "answer_files": re.findall(r'href="([^"]+\.pdf)"', field(page, "Αρχεία Απαντήσεων")),
        "answer_ids": file_ids(field(page, "Αρχεία Απαντήσεων")),
        "question_ids": file_ids(field(page, "Αρχεία Μέσων Κοινοβουλευτικού Ελέγχου")),
        "last_change": _day(field(page, "Ημ. Τελευταίας Τροποποίησης")),
        "sitting": _day(field(page, "Σχετική συνεδρίαση")),  # the plenary sitting where a topical was debated
    }


def nikh_signers(signers):
    """Short names of the ΝΙΚΗ MPs among the signers, by full name ("Κουρουπάκη Ιωάννη Ασπασία")."""
    by_full = {full: short for _, short, full, _ in MPS}
    return [by_full[n] for n in (" ".join(s.split()) for s in signers) if n in by_full]


def load():
    index = json.loads((CACHE / "list_index.json").read_text(encoding="utf-8"))
    vw = {}
    for p in sorted((CACHE / "vw").glob("*.json")):
        for d in json.loads(p.read_text(encoding="utf-8"))["results"]:
            vw[d["_id"]] = d
    acts = []
    for pcm in index:
        p = CACHE / "act" / f"{pcm}.html"
        if not p.exists():
            continue
        a = parse_act(p.read_text(encoding="utf-8"))
        a["pcm_id"] = pcm
        a["vw"] = vw.get(pcm)
        acts.append(a)
    return acts, index, vw


MONTHS = "ΙΑΝΟΥΑΡΙΟΥ ΦΕΒΡΟΥΑΡΙΟΥ ΜΑΡΤΙΟΥ ΑΠΡΙΛΙΟΥ ΜΑΙΟΥ ΙΟΥΝΙΟΥ ΙΟΥΛΙΟΥ ΑΥΓΟΥΣΤΟΥ ΣΕΠΤΕΜΒΡΙΟΥ ΟΚΤΩΒΡΙΟΥ ΝΟΕΜΒΡΙΟΥ " \
         "ΔΕΚΕΜΒΡΙΟΥ".split()
# Signature titles, in capitals and the nominative («Ο ΥΠΟΥΡΓΟΣ ΘΕΟΔΩΡΟΣ ΛΙΒΑΝΙΟΣ»): the distribution list below
# a letter names offices in the genitive («Γραφείο Υπουργού») and is not matched.
ROLES = [("Αναπληρωτής Υπουργός", r"ΑΝΑΠΛΗΡΩΤ(?:ΗΣ|ΡΙΑ) ΥΠΟΥΡΓΟΣ|(?<=[ΟΗ] )Αναπληρωτ(?:ης|ρια) Υπουργος"),
         ("Υφυπουργός", r"ΥΦΥΠΟΥΡΓΟΣ|(?<=[ΟΗ] )Υφυπουργος"),
         ("Υπουργός", r"(?<!ΥΦ)(?<!ΑΝΑΠΛΗΡΩΤΗΣ )ΥΠΟΥΡΓΟΣ|(?<=[ΟΗ] )Υπουργος"),
         ("Γενικός Γραμματέας", r"ΓΕΝΙΚ(?:ΟΣ|Η) ΓΡΑΜΜΑΤΕΑΣ|(?<=[ΟΗ] )Γενικ(?:ος|η) Γραμματεας")]


def letter(text, filed, today):
    """Date and signer of an answer letter: the latest date in the text between the filing day and today
    («29-10-2025», «12 Μαρτίου 2025»), and the title of the last signature (ROLES; the minister signs the
    letter itself, a secretary general only when the answer is a service's letter)."""
    t = norm(text)  # punctuation becomes spaces: «29-10-2025» -> «29 10 2025»
    days = [(int(y), int(m), int(d)) for d, m, y in re.findall(r"\b(\d{1,2}) (\d{1,2}) (20\d\d)\b", t)]
    days += [(int(y), MONTHS.index(m) + 1, int(d))
             for d, m, y in re.findall(r"\b(\d{1,2}) (" + "|".join(MONTHS) + r") (20\d\d)\b", t)]
    ok = []
    for y, m, d in days:
        try:
            x = date(y, m, d)
        except ValueError:
            continue
        if filed <= x <= today:
            ok.append(x)
    caps = " ".join("".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)).split())
    found = [(m.start(), role) for role, pat in ROLES for m in re.finditer(pat, caps)]
    return (max(ok) if ok else None), (max(found)[1] if found else None)


def sample_report(p, by_id):
    """Section 6b: the answer letters read by nikh_control_fetch.py answers (if it was run)."""
    path = CACHE / "answer_sample.json"
    if not path.exists():
        return
    rows = json.loads(path.read_text(encoding="utf-8"))
    today = max(a["date"] for a in by_id.values())
    diffs, made, roles = [], [], Counter()
    for r in rows:
        a = by_id[r["pcm_id"]]
        day, role = letter(r["head"] + "\n" + r["tail"], a["date"], today)
        roles[role or "δεν βρέθηκε"] += 1
        if day and a["answer_est"]:
            diffs.append((a["answer_est"] - day).days)
        m = re.match(r"D:(\d{8})", r["created"])
        if m and a["answer_est"]:
            made.append((a["answer_est"] - datetime.strptime(m[1], "%Y%m%d").date()).days)
    diffs.sort()
    made.sort()
    p(f"   Δείγμα {len(rows)} επιστολών απάντησης (τυχαίες, το πρώτο αρχείο απάντησης· "
      f"σκαναρισμένες, που χρειάστηκαν OCR: {sum(r['ocr'] for r in rows)}):")
    if diffs:
        p(f"     Εκτίμηση μείον ημερομηνία της επιστολής (n = {len(diffs)}): διάμεσος {statistics.median(diffs):.0f} "
          f"ημέρες, 10%–90% {diffs[len(diffs) // 10]}–{diffs[9 * len(diffs) // 10]}· "
          f"0–7 ημέρες {100 * sum(0 <= x <= 7 for x in diffs) / len(diffs):.0f}%.")
    if made:
        p(f"     Εκτίμηση μείον ημέρα δημιουργίας του PDF (n = {len(made)}): διάμεσος {statistics.median(made):.0f} "
          f"ημέρες, 10%–90% {made[len(made) // 10]}–{made[9 * len(made) // 10]}· "
          f"0–7 ημέρες {100 * sum(0 <= x <= 7 for x in made) / len(made):.0f}%.")
    p("     Υπογράφει: " + ", ".join(f"{k} {n}" for k, n in roles.most_common()))


def bar(n, scale):
    return "█" * round(n / scale) if scale else ""


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else str(HERE.parent / "data" / "stavroi.sqlite")
    gaz, ep_name = gazetteer(db)
    acts, index, _vw = load()
    own_ep = {short: ep for _, short, _, ep in MPS}
    today = max(a["date"] for a in acts)
    out = []
    p = out.append

    for a in acts:
        a["nikh"] = nikh_signers(a["signers"])
        a["in_group"] = [s for s in a["nikh"] if not (s in EXPELLED and a["date"] >= EXPELLED[s])]
        a["ministries_n"] = sorted({ministry(m) for m in a["ministries"]})
        a["category"] = category(a["title"], a["ministries_n"])
        a["by_title"] = category(a["title"]) != OTHER
        hits = place_hits(a["title"], gaz)
        a["eps"] = set().union(*hits)
        a["exact"] = {e for h in hits if len(h) == 1 for e in h}  # a place in one constituency only
        a["wide"] = any(len(h) > 1 for h in hits)
        a["own"] = bool(a["exact"] & {own_ep[s] for s in a["nikh"] if own_ep[s]})
        a["answered"] = bool(a["answer_files"])
        v = a["vw"] or {}
        a["answer_date"] = date.fromisoformat(v["answer_date"]) if v.get("answer_date") else None
    answer_dates(acts)
    for a in acts:
        a["days"] = (a["answer_est"] - a["date"]).days if a["answer_est"] else None
    acts.sort(key=lambda a: (a["date"], a["number"]))
    group_acts = [a for a in acts if a["in_group"]]

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pcm_id", "αριθμός", "ημερομηνία", "είδος", "θέμα", "βουλευτές_ΝΙΚΗΣ", "στην_ΚΟ_ΝΙΚΗΣ",
                    "όλοι_οι_καταθέτοντες", "ομάδες", "υπουργεία", "υπουργεία_ενιαία", "κατηγορία", "περιφέρειες",
                    "δική_του_περιφέρεια", "απαντήθηκε", "ημ_απάντησης_vouliwatch", "ημ_απάντησης_εκτίμηση", "ημέρες", "vouliwatch_απάντηση",
                    "vouliwatch_βαθμός", "σύνδεσμος"])
        for a in acts:
            v = a["vw"] or {}
            cc = (v.get("content_coverage") or {}).get("category") or ""
            w.writerow([a["pcm_id"], a["number"], a["date"].isoformat(), KIND_SHORT.get(a["kind"], a["kind"]),
                        a["title"], "; ".join(a["nikh"]), "; ".join(a["in_group"]), "; ".join(a["signers"]),
                        "; ".join(a["groups"]), "; ".join(a["ministries"]), "; ".join(a["ministries_n"]),
                        a["category"], "; ".join(ep_name[e] for e in sorted(a["eps"])), int(a["own"]),
                        int(a["answered"]), a["answer_date"] or "", a["answer_est"] or "", "" if a["days"] is None else a["days"],
                        v.get("answer_status", ""), cc,
                        (f"https://www.hellenicparliament.gr/Koinovouleftikos-Elenchos/Mesa-Koinovouleutikou-Elegxou"
                        f"?pcm_id={a['pcm_id']}")])

    p("Κοινοβουλευτικός έλεγχος των βουλευτών που εξελέγησαν με τη ΝΙΚΗ (Ιούνιος 2023)")
    p(f"Πηγές: hellenicparliament.gr (Μέσα Κοινοβουλευτικού Ελέγχου), vouliwatch.gr API. Τελευταία πράξη: {today:%d/%m/%Y}.")
    p("")
    # 0. Coverage
    sp = CACHE / "summary.json"
    summary = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    p("0. Κάλυψη (πράξεις ανά βουλευτή: που διαβάστηκαν / που μετρά η Βουλή / στο Vouliwatch)")
    for short, s in summary.items():
        p(f"   {short:<15} {s['parliament']:>4} / {s['parliament_total']:>4} / {s.get('vouliwatch', '-'):>4}")
    p(f"   Μοναδικές πράξεις: {len(index)}· με σελίδα πράξης: {len(acts)}· ταίριαξαν στο Vouliwatch: "
      f"{sum(1 for a in acts if a['vw'])} (το Vouliwatch έχει μόνο ερωτήσεις, επίκαιρες και αναφορές).")
    p("")
    # 1. Kind
    p("1. Ανά είδος (μοναδικές πράξεις· σε παρένθεση όσες κατατέθηκαν ενώ τουλάχιστον ένας υπογράφων ήταν στην ΚΟ)")
    kc, kg = Counter(a["kind"] for a in acts), Counter(a["kind"] for a in group_acts)
    for k, n in kc.most_common():
        p(f"   {KIND_SHORT.get(k, k):<22} {n:>5} ({kg[k]})")
    p(f"   {'Σύνολο':<22} {len(acts):>5} ({len(group_acts)})")
    p("")
    # 2. MP
    p("2. Ανά βουλευτή (κάθε πράξη μετρά σε κάθε υπογράφοντα)")
    p(f"   {'':<15} {'σύνολο':>6} {'μόνος':>6} {'με ΝΙΚΗ':>8} {'με άλλους':>9} {'μετά τη διαγραφή':>17}  "
      + "".join(f"{KIND_SHORT[k]:>19}" for k in kc if k in KIND_SHORT))
    for _, short, _, _ in MPS:
        mine = [a for a in acts if short in a["nikh"]]
        if not mine:
            continue
        alone = sum(1 for a in mine if len(a["signers"]) == 1)
        with_n = sum(1 for a in mine if len(a["nikh"]) > 1)
        with_o = sum(1 for a in mine if len(a["signers"]) > len(a["nikh"]))
        after = sum(1 for a in mine if short not in a["in_group"])
        kk = Counter(a["kind"] for a in mine)
        p(f"   {short:<15} {len(mine):>6} {alone:>6} {with_n:>8} {with_o:>9} {after:>17}  "
          + "".join(f"{kk[k]:>19}" for k in kc if k in KIND_SHORT))
    p("")
    # 3. Ministry
    p("3. Ανά υπουργείο (ενιαίο όνομα· μια πράξη προς πολλά υπουργεία μετρά σε καθένα)")
    mc = Counter(m for a in acts for m in a["ministries_n"])
    for m, n in mc.most_common():
        p(f"   {m:<42} {n:>5}  {100 * n / len(acts):5.1f}%")
    raw = Counter(m for a in acts for m in a["ministries"])
    p(f"   ({len(raw)} διαφορετικά ονόματα της Βουλής → {len(mc)} χαρτοφυλάκια· πράξεις χωρίς υπουργείο: "
      f"{sum(1 for a in acts if not a['ministries'])})")
    p("")
    # 4. Category
    p("4. Ανά θεματική κατηγορία (από τον τίτλο)")
    cc = Counter(a["category"] for a in acts)
    for c, n in cc.most_common():
        p(f"   {c:<52} {n:>5}  {100 * n / len(acts):5.1f}%")
    p(f"   Στο «{OTHER}»: {100 * cc[OTHER] / len(acts):.1f}%· χωρίς λέξη-κλειδί στον τίτλο ήταν το "
      f"{100 * sum(not a['by_title'] for a in acts) / len(acts):.1f}% και πήραν την κατηγορία του υπουργείου όσες μπορούσαν")
    p("")
    p("   Κατηγορία ανά βουλευτή (% των πράξεών του)")
    cats = [c for c, _ in cc.most_common()]
    p("   " + " " * 15 + "".join(f"{c[:9]:>10}" for c in cats))
    for _, short, _, _ in MPS:
        mine = [a for a in acts if short in a["nikh"]]
        if mine:
            k = Counter(a["category"] for a in mine)
            p(f"   {short:<15}" + "".join(f"{100 * k[c] / len(mine):>10.0f}" for c in cats))
    p("")
    # 5. Month
    p("5. Ανά μήνα (μοναδικές πράξεις, σε παρένθεση όσες κατατέθηκαν από μέλη της ΚΟ· █ = 5)")
    by_month = Counter(a["date"].strftime("%Y-%m") for a in acts)
    by_month_g = Counter(a["date"].strftime("%Y-%m") for a in group_acts)
    months = []
    y, m = acts[0]["date"].year, acts[0]["date"].month
    while (y, m) <= (today.year, today.month):
        months.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for mo in months:
        p(f"   {mo} {by_month[mo]:>4} ({by_month_g[mo]:>3}) {bar(by_month[mo], 5)}")
    xs = list(range(len(months) - 1))  # the running month is partial: left out of the trend
    for label, bm in (("όλες", by_month), ("μέλη της ΚΟ", by_month_g)):
        ys = [bm[mo] for mo in months[:-1]]
        half = len(ys) // 2
        p(f"   Τάση, {label} (ελάχιστα τετράγωνα, χωρίς τον τρέχοντα μήνα): "
          f"{statistics.linear_regression(xs, ys).slope:+.2f} πράξεις ανά μήνα κάθε μήνα· "
          f"μέσος όρος πρώτου μισού {statistics.mean(ys[:half]):.1f}, δεύτερου {statistics.mean(ys[half:]):.1f}.")
    by_year = Counter(a["date"].year for a in acts)
    by_year_g = Counter(a["date"].year for a in group_acts)
    p("   Ανά έτος: " + ", ".join(f"{yr}: {n} ({by_year_g[yr]})" for yr, n in sorted(by_year.items())))
    p("")
    # 6. Answers
    old = [a for a in acts if a["kind"] in WRITTEN and (today - a["date"]).days >= MIN_AGE]
    p(f"6. Απαντήσεις: γραπτές πράξεις (όχι επίκαιρες, όχι επερωτήσεις) παλαιότερες από {MIN_AGE} ημέρες, n = {len(old)}")
    p(f"   Με αρχείο απάντησης στη Βουλή: {sum(a['answered'] for a in old)} ({100 * sum(a['answered'] for a in old) / len(old):.0f}%)")
    p("   Ανά είδος: " + ", ".join(
        f"{KIND_SHORT[k]} {100 * sum(a['answered'] for a in old if a['kind'] == k) / max(1, sum(1 for a in old if a['kind'] == k)):.0f}% "
        f"(n={sum(1 for a in old if a['kind'] == k)})" for k in WRITTEN if any(a["kind"] == k for a in old)))
    chk = sorted((a["answer_est"] - a["answer_date"]).days for a in acts if a["answer_date"] and a["answer_est"])
    p(f"   Ημέρα απάντησης: εκτίμηση από τον αύξοντα αριθμό των αρχείων της Βουλής (βλ. answer_dates). Έλεγχος με τις "
      f"{len(chk)} ημερομηνίες που δίνει το Vouliwatch: διαφορά σε ημέρες " + ", ".join(map(str, chk)) + ".")
    # An act with one answer file was last changed when that file was attached (an unanswered act: about the day
    # after filing), so «Ημ. Τελευταίας Τροποποίησης» is a second check on all of them.
    lc = sorted((a["answer_est"] - a["last_change"]).days for a in acts
                if len(set(a["answer_ids"])) == 1 and a["last_change"] and a["answer_est"])
    if lc:
        p(f"   Έλεγχος με την «Ημ. Τελευταίας Τροποποίησης» των {len(lc)} πράξεων με ένα αρχείο απάντησης: διάμεσος "
          f"διαφορά {statistics.median(lc):.0f} ημέρες· ±1 ημέρα {100 * sum(abs(x) <= 1 for x in lc) / len(lc):.0f}%, "
          f"±3 {100 * sum(abs(x) <= 3 for x in lc) / len(lc):.0f}%, ±7 {100 * sum(abs(x) <= 7 for x in lc) / len(lc):.0f}%.")
    p("   Ανά υπουργείο (πράξη προς πολλά υπουργεία: απαντήθηκε αν υπάρχει τουλάχιστον ένα αρχείο· "
      "ημέρες έως την πρώτη απάντηση, μόνο για όσες απαντήθηκαν):")
    p(f"   {'':<42} {'n':>5} {'απάντ.':>7} {'διάμεσος ημ.':>13} {'≤25 ημ.':>8} {'n ημ.':>6}")
    rows = []
    for m in mc:
        sub = [a for a in old if m in a["ministries_n"]]
        if len(sub) < 10:
            continue
        d = [a["days"] for a in sub if a["days"] is not None and a["days"] >= 0]
        rows.append((m, len(sub), 100 * sum(a["answered"] for a in sub) / len(sub),
                     statistics.median(d) if d else None, 100 * sum(x <= 25 for x in d) / len(d) if d else None, len(d)))
    for m, n, rate, med, within, nd in sorted(rows, key=lambda r: -r[2]):
        p(f"   {m:<42} {n:>5} {rate:>6.0f}% {f'{med:.0f}' if med is not None else '-':>13} "
          f"{f'{within:.0f}%' if within is not None else '-':>8} {nd:>6}")
    d = [a["days"] for a in old if a["days"] is not None and a["days"] >= 0]
    if d:
        p(f"   Όλα: διάμεσος {statistics.median(d):.0f} ημέρες, ≤25 ημέρες {100 * sum(x <= 25 for x in d) / len(d):.0f}% (n = {len(d)})")
    graded = Counter((a["vw"].get("content_coverage") or {}).get("category") for a in old
                     if a["vw"] and (a["vw"].get("content_coverage") or {}).get("category"))
    if graded:
        p("   Βαθμός πληρότητας της απάντησης κατά Vouliwatch (αυτόματος, με AI): "
          + ", ".join(f"{k} {n}" for k, n in graded.most_common()))
    top_q = [a for a in acts if a["kind"] == "Επίκαιρες Ερωτήσεις"]
    deb = [a for a in top_q if a["sitting"]]
    if deb:
        p(f"   Επίκαιρες ερωτήσεις με «σχετική συνεδρίαση» (ορίστηκαν για συζήτηση στην Ολομέλεια): {len(deb)} από "
          f"{len(top_q)} ({100 * len(deb) / len(top_q):.0f}%)· διάμεσος "
          f"{statistics.median((a['sitting'] - a['date']).days for a in deb):.0f} ημέρες από την κατάθεση. Ανά υπουργείο:")
        p("   " + ", ".join(f"{m} {sum(1 for a in deb if m in a['ministries_n'])}/{n}" for m, n in Counter(
            m for a in top_q for m in a["ministries_n"]).most_common() if n >= 10))
    sample_report(p, {a["pcm_id"]: a for a in acts})
    p("")
    # 7. Co-signing
    p("7. Συνυπογραφές")
    pairs = Counter(pr for a in acts for pr in combinations(sorted(set(a["nikh"])), 2))
    for (x, y_), n in pairs.most_common(15):
        p(f"   {x} + {y_}: {n}")
    sizes = Counter(len(set(a["nikh"])) for a in acts)
    p("   Βουλευτές ΝΙΚΗΣ ανά πράξη: " + ", ".join(f"{k}: {n}" for k, n in sorted(sizes.items())))
    allnikh = sum(1 for a in acts if len(set(a["in_group"])) >= 6)
    p(f"   Πράξεις με 6+ βουλευτές της ΚΟ (κοινές της ομάδας): {allnikh}")
    p(f"   Πράξεις με υπογράφοντα εκτός ΝΙΚΗΣ: {sum(1 for a in acts if len(a['signers']) > len(a['nikh']))}")
    p("   Έλεγχος των ημερομηνιών διαγραφής με την ομάδα που γράφει η Βουλή στις πράξεις που υπέγραψε μόνος:")
    for short, day in EXPELLED.items():
        solo = [(a["date"], a["groups"][0]) for a in acts if a["nikh"] == [short] and len(a["signers"]) == 1
                and a["groups"]]
        last_n = max((d for d, g in solo if "ΝΙΚΗ" in g), default=None)
        first_i = min((d for d, g in solo if "ΑΝΕΞΑΡΤΗΤ" in g.upper()), default=None)
        p(f"   {short:<15} διαγραφή {day:%d/%m/%Y}· τελευταία πράξη ως ΝΙΚΗ "
          f"{last_n:%d/%m/%Y}, πρώτη ως ανεξάρτητος {first_i:%d/%m/%Y}" if last_n and first_i else
          f"   {short:<15} διαγραφή {day:%d/%m/%Y}· ομάδες: {Counter(g for _, g in solo)}")
    p("")
    # 8. Place
    p("8. Τόπος: πράξεις που ονομάζουν τόπο στον τίτλο. «Δική του» μόνο όταν ο τόπος ανήκει σε μία περιφέρεια,")
    p("   τη δική του· ευρύτερα ονόματα (Θεσσαλονίκη, Αθήνα, Αττική, Κρήτη, ...) μετρούν χωριστά.")
    loc = [a for a in acts if a["eps"]]
    p(f"   Με τόπο: {len(loc)} ({100 * len(loc) / len(acts):.0f}%)· με τόπο μιας περιφέρειας: "
      f"{sum(1 for a in acts if a['exact'])}· με ευρύτερο όνομα: {sum(1 for a in acts if a['wide'])}")
    for _, short, _, ep in MPS:
        mine = [a for a in acts if short in a["nikh"]]
        if not mine:
            continue
        ml = sum(1 for a in mine if a["eps"])
        own = sum(1 for a in mine if ep in a["exact"])
        wide = sum(1 for a in mine if a["wide"] and ep in a["eps"] and ep not in a["exact"])
        p(f"   {short:<15} {ep_name.get(ep, 'Επικρατείας'):<26} με τόπο {ml:>4} ({100 * ml / len(mine):3.0f}%)"
          + (f", στη δική του {own:>4} ({100 * own / len(mine):3.0f}% όλων), ευρύτερο όνομα που την περιέχει "
             f"{wide:>3}" if ep else ""))
    top = Counter(e for a in acts for e in a["exact"])
    p("   Περιφέρειες με τις περισσότερες αναφορές (τόποι μιας περιφέρειας): "
      + ", ".join(f"{ep_name[e]} {n}" for e, n in top.most_common(12)))
    p("")
    # 9. Baseline
    p("9. Σύγκριση με τις άλλες ομάδες: πράξεις ανά βουλευτή (ερωτήσεις, επίκαιρες, επερωτήσεις, αναφορές, ΑΚΕ),")
    p("   από τον πίνακα «Πιο δραστήριοι βουλευτές» του Vouliwatch, ομάδα όπως την ημέρα της λήψης· «Βουλή» = ίδια")
    p(f"   μέτρηση από τον κατάλογο της Βουλής (πράξεις από {date.fromisoformat(START):%d/%m/%Y} ως σήμερα)· ομιλίες από το Vouliwatch.")
    with open(BASELINE, encoding="utf-8-sig") as f:
        base = list(csv.DictReader(f, delimiter=";"))
    bc_path = CACHE / "baseline_counts.json"
    recount = json.loads(bc_path.read_text(encoding="utf-8")) if bc_path.exists() else {}
    grp = defaultdict(list)
    for r in base:
        g = re.search(r"\(([^()]*)\)\s*$", r["ΟΝΟΜΑ"].strip())[1]
        found = recount.get(r["ΟΝΟΜΑ"])
        grp[g].append((int(r["ΣΥΝΟΛΟ"]), int(r["ΟΜΙΛΙΕΣ"]), found[0][1] if found and len(found) == 1 else None))
    p(f"   {'':<28} {'βουλευτές':>9} {'μέσος':>7} {'διάμεσος':>9} {'Βουλή μέσος':>12} {'Βουλή διάμ.':>12} "
      f"{'ομιλίες μέσος':>14}")
    for g, v in sorted(grp.items(), key=lambda kv: -statistics.mean(x[0] for x in kv[1])):
        vw_n, sp, pa = [x[0] for x in v], [x[1] for x in v], [x[2] for x in v if x[2] is not None]
        p(f"   {g:<28} {len(v):>9} {statistics.mean(vw_n):>7.0f} {statistics.median(vw_n):>9.0f} "
          f"{statistics.mean(pa) if pa else float('nan'):>12.0f} {statistics.median(pa) if pa else float('nan'):>12.0f} "
          f"{statistics.mean(sp):>14.0f}")
    pairs = [(x[0], x[2]) for v in grp.values() for x in v if x[2] is not None]
    if pairs:
        missing = sum(1 for v in grp.values() for x in v if x[2] is None)
        ratio = sorted(b / a for a, b in pairs if a)
        p(f"   Έλεγχος με τη Βουλή: {len(pairs)} βουλευτές βρέθηκαν μία φορά στον κατάλογό της ({missing} όχι: "
          f"συνωνυμία, άλλη γραφή ή καμία πράξη)· Βουλή / Vouliwatch ανά βουλευτή: διάμεσος {statistics.median(ratio):.2f}, "
          f"10%–90% {ratio[len(ratio) // 10]:.2f}–{ratio[9 * len(ratio) // 10]:.2f}· "
          f"συσχέτιση Spearman {statistics.correlation(*zip(*pairs), method='ranked'):.3f}.")
    p("   (Μετρά ανά υπογράφοντα· οι πράξεις των Βρεττού και Παπαδόπουλου μετρούν στους Ανεξάρτητους.)")
    OUT_TXT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
