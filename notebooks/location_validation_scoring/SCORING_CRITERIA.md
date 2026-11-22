# Location validation scoring criteria (v1.0.0)

Every facility gets a `location_validation_score` from 0 to 5. **3 or higher passes.** 0, 1 and 2 fail, and
failed locations are left out of the final analysis. Failing rows **stay in bronze** (`bronze_locval_scores`)
with their score, a pass/fail flag and the reason each check failed.

The score comes from two groups of checks:

* **Main checks**: pincode, city/state, district + region, circle + division.
* **Secondary checks**: coordinates and phone numbers.

## Reference data

| Source | Used for |
|---|---|
| `india_post_pincode_directory` (Delta Sharing, read-only) | The master list of real pincodes (19,586 pincodes, 165,627 post offices) and each office's state, district, region, circle and division. Offices are taken from `bronze_loclink_offices`, which adds cleaned coordinates. |
| Google libphonenumber (`phonenumbers` 9.0.44, Apache-2.0) | Checking a phone number is valid and finding its type (landline, mobile, toll-free). Also maps a landline's STD code to "City, State". |
| [hstsethi/in-mob-prefix](https://github.com/hstsethi/in-mob-prefix) (CC BY 4.0, commit `153ba80`) | Maps a mobile number's 4-digit series to a telecom circle. A series missing from the CSV gets the circle predicted by a model (see the Phone check below). |

## Matching rules shared by all checks

* **Text normalisation**: names are upper-cased and stripped of accents and punctuation. Post-office suffixes
  (`B.O`, `S.O`, `H.O`) are removed, and renamed cities map to one spelling (Bombay→Mumbai, Gurgaon→Gurugram, …).
* **Fuzzy match**: two names match when their similarity is **≥ 0.85**. Similarity is the larger of
  whole-string edit similarity and token-set similarity. Generic place words (NAGAR, CITY, ROAD, …) are ignored
  for the token-set part, so a single generic word never produces a match.
* **States**: the typed state is canonicalised to the directory spelling (aliases such as Orissa→Odisha,
  then a fuzzy match ≥ 0.85).
* **Pincode**: the 6 digits of the zip field (`'201 301'` → `201301`). If those digits are not in the
  directory, the first valid pincode written in the address lines is used instead.
* **One pincode has many post offices.** A check passes if **any** office of the pincode agrees.

## Main checks (each is pass or fail; a missing input fails)

| Check | Passes when |
|---|---|
| **Pincode** | The pincode exists in the directory **and** at least one of its offices is in the stated state. With no stated state, one of the pincode's office or district names must instead fuzzy-match the city. |
| **City / State** | The stated state resolves **and** the city fuzzy-matches a directory district in that state. If no district matches, an office name in that state is tried. |
| **District / Region** | Two independent sources name the **same district and the same India Post region** (both parts must match). |
| **Circle / Division** | Two independent sources name the **same India Post circle and the same division** (both parts must match). |

There are three independent sources for the District/Region and Circle/Division checks:

* **P**: the post offices of the facility's pincode
* **T**: the post offices matched by the city text (the city/state check above)
* **G**: geocoded post offices within 10 km of the facility's coordinates

Any two sources agreeing is enough. A wrong pincode therefore does not fail these checks if the city and the
coordinates agree.

## Secondary checks

| Check | Passes | Fails | Missing |
|---|---|---|---|
| **Coordinates** | The facility point is within **10 km** of a geocoded post office of its pincode. If the pincode is unusable, the offices matched by the city are used instead. | The point is farther than 10 km, outside India, or there is no reference office to compare with. | No coordinates (null or 0,0). This is **neutral** and does not count against the facility. |
| **Phone** | The state each number points to matches the stated state or a pincode state. With **one** locatable number, it must match. With **two or more**, **at least two** must match. | Too few numbers match. | No phone, or no number that can be located. This **fails**. |

How a number is located:

* **Landline**: the STD code gives a city and state (e.g. `+91 712…` → Nagpur, Maharashtra). Landlines are kept
  because they stay with the building, so they are good evidence of location. Whether the landline city also
  matches the facility's city or district is recorded in `phone_n_landline_area_match` (for information only).
* **Mobile**: the 4-digit series gives a telecom circle, which gives one or more states. The in-mob-prefix CSV is
  used first. A series not in the CSV gets a circle predicted by a model trained with in-mob-prefix's own recipe
  (`circle_source = 'model'`).
* **Toll-free, premium, invalid or foreign numbers** cannot be located and are ignored.

Telecom circles are not India Post circles. That is why phone evidence is compared at **state** level. For
example, the `DL` circle covers Delhi plus the NCR towns in Haryana and UP.

## Score

`m` = number of main checks passed (0–4). "Secondaries satisfied" means the phone passes **and** the
coordinates pass or are missing.

| Score | Label | Rule | Result |
|---|---|---|---|
| **5** | `verified_all` | m = 4 and secondaries satisfied | pass |
| **4** | `verified_strong` | m = 4 and secondaries not satisfied (even if both fail), **or** m = 2–3 and secondaries satisfied | pass |
| **3** | `verified_partial` | m = 2–3 and secondaries not satisfied (one or none), **or** m = 1 | pass |
| **2** | `unverified` | m = 0, whatever the secondaries say | **fail** |
| **1** | `no_location_data` | No city, state, pincode, coordinates or phone at all | **fail** |
| **0** | `not_a_facility_record` | A CSV fragment that could not be attached to a facility | **fail** |

## Output columns (`bronze_locval_scores`)

* `chk_pincode`, `chk_city_state`, `chk_district_region`, `chk_circle_division`: true or false.
* `chk_coordinates`: `pass`, `fail` or `missing`. `chk_phone`: `pass` or `fail`.
* `why_*`: the reason a check failed. `*_agreed_by` (e.g. `P=T`): which sources agreed on a pair check.
* `n_main_pass`, `location_validation_score`, `location_validation_label`, `location_validation_passed`,
  `failed_checks`.
* Evidence columns: `state_resolved`, `city_match_kind`, `city_matched_names`, `pincode_used`,
  `pincode_source`, `point_status`, `coord_nearest_ref_km`, `phone_n_*`, `reference_states`.
* `scoring_version`, `scored_at`.

Per-number details are in `bronze_locval_phone_numbers`.
