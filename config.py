"""Settings shared by every script: paths, elections and their sources, the database schema, party names.

Adding an election: one line in ELECTIONS (plus SOURCES if the ministry serves it elsewhere),
then fetch.py, build.py and the nationwide pages pick it up.
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "data" / "stavroi.sqlite"
OUT = HERE / "out"


def accented(s):
    """The ministry writes a capital alpha with tonos as a right quote ("’νδρου" = "Άνδρου"); fixed where names enter the database."""
    return re.sub(r"’(?=\w)", "Ά", s) if isinstance(s, str) else s

ELECTIONS = {  # key -> (short name, page title); oldest first
    "2019": ("2019", "Βουλευτικές εκλογές 2019"),
    "2023/may": ("Μάιος 2023", "Βουλευτικές εκλογές Μαΐου 2023"),
    "2023/june": ("Ιούνιος 2023", "Βουλευτικές εκλογές Ιουνίου 2023"),
    "2024/euro": ("Ευρωεκλογές 2024", "Ευρωεκλογές 2024"),
}
ELECTION_NAMES = {k: short for k, (short, _) in ELECTIONS.items()}


def slug(election):
    """File-name form of an election key: 2023/may -> 2023-may."""
    return election.replace("/", "-")


BASE = "https://ekloges-prev.singularlogic.eu/{election}"
# shortcut: Euro 2024 still lives under /current; move to its ekloges-prev path once the site archives it.
SOURCES = {"2024/euro": ("https://ekloges.ypes.gr/current", "e")}


def source(election):
    """(site base, data kind): 'v' = parliamentary, 'e' = European Parliament."""
    return SOURCES.get(election, (BASE.format(election=election), "v"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS ep(election TEXT, ep_id INT, name TEXT, PRIMARY KEY(election, ep_id));
CREATE TABLE IF NOT EXISTS party(election TEXT, party_id INT, name TEXT, color TEXT,
    PRIMARY KEY(election, party_id));
CREATE TABLE IF NOT EXISTS candidate(election TEXT, ep_id INT, party_id INT, cand_id INT, name TEXT,
    PRIMARY KEY(election, ep_id, party_id, cand_id));
CREATE TABLE IF NOT EXISTS ep_total(election TEXT, ep_id INT, party_id INT, cand_id INT, votes INT,
    PRIMARY KEY(election, ep_id, party_id, cand_id));
CREATE TABLE IF NOT EXISTS station(election TEXT, tm_id INT, ep_id INT, ep_geo INT, kind TEXT,
    ekd_id INT, ekd_descr TEXT, den_id INT, den_descr TEXT, dhm_id INT, dhm_descr TEXT,
    descr TEXT, registered INT, valid INT, PRIMARY KEY(election, tm_id));
CREATE INDEX IF NOT EXISTS station_ep ON station(election, ep_id);
CREATE TABLE IF NOT EXISTS party_votes(election TEXT, tm_id INT, party_id INT, votes INT,
    PRIMARY KEY(election, tm_id, party_id));
CREATE TABLE IF NOT EXISTS cand_votes(election TEXT, tm_id INT, party_id INT, cand_id INT, votes INT,
    PRIMARY KEY(election, tm_id, party_id, cand_id));
-- Written by build.py: the ELSTAT 2021 local community (KAL2022 code) each mapped station lies in.
CREATE TABLE IF NOT EXISTS area_match(election TEXT, tm_id INT, comm_code TEXT, PRIMARY KEY(election, tm_id));
CREATE INDEX IF NOT EXISTS area_match_comm ON area_match(comm_code);
"""

NIKH = 131  # party id of ΝΙΚΗ: the one definition every analysis script imports

# Short display names by party id (ids are stable across elections); others show the ministry's name.
PARTY_SHORT = {2: "ΝΔ", 4: "ΣΥΡΙΖΑ", 106: "ΠΑΣΟΚ-ΚΙΝΑΛ", 3: "ΚΚΕ", 108: "Ελληνική Λύση", 122: "ΜέΡΑ25",
               123: "Πλεύση Ελευθερίας", 131: "ΝΙΚΗ", 157: "Σπαρτιάτες", 41: "Χρυσή Αυγή", 158: "Φωνή Λογικής",
               15: "Ένωση Κεντρώων", 28: "Οικολόγοι Πράσινοι", 100: "Λαϊκή Ενότητα", 113: "Ελλήνων Συνέλευσις"}

# Administrative regions (περιφέρειες) north to south, with the constituency ids (ep_id) of each: the index groups by them.
REGIONS = [
    ("Ανατολική Μακεδονία και Θράκη", [1, 2, 3, 4, 5]),
    ("Κεντρική Μακεδονία", [6, 7, 8, 9, 10, 11, 12, 13]),
    ("Δυτική Μακεδονία", [14, 15, 16, 17]),
    ("Ήπειρος", [18, 19, 20, 21]),
    ("Θεσσαλία", [22, 23, 24, 25]),
    ("Ιόνια Νησιά", [26, 27, 28, 29]),
    ("Δυτική Ελλάδα", [30, 31, 32]),
    ("Στερεά Ελλάδα", [33, 34, 35, 36, 37]),
    ("Αττική", [38, 40, 41, 60, 61, 62, 63, 64]),
    ("Πελοπόννησος", [43, 44, 45, 46, 47]),
    ("Βόρειο Αιγαίο", [48, 49, 50]),
    ("Νότιο Αιγαίο", [51, 52]),
    ("Κρήτη", [53, 54, 55, 56]),
]

# Party colours the ministry data gets wrong for a map: ND and ΠΑΣΟΚ at 3:1 on paper (the ministry's are 2.9 and 2.1).
PARTY_COLOR = {2: "#1f6fd1", 106: "#1a8f5a"}

# NIKH (party 131) MPs elected 25 June 2023 per constituency (iefimerida.gr, 97.75% counted);
# 10th seat: Apostolakis, Επικρατείας (resigned; replaced by Rakovalis). Vrettos and N. Papadopoulos were expelled from the party but kept their seats.
ELECTED = {60: "Κουρουπάκη", 61: "Βορύλλας", 62: "Βρεττός", 63: "Οικονομόπουλος", 31: "Τσιρώνης",
           6: "Νατσιός", 7: "Παπαδόπουλος", 22: "Ρούντας", 13: "Δελβερούδης"}
