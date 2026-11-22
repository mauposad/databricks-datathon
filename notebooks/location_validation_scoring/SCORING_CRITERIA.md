# Location validation scoring criteria (v1.1.0)

Every facility gets a `location_validation_score` from 0 to 5. **3 or higher passes.** 0, 1 and 2 fail, and
failed locations are left out of the final analysis. Failing rows **stay in bronze** (`bronze_locval_scores`)
with their score, a pass/fail flag and the reason each check failed.

The score is a **multi-criteria weighted sum (MCDM)** of five checks:

* **Main checks**: pincode, city/state, district + region, circle + division.
* **Secondary check**: coordinates.

Phone numbers are **not** scored (removed in v1.1, see `DECISIONS.md` V1).

## Reference data

| Source | Used for |
|---|---|
| `india_post_pincode_directory` (Delta Sharing, read-only) | The master list of real pincodes (19,586 pincodes, 165,627 post offices) and each office's state, district, region, circle and division. Offices are taken from `bronze_loclink_offices`, which adds cleaned coordinates. |
| `bronze_loclink_pincodes` | Each pincode's median office point (`lat/lon_office_median`) and office spread (`spread_p90_km`, the 90th-percentile distance of its offices from that median). |

## Matching rules shared by all checks

* **Text normalisation**: names are upper-cased and stripped of accents and punctuation. Post-office suffixes
  (`B.O`, `S.O`, `H.O`) are removed, and renamed cities map to one spelling (Bombay→Mumbai, Gurgaon→Gurugram, …).
* **Fuzzy match**: two names match when their similarity is **≥ 0.85**. Similarity is the larger of
  whole-string edit similarity and token-set similarity. Generic place words (NAGAR, CITY, ROAD, …) are ignored
  for the token-set part, so a single generic word never produces a match.
* **States**: the typed state is canonicalised to the directory spelling (aliases such as Orissa→Odisha,
  then a fuzzy match ≥ 0.85).
* **Inferred state**: if the typed state does not resolve, the city (or the state box read as a city) is matched
  to district names nationwide. If every matched district lies in **one** state, that state is used
  (`state_source = inferred_from_city`). This is weaker evidence.
* **Pincode**, in order: the 6 digits of the zip field (`'201 301'` → `201301`) if they are in the directory;
  else the first directory pincode written in the address lines; else, if a state was **stated**, the
  directory pincode with the **same first 5 digits** that has an office in that state, nearest by number
  (`pincode_source = neighbour`, weaker evidence).
* **One pincode has many post offices.** For name checks, any office of the pincode may agree.

## Check values

Each check is `pass` (value 1), `partial` (0.5, weaker evidence counts half) or `fail` (0). The coordinate check
can also be `missing`, which leaves it out of the score.

| Check | Group | Pass (1) | Partial (0.5) | Fail (0) |
|---|---|---|---|---|
| **Pincode** | main | The pincode is in the directory **and** one of its offices is in the stated state. With no stated state, one of the pincode's office or district names fuzzy-matches the city. | The same, but on a **neighbour** pincode. | No usable pincode, or it is in another state / does not match the city. |
| **City / State** | main | The stated state resolves **and** the city fuzzy-matches a directory district in that state (failing that, an office name in that state). | The state was **inferred from the city**. | No state, no city, or the city is not in the stated state. |
| **District / Region** | main | The offices matched by the city text (**T**) share the same **district and India Post region** with the pincode's offices (**P**) or with the geocoded offices within 10 km of the point (**G**). | n/a | T is missing, or neither P nor G agrees with it. |
| **Circle / Division** | main | The same, for **India Post circle and division**. | n/a | The same. |
| **Coordinates** | secondary | The point is within `r` km of the pincode's **median office point**, where `r = clamp(spread_p90_km, 10, 25)`. If the pincode is unusable, the median and spread of the geocoded city-matched offices are used. | n/a | Farther than `r`, outside India, no reference point, or a **shared point** (the same point, to 5 decimals, used by ≥ 3 different facilities). |

`P=T` and `G=T` agreement both count. `G=P` alone does **not** count, because both come from the pincode and
the point, which are already scored by their own checks. A shared point gives no G source.

## Score

**Weights (swing weighting).** Picture a facility that fails every check, and ask which single check you would
most want to flip to a pass. That check is rated 100, and each other check is rated against it. Weights are the
ratings divided by their sum. They were set from the v1.0 evidence and are not tuned on results.

| Check | Rating | Weight | Why |
|---|---|---|---|
| Pincode | 100 | 0.250 | Checked against the official directory; the most specific written claim. |
| City / State | 90 | 0.225 | Written text, and the only check that never depends on the pincode or the point. |
| Coordinates | 80 | 0.200 | Independent physical evidence, but scraped points are often geocoder guesses. |
| District / Region | 70 | 0.175 | Pair check, partly derived from the same pincode and city text. |
| Circle / Division | 60 | 0.150 | Coarsest postal unit, so the weakest discriminator. |

Main checks carry 80 % of the weight, and no single check carries more than 25 %.

`S = Σ wᵢ·vᵢ / Σ wᵢ` over the checks that have input (missing coordinates drop out and the other weights are
renormalised, so missing coordinates never count against a facility).

**Gate.** The values of the four main checks must add up to **at least 2** (a partial counts 0.5). Coordinates do
not count toward the gate.

| Score | Label | Rule | Result |
|---|---|---|---|
| **5** | `verified_all` | gate passed and S ≥ 0.85 | pass |
| **4** | `verified_strong` | gate passed and 0.70 ≤ S < 0.85 | pass |
| **3** | `verified_partial` | gate passed and 0.60 ≤ S < 0.70 | pass |
| **2** | `unverified` | gate failed, or S < 0.60 | **fail** |
| **1** | `no_location_data` | No city, state, pincode or coordinates at all | **fail** |
| **0** | `not_a_facility_record` | A CSV fragment that could not be attached to a facility | **fail** |

Examples:

| Facility | S | Score |
|---|---|---|
| All 4 main + coordinates | 1.000 | 5 |
| All 4 main, coordinates missing | 1.000 | 5 |
| Neighbour pincode (½) + other 3 main + coordinates | 0.875 | 5 |
| All 4 main, coordinates fail | 0.800 | 4 |
| City/state + both pair checks + coordinates, pincode fails | 0.750 | 4 |
| Pincode + city/state + coordinates, both pair checks fail | 0.675 | 3 |
| Pincode + city/state, coordinates and pair checks fail | 0.475 | 2 |
| Inferred state (½) + pincode (½), everything else fails | — | 2 (gate: 1.0 < 2) |

## Downstream

`S` (`location_validation_s`) is the Care Finder's main location signal (`src/03_gold_facility_services.sql`):
`q_location = round(6 × S)` (Quality) and `pts_location = round(15 × S)` (Trust).

## Output columns (`bronze_locval_scores`)

* `chk_pincode`, `chk_city_state`, `chk_district_region`, `chk_circle_division`: `pass`, `partial` or `fail`.
  `chk_coordinates`: `pass`, `fail` or `missing`.
* `val_*`: each check's value (1 / 0.5 / 0, null when missing). `why_*`: the reason a check failed or is partial.
  `*_agreed_by` (e.g. `P=T`, `P=G=T`): which sources agreed on a pair check.
* `main_value`, `n_main_pass` (full passes), `gate_passed`, `location_validation_s`, `location_validation_score`,
  `location_validation_label`, `location_validation_passed`, `location_validation_fail_reason`, `failed_checks`,
  `partial_checks`.
* Evidence columns: `state_resolved`, `state_source`, `city_match_kind`, `city_matched_names`, `pincode_written`,
  `pincode_used`, `pincode_source`, `point_status`, `point_n_facilities`, `point_shared`, `coord_ref_source`,
  `coord_median_km`, `coord_radius_km`.
* `scoring_version`, `scored_at`.
