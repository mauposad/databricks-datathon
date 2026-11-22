# Location validation scoring model (v1.1.0)

**Virtue Foundation India Healthcare Datathon · Care Finder**
Status: **final** (v1.1.0, 2026-11-21). Merged to `main` (PR #6); live in `workspace.datathon` once `build_facility_tables` has run.

| | |
|---|---|
| Output | `location_validation_score` 0–5 per facility (3 or more passes) and `location_validation_s`, a 0–1 weighted agreement |
| Method | Rule-based cross-checks combined with a multi-criteria weighted sum (MCDM, swing weights), plus a two-main-check gate |
| Code | `notebooks/location_validation_scoring/` (`01` repair, `02` score, `03` publish) |
| Job | `location_validation_scoring`, run as the first task of `build_facility_tables` (serverless) |
| Tables | `workspace.default.bronze_locval_scores` (every facility, every check) → `workspace.datathon.silver_location_validation` (one row per facility, used by the app) |
| Rules | [`SCORING_CRITERIA.md`](SCORING_CRITERIA.md) (authoritative), decisions in [`DECISIONS.md`](DECISIONS.md) |

---

## 1. Purpose

Facility records come from scraped web pages. Their address, pincode and map point are often typed in the wrong box,
copied from an aggregator or geocoded to a city centre. A facility shown in the wrong place sends a patient to the
wrong town, so the Care Finder must know **how far each record's location can be trusted**.

The model does not look the facility up anywhere. It asks whether the facility's **own location claims agree with
each other** when they are checked against the India Post directory. A record whose pincode, city, district, postal
circle and map point all describe the same place scores high. A record whose claims contradict each other scores low.

Two design rules come from the team (`DECISIONS.md` T7, V5):

* **No single field decides the score.** The data is noisy because sources are under-resourced, not because anyone
  is poisoning it. One bad pincode must not sink an otherwise consistent record.
* **The main location fields carry most of the weight.** Pincode, city/state, district and postal circle make up
  80 % of the score.

## 2. Inputs

| Input | Source | Notes |
|---|---|---|
| Facility address, pincode, coordinates | `facilities` (Delta Sharing), repaired by notebook `01` | About 90 source rows were split by line breaks inside quoted CSV text. 30 facilities are merged back together with their coordinates. |
| Post offices | `india_post_pincode_directory` → `bronze_loclink_offices` | 165,627 offices, 19,586 pincodes. Each office has a state, district, region, circle and division. Coordinates are cleaned, and only offices inside India and inside their own state are used as location references. |
| Pincode centre and size | `bronze_loclink_pincodes` | The median point of each pincode's offices, and `spread_p90_km`, the distance from that median within which 90 % of its offices lie. |

Phone numbers are **not** used (§7, V1).

## 3. How a facility is scored

### 3.1 Read the record

* **State**: the typed state, canonicalised (Orissa → Odisha, then a fuzzy match). If it does not resolve, the city
  is looked up nationally. If all its matching districts are in one state, that state is **inferred** (weaker
  evidence).
* **City**: normalised (Bombay → Mumbai, post-office suffixes removed) and fuzzy-matched at ≥ 0.85 similarity.
* **Pincode**: from the zip field, else from the address lines. If neither is in the directory and a state was
  written, the nearest pincode with the same first five digits in that state is used (**neighbour**, weaker
  evidence). This covers real pincodes the directory is missing, such as Mumbai 400036.
* **Map point**: missing, outside India, or OK. A point used by three or more different facilities is flagged as a
  **shared/default** point.

### 3.2 Three independent sources of "where is this?"

| Source | What it is |
|---|---|
| **P** | The post offices of the facility's pincode |
| **T** | The post offices matched by the written city text (districts of the stated state first, then office names) |
| **G** | Geocoded post offices within 10 km of the facility's map point (none for a shared point) |

### 3.3 Five checks

| Check | Group | Weight | Pass (1) · Partial (½) · Fail (0) |
|---|---|---|---|
| Pincode | main | 0.250 | In the directory and in the stated state · neighbour pincode · otherwise |
| City / State | main | 0.225 | City found in the stated state · state inferred from city · otherwise |
| District / Region | main | 0.175 | T agrees with P or G on district **and** postal region · n/a · otherwise |
| Circle / Division | main | 0.150 | T agrees with P or G on postal circle **and** division · n/a · otherwise |
| Coordinates | secondary | 0.200 | Within `clamp(spread_p90_km, 10, 25)` km of the pincode's median point · n/a · farther, outside India, no reference, or a shared point. **Missing** coordinates are left out. |

The two pair checks must include **T**. Agreement between P and G alone does not count, because the pincode and the
map point already have their own checks. Counting them again would score the same evidence twice (review item L2).

### 3.4 Combine

```
S    = Σ weight × value / Σ weight        (over checks with input; missing coordinates drop out)
gate = pincode + city/state + district/region + circle/division ≥ 2    (values, so a partial counts ½)
```

| Score | Label | Rule | Result |
|---|---|---|---|
| 5 | `verified_all` | gate passed, S ≥ 0.85 | pass |
| 4 | `verified_strong` | gate passed, S ≥ 0.70 | pass |
| 3 | `verified_partial` | gate passed, S ≥ 0.60 | pass |
| 2 | `unverified` | gate failed, or S < 0.60 | fail |
| 1 | `no_location_data` | no city, state, pincode or coordinates | fail |
| 0 | `not_a_facility_record` | orphan CSV fragment | fail |

### 3.5 Why these weights

The weights come from **swing weighting**. Picture a facility that fails every check, and ask which single check you
would most want to flip to a pass. That check is rated 100, and each of the others is rated against it. The weights
were fixed from what the v1.0 run showed about each check, **before** the v1.1 results existed, and were not tuned
afterwards.

| Check | Rating | Reason |
|---|---|---|
| Pincode | 100 | Checked against the official directory; the most specific written claim |
| City / State | 90 | Written text, and the only check that never depends on the pincode or the point |
| Coordinates | 80 | Independent physical evidence, but scraped points are often geocoder guesses |
| District / Region | 70 | Pair check, partly derived from the same pincode and city text |
| Circle / Division | 60 | Coarsest postal unit, so the weakest discriminator |

No single check carries more than 25 %. So one failed check can lower a score but never fail it alone: a record that
passes everything else keeps S ≥ 0.75, or ≥ 0.69 when it has no coordinates.

### 3.6 Worked examples

| Record | S | Score |
|---|---|---|
| Everything agrees | 1.000 | 5 |
| Everything agrees, no coordinates | 1.000 | 5 |
| Neighbour pincode, everything else agrees | 0.875 | 5 |
| All four main checks agree, map point 40 km off | 0.800 | 4 |
| Pincode wrong, everything else agrees | 0.750 | 4 |
| Pincode and city agree, district/circle and map point do not | 0.475 | 2 (fail) |
| Only district/region and the map point agree | — | 2 (fail, gate) |

## 4. Results (v1.1 run, 2026-11-21, 10,000 facilities)

| Score | Facilities | Share |
|---|---|---|
| 5 | 7,091 | 70.9 % |
| 4 | 1,994 | 19.9 % |
| 3 | 318 | 3.2 % |
| 2 (fail) | 597 | 6.0 % |

**Pass rate: 94.0 %** (v1.0: 99.6 %).

| Check | Pass | Partial | Fail |
|---|---|---|---|
| Pincode | 9,564 | 161 (neighbour) | 275 |
| City / State | 9,555 | 252 (inferred) | 193 |
| District / Region | 9,170 | | 830 |
| Circle / Division | 9,266 | | 734 |
| Coordinates | 7,581 | | 2,419 (13 shared points) |

* **Coordinates are the main discriminator.** Of the points that fail, 447 are 10–25 km from their pincode's centre
  and about 1,950 are more than 25 km away (771 more than 200 km). Most pincodes are compact (spread under 10 km), so
  the typical radius is 10 km.
* **Why facilities fail:** 282 fail the gate and 315 have S < 0.60. The largest group (276) has a pincode and city
  that agree with each other at state level, while the district/circle checks and the map point point somewhere else.
  These are the records most worth a manual check.
* **v1.0 → v1.1:** 1,956 facilities went from 4 to 5. They had lost their point only on phones, and the rest of their
  location agrees.

## 5. How the Care Finder uses it

| Where | Rule |
|---|---|
| `find_care`, district planner | Facilities scoring 0–2 are never returned. The count left out is reported as `n_excluded_unverified_location`. |
| Quality score (0–100) | `q_location = round(6 × S)` |
| Trust score (0–100) | `pts_location = round(15 × S)` |
| Result card | "Location n/5" badge and the five checks, each with a plain-language reason (½ for weaker evidence) |
| Unscored facilities | Shown, marked "Location not validated"; Quality and Trust fall back to silver's `location_confidence` (high / medium / low) |

`location_confidence` is still used to choose which map point to show (coordinates or the pincode centre) and to
filter the nearest-emergency fallback. It no longer gives points.

Effect in testing: average Quality went from 46.6 to 47.0. 16,430 of 44,900 facility × service rows changed, by at
most 6 points.

## 6. Limitations

* **No ground truth.** There is no labelled set of facilities with a known true location, so precision and recall
  are not measured. The score measures *consistency*, not correctness. A record that is consistently wrong (every
  field copied from the wrong branch) still scores 5.
* **The directory is incomplete and partly mis-geocoded.** The neighbour-pincode fallback covers missing pincodes
  only when a state is written. Offices outside their own state are ignored as references.
* **Fixed radius floor.** Rural pincodes can be larger than 25 km. Facilities there may fail coordinates even when
  correct, which costs at most 0.20 of S.
* **Address text is only partly used.** Locality names and landmarks in `address_line*` are not matched (review
  item G3).
* **Weights are expert judgement.** They follow a documented swing-weighting rationale, but they were not
  estimated from labelled data.

## 7. What changed from v1.0 and why

| v1.0 | v1.1 | Why (`SCORING_REVIEW.md` item) |
|---|---|---|
| Phone check (telecom circle or STD area must match the state) | **Removed** | Low and unreliable match rates: model-predicted circles matched 17 % of the time, plus number portability, telecom circles spanning up to six states, and scraped lists of 50+ numbers (H1–H3, L5, L6) |
| Within 10 km of *any* office of the pincode | Within 10–25 km of the pincode's *median* point, scaled by its spread | "Any office" was too lenient for large pincodes; a fixed 10 km was too strict for rural ones (H4, L4) |
| Pincode missing from the directory fails | Neighbour pincode counts ½ | The directory lacks real pincodes (H5) |
| A city typed in the state box fails city/state | State inferred from the city counts ½ | (H6) |
| Any two of P, T, G agreeing | Must include T | P=G double-counted the pincode and the point (L2) |
| One main check could pass (score 3) | At least two main checks (gate) | (L3) |
| Rule table of counts | MCDM weighted sum, bands 0.85 / 0.70 / 0.60 | Main checks hardly discriminated, and the score was driven by the secondaries (L1) |
| Shared/default points accepted | Fail coordinates, no G source | (L7) |
| Score was display-only | Feeds Quality and Trust | The location score became the main source for location scoring (V11) |

## 8. Operating the model

```bash
export DATABRICKS_CONFIG_PROFILE=<PROFILE>
databricks bundle deploy --target dev --var care_finder_app_name=care-finder-<you>
databricks bundle run build_facility_tables --target dev --var care_finder_app_name=care-finder-<you>
```

* `build_facility_tables` runs the whole chain: location scoring (`location_linkage/00` and `01` → `02` → `03`
  publish), then silver → gold → `find_care` → district planner.
* To test without touching the live app, run `02` on its own, then `03` with `publish_schema=default`,
  `publish_prefix=lvsbx_`. Then run `src/*.sql` with `workspace.datathon.` rewritten to `workspace.default.lvsbx_`.
* Each new scoring version keeps the previous bronze scores as `bronze_locval_scores_v<old version>`, and notebook
  `02` shows the old → new score transition.
* **To change a rule:** edit `_scoring_common.py` (weights, bands, radii) or `02_score_locations.py`, update
  `SCORING_CRITERIA.md`, add a row to `DECISIONS.md`, and bump `SCORING_VERSION`.

## 9. Licences

* India Post pincode directory, via the datathon Delta Sharing catalog.
* `location_linkage/00` places offices in states and districts with geoBoundaries gbOpen polygons: ADM1 from DataMeet
  India / Election Commission of India (CC BY 2.5 IN), ADM2 from Pathways Data / lgdirectory.gov.in (ODbL 1.0).
