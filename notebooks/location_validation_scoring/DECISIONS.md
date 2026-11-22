# Location validation scoring: decision log

This log records every decision behind `SCORING_CRITERIA.md`, and whether it came from the team or was
proposed during implementation. Items marked **proposed** are open for the team to overturn. To change a rule,
update it in `_scoring_common.py` / `02_score_locations.py`, edit this file and the criteria, and bump
`SCORING_VERSION`.

## Team decisions (2026-11-21)

| # | Topic | Decision |
|---|---|---|
| T1 | Fields | Four main checks (pincode, city/state, district/region, circle/division) and two secondary checks (phone, coordinates). |
| T2 | Matching | Matches are relative: values must agree with each other across the record. Spelling differences are fine. |
| T3 | Fuzzy threshold | 0.85 similarity. |
| T4 | Pincode master list | Validate against the India Post directory. |
| T5 | District / region source | `india_post_pincode_directory`. |
| T6 | Coordinates | Within 10 km. |
| T7 | Bad pincode | Must not fail everything. No single field decides the score: the data is noisy because of under-resourcing, not deliberate poisoning. |
| T8 | Pairs | District + region, and circle + division: **both** parts of a pair must match. |
| T9 | Multiple post offices per pincode | Matching **any** office of the pincode is enough. |
| T10 | Phones | With several numbers, **at least two** must match. Landlines are **not** skipped. |
| T11 | Score table | 4 main and both secondaries → 5. 4 main and one secondary → 4. 4 main and both secondaries fail → 4. 2–3 main and both secondaries → 4. 2–3 main and 0–1 secondaries → 3. Exactly 1 main → 3. 0 main → 2 (fails). |
| T12 | Missing data | A missing phone counts against the facility. Missing coordinates do not. |
| T13 | Failing scores | 0, 1 and 2 do not pass. |
| T14 | Column-shifted rows | Try to repair them, and report what was done (see R1–R4). |
| T15 | Failing rows | Kept in bronze with their score and a pass/fail flag. |
| T16 | Output | `bronze_locval_scores`, one row per facility, with a true/false column and a reason for every check. |
| T17 | Code | A standalone folder, `notebooks/location_validation_scoring/`. It may reuse other notebooks and tables. |
| T18 | Phone reference | Look the series up in the in-mob-prefix CSV. Where it is missing, use a model prediction. |
| T19 | Delivery | Notebooks plus a bundle job, both reproducible and documented. |

## Implementation decisions (proposed)

| # | Topic | Decision and reason |
|---|---|---|
| D1 | Score range | Kept 0–5. The 1–10 option was not needed, because neutral missing coordinates cover the gaps. Under 0–5, 1 = no location data at all and 0 = an orphan CSV fragment (both fail, per T13). |
| D2 | Pincode check | Pass = the pincode is in the directory **and** one of its offices is in the stated state. This checks the pincode against the written address, not only that it exists. If no state is stated, the city must match a district or office name of the pincode. |
| D3 | City/State check | Needs both a state and a city. The city is matched to directory **district** names in the stated state first, and only then to **office** names. This keeps generic office names from producing matches. A state box that holds a city name still feeds source T, but this check fails. |
| D4 | District/Region and Circle/Division | Pass when **two of three independent sources** (P = pincode offices, T = city-matched offices, G = geocoded offices within 10 km) share the same pair. This meets T7: a bad pincode is rescued by city and coordinates. |
| D5 | Coordinates "missing" | Null or (0,0) = missing = neutral (treated as satisfied in the score). A point outside India, or with no reference office to compare against, **fails**. |
| D6 | Coordinates reference | Distance is measured to the nearest geocoded office of the pincode. Only offices inside India and inside their own state count (`bronze_loclink_offices.geo_ok`). If the pincode is unusable, the city-matched offices are used. |
| D7 | Phone comparison level | **State.** Telecom circles are not India Post circles (`DL` spans Delhi and parts of Haryana and UP; `NE` is six states), so a state-level comparison is the only consistent one. The reference states are the stated state plus every state of the pincode's offices. |
| D8 | One phone vs. many | One locatable number → it must match. Two or more → at least two must match (T10). Toll-free, premium, invalid and foreign numbers are ignored. If nothing can be located, the check fails as "missing" (T12). |
| D9 | Landline lookup | Google libphonenumber's STD/SDCA geocoder (Apache-2.0, pinned 9.0.44). No maintained STD-code CSV was found: the DoT National Numbering Plan PDF timed out, and the one GitHub repo has no licence and only covers state capitals. Whether a landline's city also matches is recorded, but it does not change the score. |
| D10 | Mobile model | in-mob-prefix publishes **no trained models** (its `models/` folder is git-ignored), and its recipe predicts the operator, not the circle. So notebook 00 retrains the same recipe (GradientBoosting, 75 trees, depth 2, seed 42) with **circle** as the target. It saves one model per leading digit to the `locval_ref` volume and stores hold-out accuracy and prediction probability next to every predicted series. |
| D11 | Mobile number portability | Since 2015 a number can keep its series after moving to another state. A series therefore shows where the number was issued. The "at least two must match" rule limits the damage. |
| D12 | Pincode fallback | If the zip field is not a directory pincode, the first valid 6-digit pincode in the address lines is used (`pincode_source = address_text`). |
| D13 | City renames | A small alias list (Bombay→Mumbai, Gurgaon→Gurugram, …) is applied before fuzzy matching, because edit distance cannot link renamed cities. |
| D14 | Table prefix | `bronze_locval_*` in `workspace.default`. This keeps the pipeline separate from `bronze_loclink_*`, which it reads. |
| D15 | Dependency | The job runs `location_linkage/00_build_location_pairs` first, so `bronze_loclink_offices` always exists and is current. |

## Integration decisions (2026-11-21)

In short:

* Publish one score per `cluster_id` to `workspace.datathon.silver_location_validation`.
* Silver reads the repaired rows, and unscored facilities are flagged, not dropped.
* `find_care` and the district planner exclude scores 0–2.
* The score is display-only: it does not change rank. *(Superseded by V11.)*
* Scoring revisions wait for v1.1.

## v1.1 team decisions (2026-11-21)

These replace the rules they name. Items refer to `SCORING_REVIEW.md`.

| # | Item | Decision | Replaces |
|---|---|---|---|
| V1 | H1–H3, L5, L6 | **Phone numbers are removed from scoring.** Match rates are too low to rely on (model circles match 17 % of the time), and number portability, wide telecom circles and scraped lists make the evidence too loose. Notebook `00_ingest_phone_reference` and its job task are removed. | T10, T12 (phone half), T18, D7–D11 |
| V2 | H4, L4 | Coordinates are compared to the pincode's **median office point**, within `clamp(spread_p90_km, 10, 25)` km. Pass/fail, no partial band. G keeps its 10 km search. | T6 (now the floor), D6 |
| V3 | H5 | A pincode missing from the directory is replaced by the nearest pincode with the same first 5 digits that has an office in the **stated** state. The pincode check then scores **partial** (0.5). | F2 |
| V4 | H6 | With no usable state, the state is inferred from the city when the city's matched districts all lie in one state. City/state then scores **partial** (0.5). | D3 (last sentence) |
| V5 | L1 | The rule table is replaced by an **MCDM weighted sum** with **swing weights** (pincode 100, city/state 90, coordinates 80, district/region 70, circle/division 60). Main checks carry 80 % of the weight and no check more than 25 %, so no single field decides the score. Weights are set from current evidence, **not tuned on results**. | T11, D1 |
| V6 | L1 | Bands: S ≥ 0.85 → 5, ≥ 0.70 → 4, ≥ 0.60 → 3, below → 2 (fail). | T11 |
| V7 | L2 | Pair checks pass only when the agreeing pair **includes T** (the city text). `G=P` alone no longer passes. | D4 |
| V8 | L3 | **Gate:** the four main checks' values must add up to ≥ 2 (a partial counts 0.5). Coordinates do not count. | T11 ("exactly 1 main → 3") |
| V9 | L7 | A point shared by ≥ 3 different facilities (same `cluster_id` counts once, 5 decimals) fails the coordinate check and gives no G source. | D5 |
| V10 | Missing coordinates | Still neutral: the coordinate weight is left out and the others are renormalised. | (keeps T12) |
| V11 | Care Finder | The location validation score is the **main source for location scoring**: `q_location` (6 Quality points) = `round(6 × location_validation_s)` and `pts_location` (15 Trust points) = `round(15 × location_validation_s)`. A facility with no location score falls back to the old `location_confidence` rule (Quality 6/3/0, Trust 15/8/0). `location_confidence` still picks which map point is shown and filters the nearest-emergency fallback. The location score therefore **can now change rank** through Quality. | Integration decision "display-only" |
| V12 | Rollout | v1.1 is run and compared in `workspace.default` first. Publishing to `workspace.datathon` (notebook 03) happens after the teammate who owns it agrees. | |

## Repairs of column-shifted rows (T14)

| # | Finding / action |
|---|---|
| R1 | The ~88 rows with `address_countryCode` ≠ `IN` are **not** separate facilities. The source CSV was parsed with line breaks inside quoted text, so one facility became a *head* row (identity, phones, address, no coordinates) followed by *fragment* rows. The last fragment (*tail*) holds the facility's GeoJSON point, shifted into an earlier column. |
| R2 | Parquet keeps the original row order (`_metadata.file_name`, `_metadata.row_index`), so each head's fragments sit directly after it. Every `IN` row starts a group, and the non-`IN` rows that follow it belong to that group. |
| R3 | Each head gets `coordinates`, `latitude`, `longitude` (parsed from the GeoJSON, which is unambiguous), `cluster_id` and `source_urls`. The last three are realigned by the tail's column offset, and `realign_check` confirms the realigned lat/lon cells repeat the GeoJSON. The fragment text is kept in `fragment_text`. Other columns (e.g. the rest of the description) are not rebuilt. |
| R4 | All rows are kept in `bronze_locval_facilities_repaired` with a `repair_status`. Merged fragments are not scored. Orphan fragments (none expected) score 0. A per-head log is in `bronze_locval_repair_log`. Results of the first run are under *Run results*. |

## Run results

### v1.0.0, 2026-11-21 (job `location_validation_scoring`, serverless)

**Repair (R1–R4):** 10,088 source rows = 9,970 clean + 30 split facilities (30 heads + 88 fragments).
All 30 heads were repaired. Each got its point back, and the realigned lat/lon matched the GeoJSON in 30 of 30.
There were no orphan fragments, so **10,000 facilities** were scored.

| Score | Facilities |
|---|---|
| 5 | 5,616 |
| 4 | 3,786 |
| 3 | 554 |
| 2 (fail) | 44 |

Pass rates by check:

| Check | Pass rate |
|---|---|
| Pincode | 95.4 % |
| City/state | 95.6 % |
| District/region | 96.4 % |
| Circle/division | 96.7 % |
| Coordinates | 80.7 % (none missing) |
| Phone | 75.1 % |

The 30 repaired facilities scored 4 (14) or 5 (16).

### Findings that need a team decision

| # | Finding |
|---|---|
| F1 | **The model circle predictions are close to noise.** Hold-out accuracy is 0.69 for 6xxx, but only 0.17 / 0.24 / 0.18 for 7xxx / 8xxx / 9xxx (21 circles). Model-predicted numbers match the facility's state only 17 % of the time, against 76 % for CSV-listed series and 86 % for landlines. Without model predictions, 447 facilities that now fail the phone check would pass, and 149 that now pass would fail. |
| F2 | **The directory is not a complete pincode list.** 279 facilities have real-looking pincodes that are missing from it (e.g. Mumbai 400036, Nagpur 440009, while 440008 and 440010 are present). They fail the pincode check. The other checks still score them through T and G. |
| F3 | **Phone lists are noisy.** `phone_numbers` often holds dozens of numbers scraped from aggregator pages, many belonging to other cities. 1,643 facilities fail "at least two must match". |
