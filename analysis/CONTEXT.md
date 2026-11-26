# analysis/ — ΝΙΚΗ (party 131) statistics

Catalog only: no numbers, no conclusions. Numbers live in each script's `.txt`; the Greek write-up is `NIKH.md` (sections below), the short report `NIKH_anafora.md` (+ pdf) quotes `NIKH.md`; the action plan `NIKH_schedio.md` (+ pdf, no new analysis) quotes both.
Run: `python -I -X utf8 analysis/<script>.py data/stavroi.sqlite` (stdlib only unless noted). The docstring of each script is its contract (inputs, method, output). A step is done when its `.txt` exists and its section is in `NIKH.md`.

## One home per fact

| Fact | Home |
|---|---|
| Party id 131 | `config.NIKH` (import it; never retype) |
| Which party a `nikh_*` script studies | `party.py`: `--party=ID`, `--rival=ID` (default NIKH, 108), `--out=PATH` for pages of another party (never in `out/`); `--base=KEY --target=KEY` (default 2023/june → 2024/euro) in the scripts that compare two elections; NIKH-only sections run only when `party.IS_NIKH`, those about NIKH June 2023 → Euro 2024 only when `party.REFERENCE` |
| Party names, genitive | `config.PARTY_SHORT`, `config.PARTY_GEN` |
| Polls since Sep 2023 | `nikh_polls.csv` (`niki` column hand-checked; other party columns from `polls_wiki.py`); May/June 2023: `nikh_polls_2023.csv` |
| Polls and ballots of all parties, 2007-2024 | `nikh_pollerror.csv` (from `polls_wiki.py`) |
| NIKH level today / in H days | `nikh_polls.estimate(H)` |
| Level of any party today / in H days / as known on a past day | `forecast.estimate(code, H, as_of=day)` (fit on the polls ended by then); codes and columns: `forecast.PARTIES` |
| Ballot error of any party (log ratio, a/p + b); election-day shares summing to 100 | `forecast.error_fit()`; `forecast.simulate(n, H)` |
| National seat forecast (geography per party, probabilities, seat ranges) | `forecast.GEO`, `forecast.seat_sims(n, H)`; summary in `forecast.json` |
| Ballot/poll ratios of NIKH | `nikh_polls.euro_miss`, `nikh_polls.miss_2023` |
| Ballot/poll ratios of other small parties | `nikh_pollerror.ratios(kind)` |
| Ballot/poll coefficient of each firm and party, every poll 2007-2024 (k; house effect h) | `pollster_coef.csv` (from `pollster_coef.py`) |
| Electoral law (seats, threshold, bonus, State seats) and national seat totals | `seats_law.LAWS`, `seats_law.national_seats()` (pure, no db) |
| Seat allocation per constituency, `ep_votes` | `nikh_seats.py` (its national step is `seats_law.national_seats`) |
| Coalitions and the probabilities of a run (who reaches 151, the bonus) | `forecast.COALITIONS`, `forecast.METRICS`, `forecast.rates()` |
| Per-community data | `nikh_drivers.load()` over `build.communities()` |
| Country and city of each station abroad (2023; none for Euro 2024); postal votes (Euro 2024, one station of kind Τ per constituency, tm_id = ep*10000+9999) | table `abroad`, `station.kind='Τ'` (both written by `fetch.py`) |
| Valid votes; 3% threshold in votes | `zones.valid_votes(c, e)`; `zones.threshold(c, e)` (3% of the valid votes, June 2023 by default, from the DB) |

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
| `zones.py` (module: units, tiers, 3% threshold) | db | — | 5, 20, 21 |
| `nikh_pareto.py` | db, `zones.py` | `nikh_pareto.txt` | 5 |
| `nikh_floor.py` | db (`area_match`), `zones.py` | `nikh_floor.txt` | 20 |
| `nikh_backtest.py` | db, `zones.py` | `nikh_backtest.txt` | 21 |
| `nikh_regions.py` | db | `nikh_regions.txt` | 7 |
| `pyei_2019_2023.py --region=N` (per region, 5 election pairs) | db; PyEI venv | `pyei_regions/<base>_to_<target>_<N>.txt` | 7 |
| `pyei_regions_summary.py` | db, `pyei_regions/*.txt` | `pyei_regions/summary.txt` | 7 |
| `benchmark_fetch.py` (every 2nd day by `.github/workflows/benchmark.yml`, PR) | `BASE/data/greece.json` of the outside forecast (network) | `benchmark_runs.csv`, `benchmark_parties.csv` | 18; plan: `benchmark_plan.md` |
| `polls_wiki.py` [cache_dir] | Wikipedia poll tables (network) | `nikh_pollerror.csv`; party columns of `nikh_polls.csv` | plan 2, stage 2 |
| `nikh_polls.py` | `nikh_polls*.csv` | `nikh_polls.txt` | 16, 17 |
| `nikh_pollerror.py` | `nikh_pollerror.csv` | `nikh_pollerror.txt` | 18 |
| `forecast.py` [db [N]] (national forecast, steps 1-3: poll average of every party, ballot error, seats) | `nikh_polls.csv`, `nikh_polls.py`, `nikh_pollerror.csv`, `nikh_pollerror.py`, db + `nikh_seats.py` (step 3) | `forecast.txt`, `forecast.json` | — |
| `forecast_trend.py` (the national forecast every 14 days, with the polls known each day; national seats only) | `forecast.py` (`simulate(as_of=)`, `law_votes`, `rates`), `seats_law.py` | `forecast_trend.json` (trend section of `out/forecast.html`) | — |
| `forecast_backtest.py` (the seat rule of `seats_law.py` on the national votes of 2015-2023, under the law of each election, against the ministry's seats per party) | the results site (`dyn1/v/epik_1.js`), `seats_law.py` (`LAWS`, `ELECTION_LAW`) | `forecast_backtest.json` (check section of `out/forecast.html`; recomputed by `tests/test_forecast.py`) | — |
| `samaras_scenarios.py` [db [N]] (not NIKH: a Samaras party at 10/11/12%, seats, majorities, bonus; source split and geography are judgement, both varied) | `forecast.py` (`simulate`, `spread`, `geography`), db + `nikh_seats.py` | `samaras_scenarios.txt`, `samaras.json` (scenario section of `out/forecast.html`) | — |
| `nikh_flows.py` | `nikh_polls.csv` | `nikh_flows.txt` | 19 |
| `nikh_montecarlo.py` | db, `nikh_polls.py`, `nikh_pollerror.py`, `nikh_seats.py`, `zones.py` | `nikh_montecarlo.txt` | 9, 16, 18 |
| `nikh_abstention.py` | db | `nikh_abstention.txt` | 10 |
| `nikh_spatial.py` | db | `nikh_spatial.txt` | 11 |
| `nikh_clusters.py` | db | `nikh_clusters.txt` | 13 |
| `nikh_ei_compare.py` | db; PyEI venv (arviz) | `nikh_ei_compare.txt` | 14 |
| `nikh_census.py` | db, 2021 census | `nikh_census.txt` | 15 |
| `nikh_map.py` (+ `nikh_map_template.html`) | db | `out/nikh_2023-2024.html` | — |
| `nikh_polls_page.py` (+ `nikh_polls_template.html`) | `nikh_polls*.csv`, `nikh_polls.py`, `pollster_record.py` (`niki_misses()`: how close each firm fell) | `out/nikh_polls.html` | 16, 18 |
| `pollster_coef.py` (ballot / poll of each firm and party over all polls of 12 elections, any lead time; house effect; by lead time) | `nikh_pollerror.csv`; NIKH from `nikh_polls_2023.csv`, `nikh_polls.csv`, `nikh_polls.py` | `pollster_coef.csv`, `pollster_coef.txt` | 25 |
| `pollster_record.py` (error of each firm's last poll before 2019, May and June 2023; `weights()`; house-effect check) | `nikh_pollerror.csv`, `nikh_polls.csv`, `forecast.py` | stdout (and the track-record section of `out/forecast.html`) | — |
| `forecast_page.py` (+ `forecast_template.html`) | `forecast.json` (run `forecast.py` with the db first), `samaras.json`, `forecast_trend.json` (both optional), `forecast_backtest.json`, `nikh_polls.csv`, `pollster_record.py`, db (constituency outlines for the map) | `out/forecast.html` | — |
| `nikh_control_fetch.py` (every act of parliamentary oversight of the 11 MPs elected with ΝΙΚΗ or taking its seat; ≤1 request/s, resumable; `baseline` recounts every MP of `nikh_control_baseline.csv` from the Parliament, `answers` reads 50 random answer PDFs, needs PyMuPDF and tesseract) | hellenicparliament.gr «Μέσα Κοινοβουλευτικού Ελέγχου», vouliwatch.gr API | `data/parl_control/` (git-ignored cache, with `baseline_counts.json`, `answer_sample.json`) | 22 |
| `nikh_control.py` [db] (ministry, topic and place of each act from its title; answers; co-signing; answer day estimated from the Parliament file numbers and checked three ways; who signs the answer; topicals set for debate; Vouliwatch table recounted) | `data/parl_control/`, db (place names), `nikh_control_baseline.csv` (Vouliwatch «Πιο δραστήριοι βουλευτές», acts per MP of every group) | `nikh_control.csv`, `nikh_control.txt` | 22 |
| `abroad.py` [db] (all parties: voters abroad by continent, country and city, 2023; Euro 2024 postal votes against the ballot box, per constituency) | db (`abroad`, postal stations of kind Τ); `data/abroad_geo.json` (city positions; missing ones from Wikidata, rate-limited) | `abroad.txt`, `out/abroad.html` (with a Leaflet map of the cities) | 23 |
| `nikh_ep.py` (the ΝΙΚΗ MEP Αναδιώτης in the European Parliament: every question of the 10th term with authors, addressee and answer, roll-call votes of every plenary day, mandate spans and plenary speeches of all current MEPs; `fetch` caches the API, ≤1 request/s) | EP Open Data API (`data.europarl.europa.eu/api/v2`) | `data/ep_control/` (git-ignored cache), `nikh_ep.txt` | 24 |
| `nikh_ep_stats.py` (statistical checks of Αναδιώτης: rank with split and solo counts and bootstrap; Kaplan–Meier and stratified log-rank of answer times; topic keywords on English titles with Fisher tests and log-odds words; co-signing network and Louvain communities; Poisson test per month; roll-call participation of all 720 MEPs and plenary speeches of all 720) | `data/ep_control/` through `nikh_ep.py` | `nikh_ep_stats.txt` | 24 |

Not NIKH: `field_ops*`, `venue_*`, `client*`, `stats.py` (shared helpers, no catalog entry).
Plans: `NIKH_plan.md` (done), `NIKH_plan2.md` (done), `forecast_plan.md` (forecast page sections; in progress).
Plans: `NIKH_plan.md` (done), `NIKH_plan2.md` (done), `stats_plan.md` (open: calibration, signed bias, shared ballot error, house effects over time, herding, undecided, postal vote, turnout).
Before changing a shared function: rerun the scripts that import it and `cmp` their `.txt` with the committed one.
