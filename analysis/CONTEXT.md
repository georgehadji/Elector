# analysis/ — ΝΙΚΗ (party 131) statistics

Catalog only: no numbers, no conclusions. Numbers live in each script's `.txt`; the Greek write-up is `NIKH.md` (sections below), the short report `NIKH_anafora.md` (+ pdf) quotes `NIKH.md`.
Run: `python -I -X utf8 analysis/<script>.py data/stavroi.sqlite` (stdlib only unless noted). The docstring of each script is its contract (inputs, method, output). A step is done when its `.txt` exists and its section is in `NIKH.md`.

## One home per fact

| Fact | Home |
|---|---|
| Party id 131 | `config.NIKH` (import it; never retype) |
| Polls since Sep 2023 | `nikh_polls.csv` (`niki` column hand-checked; other party columns from `polls_wiki.py`); May/June 2023: `nikh_polls_2023.csv` |
| Polls and ballots of all parties, 2007-2024 | `nikh_pollerror.csv` (from `polls_wiki.py`) |
| NIKH level today / in H days | `nikh_polls.estimate(H)` |
| Ballot/poll ratios | `nikh_polls.euro_miss`, `nikh_polls.miss_2023` |
| Seat allocation, `ep_votes` | `nikh_seats.py` |
| Per-community data | `nikh_drivers.load()` over `build.communities()` |
| 3% threshold in votes | `nikh_pareto.THRESHOLD` (3% of June 2023 valid votes, from the DB) |

## Scripts

| Script | Reads | Writes | NIKH.md § |
|---|---|---|---|
| `nikh_vs_2019.py`, `ei_2019_2023.py` | db | stdout | 1, 2 |
| `pyei_2019_2023.py` | db; PyEI venv outside the repo | `pyei*.txt` | 4 |
| `nikh_seats.py` | db | `nikh_seats.txt` | 5 |
| `nikh_targets.py`, `nikh_units.py` | db | stdout | 5 |
| `nikh_targets_map.py` (+ `nikh_targets_template.html`) | db | `out/nikh_targets.html` | 5 |
| `nikh_drivers.py` | db | `nikh_drivers.txt` | 5, 12 |
| `nikh_competition.py`, `nikh_expelled.py` | db | one `.txt` each | 5 |
| `nikh_pareto.py` | db | `nikh_pareto.txt` | 5 |
| `nikh_regions.py` | db | `nikh_regions.txt` | 7 |
| `polls_wiki.py` [cache_dir] | Wikipedia poll tables (network) | `nikh_pollerror.csv`; party columns of `nikh_polls.csv` | plan 2, stage 2 |
| `nikh_polls.py` | `nikh_polls*.csv` | `nikh_polls.txt` | 16, 17 |
| `nikh_montecarlo.py` | db, `nikh_polls.py`, `nikh_seats.py` | `nikh_montecarlo.txt` | 9, 16 |
| `nikh_abstention.py` | db | `nikh_abstention.txt` | 10 |
| `nikh_spatial.py` | db | `nikh_spatial.txt` | 11 |
| `nikh_clusters.py` | db | `nikh_clusters.txt` | 13 |
| `nikh_ei_compare.py` | db; PyEI venv (arviz) | `nikh_ei_compare.txt` | 14 |
| `nikh_census.py` | db, 2021 census | `nikh_census.txt` | 15 |
| `nikh_map.py` (+ `nikh_map_template.html`) | db | `out/nikh_2023-2024.html` | — |

Not NIKH: `field_ops*`, `venue_*`, `karagiannakidis*`, `KARAGIANNAKIDIS*`.
Plans: `NIKH_plan.md` (done), `NIKH_plan2.md` (in progress).
Before changing a shared function: rerun the scripts that import it and `cmp` their `.txt` with the committed one.
