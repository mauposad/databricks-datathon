# Scoring v1.1 plan (branch `feature/final-scoring-tuning`)

Working plan for the final changes to the **location validation score** and the Care Finder **quality score**.
Item numbers refer to `SCORING_REVIEW.md`. The decisions are recorded as V1–V12 in `DECISIONS.md`, and the
rules in `SCORING_CRITERIA.md`.

## Decisions (2026-11-21)

| Item | Decision |
|---|---|
| H1–H3, L5, L6 | Phone numbers removed from scoring. |
| H4, L4 | Pincode median point, radius `clamp(spread_p90_km, 10, 25)` km, pass/fail. |
| H5 | Neighbour pincode (same first 5 digits, stated state) counts half. |
| H6 | State inferred from a nationally unique city match counts half. |
| L1 | MCDM weighted sum with swing weights 100 / 90 / 80 / 70 / 60 (pincode, city/state, coordinates, district/region, circle/division), fixed from current evidence. Bands 0.85 / 0.70 / 0.60. |
| L2 | Pair checks must include T (city text). |
| L3 | Gate: main-check values sum ≥ 2 (a half counts half). |
| L7 | Shared points (≥ 3 different facilities) fail coordinates. |
| Care Finder | Main source for location scoring: `q_location` = `round(6 × S)`, Trust `pts_location` = `round(15 × S)`; unscored facilities keep the old confidence rule. |
| Rollout | Run in `workspace.default` first, compare with v1.0, then publish to `workspace.datathon` with the owner's agreement. |

## Status

| Step | State |
|---|---|
| Code: `_scoring_common`, `02`, `03`, job, notebook `00` removed | done |
| Care Finder: `src/02`, `src/03`, app text, partial status on cards | done |
| Docs: criteria, decisions, review, README | done |
| Run `02` in `workspace.default`, v1.0 → v1.1 transition (v1.0 kept as `bronze_locval_scores_v1_0_0`) | done |
| Sandbox: `03` with `publish_prefix=lvsbx_`, then `src/02` + `src/03` against `workspace.default.lvsbx_*` | done |
| Publish (`03`) + rebuild `workspace.datathon` + app deploy | agreed 2026-11-21, in progress |

## v1.1 results (2026-11-21, 10,000 facilities)

| Score | v1.0 | v1.1 |
|---|---|---|
| 5 | 5,616 | 7,091 |
| 4 | 3,786 | 1,994 |
| 3 | 554 | 318 |
| 2 (fail) | 44 | 597 |

Pass rate 99.6 % → 94.0 %. Most 4 → 5 moves (1,956) are facilities that only lost a point on phones.

| Check | pass | partial | fail |
|---|---|---|---|
| Pincode | 9,564 | 161 (neighbour) | 275 |
| City / state | 9,555 | 252 (inferred) | 193 |
| District / region | 9,170 | | 830 |
| Circle / division | 9,266 | | 734 |
| Coordinates | 7,581 | | 2,419 (13 shared points) |

* Fails: 282 on the gate, 315 on S < 0.60. The largest group (276) passes pincode + city/state but fails both
  pair checks and coordinates.
* Coordinates: 562 facilities went pass → fail (median point instead of nearest office), 70 fail → pass. Most
  pincodes have `spread_p90_km` under 10 km, so the radius stays 10 km for the median facility. 447 points
  10–25 km away still fail; 1,948 are more than 25 km away.
* Pair checks: `P=G=T` 7,493, `G=T` 894, `P=T` 783; 638 fail because T disagrees, 192 because T is not placed.
* Care Finder (sandbox): average Quality 46.6 → 47.0, average `q_location` 5.0 → 5.4; 16,430 of 44,900
  facility × service rows change, by at most 6 points. With Trust also switched, average Trust is 47.4.
  Location score 5 → `q_location` 5–6, 4 → 5, 3 → 4.
