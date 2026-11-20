"""Settings shared by every script: paths, elections and their sources, the database schema, party names.

Adding an election: one line in ELECTIONS (plus SOURCES if the ministry serves it elsewhere),
then fetch.py, build.py and the nationwide pages pick it up.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "data" / "stavroi.sqlite"
OUT = HERE / "out"

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

# Short display names by party id (ids are stable across elections); others show the ministry's name.
PARTY_SHORT = {2: "ΝΔ", 4: "ΣΥΡΙΖΑ", 106: "ΠΑΣΟΚ-ΚΙΝΑΛ", 3: "ΚΚΕ", 108: "Ελληνική Λύση", 122: "ΜέΡΑ25",
               123: "Πλεύση Ελευθερίας", 131: "ΝΙΚΗ", 157: "Σπαρτιάτες", 41: "Χρυσή Αυγή", 158: "Φωνή Λογικής",
               15: "Ένωση Κεντρώων", 28: "Οικολόγοι Πράσινοι", 100: "Λαϊκή Ενότητα", 113: "Ελλήνων Συνέλευσις"}

PARTY_ARTIFACTS = [  # published static map pages, one per party (June share + May top crosses)
    ("ΝΔ", "https://claude.ai/artifact/AA8ahMFs93axFWPMqjE89K"),
    ("ΣΥΡΙΖΑ", "https://claude.ai/artifact/6T4E54QLvdcgcEoarXMzQ3"),
    ("ΠΑΣΟΚ-ΚΙΝΑΛ", "https://claude.ai/artifact/H55tMGJdo7mGiVpks9veRT"),
    ("ΚΚΕ", "https://claude.ai/artifact/7QEvCY57DX38fXR3RKMcw3"),
    ("Σπαρτιάτες", "https://claude.ai/artifact/U9ZYzdXc5TAx3c4NZ5pWoE"),
    ("Ελληνική Λύση", "https://claude.ai/artifact/9FCakTKkFzEJp4jTPbaKkR"),
    ("ΝΙΚΗ", "https://claude.ai/artifact/DkDUaRmft4CLwX5uToXgSM"),
    ("Πλεύση Ελευθερίας", "https://claude.ai/artifact/9YkgFraGBABMQtheiVBUMQ"),
]

# NIKH (party 131) MPs elected 25 June 2023 per constituency (iefimerida.gr, 97.75% counted);
# 10th seat: Apostolakis, Επικρατείας.
ELECTED = {60: "Κουρουπάκη", 61: "Βορύλλας", 62: "Βρεττός", 63: "Οικονομόπουλος", 31: "Τσιρώνης",
           6: "Νατσιός", 7: "Παπαδόπουλος", 22: "Ρούντας", 13: "Δελβερούδης"}
