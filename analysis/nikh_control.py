"""Parliamentary oversight of the MPs elected with ΝΙΚΗ (party 131): classify every act and count.

Input: the cache of nikh_control_fetch.py (data/parl_control/: Parliament listing and act pages, Vouliwatch JSON),
the results db (place names: municipalities and municipal units per constituency, June 2023) and
nikh_control_baseline.csv (acts per MP of every group, from Vouliwatch's «Πιο δραστήριοι βουλευτές»,
groups as on the day it was saved).
Output: nikh_control.csv (one row per act), nikh_control.txt (the tables).

Classification (all rules in this file, from the titles only):
  - ministry: the Parliament's ministry names, merged across reshuffles into one name per portfolio (MINISTRIES);
  - topic: a fixed list of categories (CATEGORIES), each a set of word beginnings; the category with the most
    hits wins, ties go to the one listed first, no hit is «Άλλο»;
  - place: a municipality, municipal unit or constituency named in the title (stems, as matching.py) → its
    constituencies; «own» only when the place lies in one constituency, that of a ΝΙΚΗ MP who signed (names of
    wider areas, WIDE, are counted apart).
Group at filing: Παπαδόπουλος and Βρεττός were expelled (EXPELLED dates); an act they filed on or after that
day is not counted as ΝΙΚΗ group work. Answers: the Parliament page lists answer files (answered yes/no) but no
date; the day of the first answer is estimated from the file numbers (answer_dates) and checked against the few
dates Vouliwatch gives. Vouliwatch's grade of each answer is its own, made with AI.

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
from collections import Counter, defaultdict
from datetime import date, datetime
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # python -I drops the script dir
sys.path.insert(0, str(HERE))
from nikh_control_fetch import CACHE, MPS

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
        "ΑΜΒΛΩΣ ΕΚΤΡΩΣ ΠΑΡΕΝΘΕΤ ΟΜΟΦΥΛ ΛΟΑΤΚΙ ΦΥΛΟΥ ΦΥΛΟ. ΤΡΑΝΣ ΑΙΜΟΜΙΞ ΥΠΟΒΟΗΘΟΥΜΕΝ ΣΕΞΟΥΑΛΙΚ ΔΙΑΠΑΙΔΑΓΩΓ ΕΜΒΟΛ "
        "ΤΑΥΤΟΤΗΤ ΨΗΦΙΑΚ ΠΡΟΣΩΠΙΚ_ΔΕΔΟΜΕΝ ΚΑΜΕΡ ΕΠΙΤΗΡΗΣ ΠΑΡΑΚΟΛΟΥΘΗΣ ΤΕΧΝΗΤΗΣ?_ΝΟΗΜΟΣΥΝ ΠΟΡΝΟΓΡΑΦ ΕΘΙΣΜ "
        "ΚΙΝΗΤ*_ΤΗΛΕΦΩΝ ΚΟΙΝΩΝΙΚ*_ΔΙΚΤΥ ΕΥΘΑΝΑΣ ΛΟΓΟΚΡΙΣ ΕΛΕΥΘΕΡΙΑΣ?_ΤΟΥ_ΛΟΓΟΥ ΤΖΟΓ ΚΑΖΙΝΟ ΤΥΧΕΡΑ?_ΠΑΙΓΝ "
        "ΤΥΧΕΡΩΝ_ΠΑΙΓΝ ΜΑΣΚ ΠΡΟΣΩΠΙΚ*_ΑΡΙΘΜ ΜΕΤΡΗΤ ΔΕΔΟΜΕΝΩΝ. EUROPRIDE PRIDE ΚΥΗΣ ΗΘΙΚ")),
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
        "ΕΚΦΟΒΙΣΜ ΕΙΔΙΚΗΣ_ΑΓΩΓΗΣ ΕΠΙΜΟΡΦΩΣ ΡΟΜΠΟΤΙΚ")),
    ("Υγεία", (
        "ΝΟΣΟΚΟΜ ΥΓΕΙ ΙΑΤΡ ΓΙΑΤΡ ΝΟΣΗΛΕΥΤ ΕΚΑΒ ΕΟΠΥΥ ΦΑΡΜΑΚ ΑΣΘΕΝ ΚΑΡΚΙΝ ΟΓΚΟΛΟΓ ΚΛΙΝΙΚ ΧΕΙΡΟΥΡΓ ΨΥΧΙΑΤΡ ΨΥΧΙΚ*_ΥΓΕΙ "
        "ΚΑΡΔΙ ΔΙΑΒΗΤ ΑΙΜΟΚΑΘΑΡ ΠΑΘΟΛΟΓ ΑΘΕΝΟΦΟΡ ΕΟΔΥ. ΜΕΘ. ΛΟΙΜΩΞ ΕΠΙΔΗΜ ΠΑΝΔΗΜ ΚΟΡΩΝΟΙ COVID ΑΝΑΙΣΘΗΣΙΟΛΟΓ ΤΕΠ. "
        "ΟΔΟΝΤΙΑΤΡ ΕΜΒΟΛΙΑΣΜ ΜΑΙΕΥΤ ΓΥΝΑΙΚΟΛΟΓ ΝΕΦΡΟΠΑΘ ΑΝΟΙΑ ALZHEIMER ΔΥΤΙΚΟΥ_ΝΕΙΛΟΥ ΦΥΣΙΚΟΘΕΡΑΠ ΣΑΛΜΟΝΕΛ ΔΙΑΣΩΣΤ "
        "ΑΕΡΟΔΙΑΚΟΜΙΔ")),
    ("Δημόσια τάξη και δικαιοσύνη", (
        "ΑΣΤΥΝΟΜ ΕΛΑΣ. ΕΓΚΛΗΜ ΦΥΛΑΚ ΚΡΑΤΟΥΜΕΝ ΔΙΚΑΣΤ ΔΙΚΑΙΟΣΥΝ ΕΙΣΑΓΓΕΛ ΠΟΙΝΙΚ ΚΛΟΠ ΛΗΣΤ ΔΟΛΟΦΟΝ ΝΑΡΚΩΤ ΒΙΑ. ΒΙΑΣ "
        "ΑΝΟΜΙ ΡΟΜΑ. ΣΥΜΜΟΡΙ ΟΠΛΑ. ΟΠΛΩΝ. ΟΠΛΟΦΟΡ ΕΚΡΗΞ ΤΡΟΜΟΚΡΑΤ ΔΙΚΗΓΟΡ ΣΥΜΒΟΛΑΙΟΓΡΑΦ ΑΠΑΤ ΔΙΑΦΘΟΡ ΣΚΑΝΔΑΛ ΟΠΕΚΕΠΕ "
        "ΤΕΜΠ ΕΦΕΤΕΙ ΔΙΚΑΣΤΗΡΙ ΕΓΚΛΗΜΑΤΙΚΟΤΗΤ ΑΣΦΑΛΕΙΑ_ΤΩΝ_ΠΟΛΙΤΩΝ ΥΠΟΘΗΚΟΦΥΛΑΚ ΚΑΤΑΠΑΤΗΣ ΕΝΝΟΜ*_ΠΡΟΣΤΑΣ ΝΟΜΙΜΟΤΗΤ")),
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
        "ΚΟΙΝΩΦΕΛ ΠΡΟΥΠΗΡΕΣΙ ΔΕΔΟΥΛΕΥΜΕΝ ΒΑΡΕ*_ΚΑΙ_ΑΝΘΥΓΙΕΙΝ ΑΠΟΛΥΣ ΑΠΟΛΥΘ ΕΜΠΟΡΙ ΚΑΡΤΕΛ ΜΕΤΑΠΟΙΗΣ ΠΑΡΑΟΙΚΟΝΟΜ ΙΣΟΖΥΓΙ "
        "ΕΠΕΝΔΥΣ ΝΟΜΙΣΜΑΤΙΚ ΠΛΗΡΩΜ ΡΕΥΣΤΟΤΗΤ ΔΑΠΑΝ ΣΠΑΤΑΛ ΠΡΟΣΩΠΙΚ*_ΔΙΑΦΟΡ ΜΝΗΜΟΝΙ ΥΠΕΡΚΟΣΤΟΛΟΓ ΛΙΑΝΙΚ ΝΑΥΠΗΓΕΙ")),
    ("Υποδομές, ενέργεια, περιβάλλον, πολιτική προστασία", (
        "ΟΔΙΚ ΟΔΟΣ. ΟΔΟΥ. ΟΔΩΝ. ΔΡΟΜ ΑΥΤΟΚΙΝΗΤΟΔΡΟΜ ΓΕΦΥΡ ΣΙΔΗΡΟΔΡΟΜ ΟΣΕ. HELLENIC_TRAIN ΜΕΤΡΟ ΛΕΩΦΟΡΕΙ ΚΤΕΛ "
        "ΣΥΓΚΟΙΝΩΝ ΜΕΤΑΦΟΡ ΜΕΤΑΚΙΝΗΣ ΛΙΜΑΝ ΑΕΡΟΔΡΟΜ ΑΕΡΟΛΙΜΕΝ ΕΝΑΕΡΙ ΑΚΤΟΠΛΟ ΠΛΟΙ ΝΗΣΙΩΤ ΕΝΕΡΓΕΙ ΡΕΥΜΑ ΔΕΗ. "
        "ΗΛΕΚΤΡΙΚ*_ΕΝΕΡΓ ΗΛΕΚΤΡΟΔΟΤ ΑΝΕΜΟΓΕΝΝΗΤ ΑΙΟΛΙΚ ΦΩΤΟΒΟΛΤ ΑΠΕ. ΥΔΡΟΓΟΝΑΝΘΡΑΚ ΦΥΣΙΚΟ*_ΑΕΡΙ ΠΥΡΚΑΓ ΠΥΡΚΑΙ ΑΝΤΙΠΥΡ "
        "ΠΥΡΟΠΡΟΣΤΑΣ ΠΛΗΜΜΥΡ ΣΕΙΣΜ ΚΑΤΟΛΙΣΘ ΥΔΡΕΥΣ ΝΕΡΟ. ΝΕΡΟΥ. ΛΕΙΨΥΔΡ ΑΠΟΧΕΤΕΥΣ ΑΠΟΡΡΙΜ ΧΥΤΑ. ΑΝΑΚΥΚΛ ΡΥΠΑΝΣ "
        "ΠΕΡΙΒΑΛΛΟΝΤ ΔΑΣΟ ΔΑΣΙΚ ΔΑΣΩΝ ΔΑΣΗ. ΑΙΓΙΑΛ ΠΑΡΑΛΙ ΧΩΡΟΤΑΞ ΠΟΛΕΟΔΟΜ ΑΥΘΑΙΡΕΤ ΚΤΗΜΑΤΟΛΟΓ ΠΥΡΟΣΒΕΣΤ "
        "ΠΟΛΙΤΙΚΗΣ_ΠΡΟΣΤΑΣΙΑΣ ΚΛΙΜΑΤΙΚ ΕΡΓΟ. ΕΡΓΟΥ. ΕΡΓΩΝ. ΚΑΤΑΣΚΕΥ ΔΙΑΒΡΩΣ ΑΔΕΣΠΟΤ ΖΩΩΝ_ΣΥΝΤΡΟΦΙΑΣ ΚΑΤΑΦΥΓΙ ΚΤΙΡΙ ΚΤΗΡΙ "
        "ΚΑΘΙΖΗΣ ΥΔΑΤ ΥΔΡΟΔΟΤ ΑΠΟΒΛΗΤ ΚΟΛΠ LNG ΔΙΥΛΙΣΤΗΡΙ ΑΔΜΗΕ ΛΙΓΝΙΤ ΚΤΗΜΑΤΟΓΡΑΦ ΦΡΑΓΜ ΛΙΜΕΝΙΚ ΚΕΝΤΡ*_ΔΕΔΟΜΕΝΩΝ "
        "ΛΑΤΟΜ ΝΑΥΤΙΛ")),
    ("Δημόσια διοίκηση, αυτοδιοίκηση, πολιτισμός", (
        "ΔΗΜΟΣΙΩΝ_ΥΠΑΛΛΗΛ ΥΠΑΛΛΗΛ ΑΣΕΠ. ΠΡΟΣΛΗΨ ΥΠΟΣΤΕΛΕΧΩΣ ΚΕΝΕΣ_ΘΕΣΕΙΣ ΟΡΓΑΝΙΚ*_ΘΕΣ ΚΕΠ. ΔΗΜΑΡΧ ΔΗΜΟΤΙΚ*_ΣΥΜΒΟΥΛ "
        "ΠΕΡΙΦΕΡΕΙΑΚ*_ΣΥΜΒΟΥΛ ΟΤΑ. ΑΥΤΟΔΙΟΙΚΗΣ ΓΡΑΦΕΙΟΚΡΑΤ ΠΟΛΙΤΙΣΜ ΑΡΧΑΙΟΛΟΓ ΜΝΗΜΕΙ ΜΟΥΣΕΙ ΕΡΤ. ΜΜΕ. ΑΘΛΗΤ ΓΗΠΕΔ "
        "ΓΛΩΣΣ ΙΣΤΟΡΙ ΕΚΛΟΓ ΔΗΜΟΣΚΟΠ ΤΥΠΟΥ. ΔΗΜΟΣΙΟΓΡΑΦ ΔΗΜΟΣΙΟΥ_ΤΟΜΕΑ ΘΕΑΤΡ ΦΕΣΤΙΒΑΛ ΑΠΟΚΟΜΜΑΤΙΚΟΠΟΙΗΣ ΘΕΣΕ*_ΕΥΘΥΝΗΣ "
        "ΓΕΝΙΚ*_ΓΡΑΜΜΑΤΕΙ ΚΟΛΥΜΒΗΤΗΡΙ ΠΟΔΗΛΑΤΟΔΡΟΜ ΡΑΔΙΟΦΩΝ ΠΡΟΓΡΑΜΜΑΤΟΣ ΔΗΜΟΣΙ*_ΠΕΡΙΟΥΣΙ")),
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


def category(title):
    """Topic of an act from its title: the category with most distinct keyword hits; ties to the first listed."""
    t = norm(title)
    best, best_n = OTHER, 0
    for name, pat in _CAT:
        n = len(set(pat.findall(t)))
        if n > best_n:
            best, best_n = name, n
    return best


# Names of more than one constituency, and names that are also ordinary words or name a national issue.
WIDE = {"Θεσσαλονίκη": (6, 7), "Αθήνα": (38, 60, 61, 62), "Πειραιάς": (40, 41),
        "Αττική": (38, 40, 41, 60, 61, 62, 63, 64), "Κρήτη": (53, 54, 55, 56), "Θεσσαλία": (22, 23, 24, 25),
        "Θράκη": (1, 2, 3), "Πελοπόννησος": (43, 44, 45, 46, 47), "Επτάνησα": (26, 27, 28, 29),
        "Δωδεκάνησα": (52,), "Κυκλάδες": (51,), "Σαμοθράκη": (1,)}
# Place names that are also ordinary words or name a national issue: never read as a place.
STOP = {stems(w) for w in "Νίκης Ειρήνης Ελπίδας Αγίου Αγίας Μέσης Κεντρικής Άνω Κάτω Νέας Νέου Παλαιάς Ελληνικού "
        "Ηπείρου Μακεδονίας Αιγαίου Ολύμπου Δημοκρατίας Ελευθερίας Σωτήρος Προφήτη Ταξιαρχών Κάμπου Πύργου "
        "Κάστρου Λίμνης Πηγής Βρύσης Ποταμού Ακρόπολης Σταδίου Κρίνου Άσπρου Ζωής Αγάπης Πίστεως Σοφίας Λόγου "
        "Χώρας Νήσων Αμύνης Αρετής Δόξας Ελάτης Πεύκων Δάφνης".split()}


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
        a["category"] = category(a["title"])
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
    p(f"   Στο «{OTHER}»: {100 * cc[OTHER] / len(acts):.1f}%")
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
    p("9. Σύγκριση με τις άλλες ομάδες: πράξεις ανά βουλευτή (ερωτήσεις, επίκαιρες, επερωτήσεις, αναφορές, ΑΚΕ·")
    p("   χωρίς ομιλίες), από τον πίνακα «Πιο δραστήριοι βουλευτές» του Vouliwatch· ομάδα όπως την ημέρα της λήψης.")
    with open(BASELINE, encoding="utf-8-sig") as f:
        base = list(csv.DictReader(f, delimiter=";"))
    grp = defaultdict(list)
    for r in base:
        g = re.search(r"\(([^()]*)\)\s*$", r["ΟΝΟΜΑ"].strip())[1]
        grp[g].append(int(r["ΣΥΝΟΛΟ"]))
    p(f"   {'':<28} {'βουλευτές':>9} {'μέσος':>7} {'διάμεσος':>9} {'σύνολο':>7}")
    for g, v in sorted(grp.items(), key=lambda kv: -statistics.mean(kv[1])):
        p(f"   {g:<28} {len(v):>9} {statistics.mean(v):>7.0f} {statistics.median(v):>9.0f} {sum(v):>7}")
    p("   (Το Vouliwatch μετρά ανά υπογράφοντα· οι πράξεις των Βρεττού και Παπαδόπουλου μετρούν στους Ανεξάρτητους.)")
    OUT_TXT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
