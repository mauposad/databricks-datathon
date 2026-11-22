# Scoring review: where v1.0.0 falls short or scores too harshly

These notes come from the first full run (2026-11-21, 10,000 facilities). All numbers are from
`workspace.default.bronze_locval_scores` and `bronze_locval_phone_numbers`. Each item gives the evidence, the
direction of the error and a candidate fix. **None are applied yet**: they are for the team to iterate on.

Score distribution today: 5 → 5,616 · 4 → 3,786 · 3 → 554 · 2 → 44. 99.6 % pass.

## Too harsh

| # | Issue | Evidence | Candidate fix |
|---|---|---|---|
| H1 | **The "two must match" phone rule punishes short lists.** A facility with 2 locatable numbers where one matches fails, the same as one where none match. | 1,643 facilities fail with `fewer_than_two_phones_match`. **1,165 of them have exactly one match.** Phone is the only thing keeping 1,357 facilities with all four main checks and coordinates at 4 instead of 5. | Require "at least two, **or** a majority", or "at least one landline match". Or compare the *share* of matching numbers, e.g. ≥ 50 %. |
| H2 | **Model-predicted mobile circles add noise that causes failures.** A predicted number counts as "locatable", which raises the bar to two matches, but it matches only 17 % of the time. | Model hold-out accuracy is 0.17–0.24 for 7/8/9xxx. 447 facilities fail the phone check only because of model numbers. | Ignore model predictions below a probability cutoff, or count them as "not locatable". See DECISIONS F1. |
| H3 | **Ported mobiles.** Mobile number portability lets a number keep its series in another state. `single_phone_state_differs` fails 528 facilities on one number. | 439 of them pass every main check and the coordinate check. | When the only number is a mobile, treat a mismatch as "unverifiable" (neutral) rather than "fail". Landlines stay strict. |
| H4 | **Coordinates must be within 10 km, while silver calls ≤ 25 km "agree".** | 370 coordinate failures are 10–25 km from the nearest office of their pincode. Rural pincodes cover large areas. | Scale the radius by the pincode's own spread (`bronze_loclink_pincodes.spread_p90_km`), or use the silver bands (agree ≤ 25 km, near ≤ 75 km = half credit). |
| H5 | **The directory is incomplete.** Real pincodes (Mumbai 400036, Nagpur 440009) are missing, so the pincode check fails. | 279 facilities have `pincode_not_in_directory`. | Accept the nearest directory pincode with the same first 5 digits and the same stated state (`pincode_source = 'neighbour'`), shown as weaker evidence. See DECISIONS F2. |
| H6 | **A state box holding a city fails city/state.** | `state_missing_or_unresolved` fails 279 facilities, yet T is still found from the state text. | Infer the state from the city match when it is unique nationally (flag it as inferred). |

## Too lenient (scores higher than the evidence deserves)

| # | Issue | Evidence | Candidate fix |
|---|---|---|---|
| L1 | **The main checks hardly discriminate.** Each passes 95–97 % of the time, and 96 % of facilities pass all four. The score is driven mostly by the two secondary checks. | Score matrix. | Weight the checks, or move to the 1–10 scale the team offered, so the main checks have room to separate good and weak records. |
| L2 | **The main checks are correlated, not independent.** The pincode check and city/state both depend on the typed state. District/region and circle/division are settled by `G=P` 87 % of the time, i.e. coordinates plus pincode, which are *also* the coordinate check. One good pincode + coordinates pair passes 3 main checks and 1 secondary at once. | `district_region_agreed_by`: G=P 8,360 · P=T 766 · G=T 517. | Require pair checks to include the T source (written text), or count each underlying source once. |
| L3 | **One main check = pass (3).** A facility can pass on a single matched check. | 60 facilities pass this way (m = 1). | Confirm with the team (raised in DECISIONS). |
| L4 | **Coordinates are compared to *any* office of the pincode.** Large pincodes have offices spread 20–50 km apart, so a point can be "within 10 km" of an outlying office. | Team decision T9 applies "any office" to name matching. Applying it to distance was our extension. | Compare to the pincode's median point (`office_median`, as in location_linkage), with the radius scaled by spread. |
| L5 | **Telecom circles are wide.** `DL` accepts Delhi, Haryana and UP. `NE` accepts six states. `MP` accepts Chhattisgarh. | n/a | Use the landline STD area as district-level evidence (already computed as `phone_n_landline_area_match`), and give landline area matches more weight than circle matches. |
| L6 | **Long scraped phone lists can pass by luck.** With 10+ numbers, 725 of 747 pass. Two matches out of 50 numbers from aggregator pages is weak evidence. | `phone_by_listsize`. | Use the share of matching numbers, or prefer `officialPhone` (first) over the scraped list. |
| L7 | **Shared or default coordinates are not checked.** Location-linkage notebook 11 found shared/default points. Here 10,000 facilities have only 9,947 distinct points. | n/a | Flag points shared by ≥ 3 unrelated facilities, and do not let them satisfy the coordinate check. |

## Gaps (not scored at all)

| # | Gap | Candidate fix |
|---|---|---|
| G1 | The "missing coordinates are neutral" rule never fires: every facility has coordinates after the repair. It is untested. | Add a unit-style test notebook with synthetic records covering each score path. |
| G2 | No ground truth. There is no labelled set of "correct location" facilities, so we cannot measure precision/recall of the score. `eval/` on main has one for services only. | Label ~60 facilities (true location yes/no) and track agreement per score, the way `eval/labels.csv` does for services. |
| G3 | The score ignores `address_line*` text beyond pincode extraction (locality names, landmarks). | Match locality text against office names of the pincode as extra T evidence. |
| G4 | It does not use silver's `far_places_in_text` ("located in X, 300 km away") or `possible_duplicate_of`. | Read them once silver is readable (needs USE SCHEMA on `workspace.datathon`). |
