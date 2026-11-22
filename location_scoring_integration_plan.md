# Plan: bringing the location validation score into Care Finder

> Status: **implemented on `feature/location-discovery`, tested in a sandbox copy; the live `workspace.datathon`
> silver/gold/`find_care` have not been rebuilt yet** (see *Rollout*). Branch `feature/location-discovery` (main merged in).
> Scoring rules: `notebooks/location_validation_scoring/SCORING_CRITERIA.md`. Known weaknesses:
> `notebooks/location_validation_scoring/SCORING_REVIEW.md`.

## Where things are today

| Layer | Location trust today | Location validation score |
|---|---|---|
| Tables | `workspace.datathon.silver_facilities`: `location_source` (which point to use), `location_confidence` high/medium/low/none, `record_coherence_score` 0–100 with `coh_*` deductions, `identity_conflict` | `workspace.default.bronze_locval_scores`: 0–5 score, pass flag, 6 checks with reasons, per-number phone evidence |
| Key | `facility_id` = `cluster_id`, one row per cluster (the best `unique_id` is kept, all ids in `all_unique_ids`) | `unique_id`, one row per source facility row |
| Ranking (`find_care`) | Quality reliability ≤ 20 = sources 8 + `q_location` 6 (from `location_confidence`) + `q_coherence` 6 | Not used |
| App (`schema.py`, `ResultCard.jsx`, `ScoreBreakdown.jsx`, `HowWeScore.jsx`) | `confidence`, `coherence`, `identity_conflict`, caveats, a "location" segment in the score bar | Not shown |
| Jobs | `build_facility_tables` (SQL warehouse, 01→05) | `location_validation_scoring` (serverless notebooks) |

The two systems answer different questions. Silver decides **which point to use** for distance. Our score rates
**how far the record's location claims agree with each other**, including phone and India Post hierarchy evidence
that silver does not have. The plan keeps silver's point resolution and adds our score as location evidence.

## Steps

### 1. Publish a facility-level table the app can read

* Notebook `03_publish_location_scores` (new, in `location_validation_scoring/`) writes
  `silver_location_validation` with one row per `facility_id` (`cluster_id`):
  * The score of the `unique_id` silver chose (`silver_facilities.unique_id`). Also store `min_score` and
    `max_score` across `all_unique_ids`, so a cluster whose rows disagree is visible.
  * The check columns, compacted to `checks ARRAY<STRUCT<key, label, status, why>>` so the card can render them
    without knowing the column names.
  * `scoring_version`, `scored_at`.
* It is written to **`workspace.datathon`** next to silver (decision A1). This needs `USE SCHEMA` + `CREATE TABLE`
  on `workspace.datathon` for whoever runs the job (we have neither today), or the schema owner runs the job.
  The notebook takes `publish_catalog` / `publish_schema` widgets, so the bronze tables stay in `workspace.default`.
* **Cluster ids for repaired rows.** The 30 repaired facilities have no `cluster_id` in the source. That is why
  silver drops them today (`WHERE cluster_id IS NOT NULL`). Their repaired `cluster_id` comes from the tail row
  (`bronze_locval_facilities_repaired`). See Q4 on whether silver should read the repaired table.

### 2. Use the score in silver/gold (the SQL pipeline): display and gate only

* `02_silver_facilities.sql`: LEFT JOIN `workspace.datathon.silver_location_validation` and carry
  `location_validation_score`, `location_validation_passed` and `location_checks`. Add a quality flag
  `location_unverified` when the score is ≤ 2.
* **Ranking stays as it is (decision A2).** `q_location` / `q_coherence` keep their points. The score is shown,
  not weighted. `q_location_validation` is a later option once the eval set exists.
* **Gate (decision A3, team rule T13):** `find_care` drops every facility with `location_validation_score <= 2`
  from its candidates. A facility with **no** score row (e.g. new data not yet scored) is kept and labelled
  "location not yet validated", so a missing join can never silently empty results. `find_care` returns
  `n_excluded_unverified_location` so the UI can say "N facilities hidden: location could not be verified".
* Append new `find_care` output columns at the end, as phase 3 did, so the adapter keeps working before it is
  updated.

### 3. Show it in the app

* `app/backend/schema.py`: add the optional model
  `LocationValidation {score, label, passed, checks: [Check-like {key, label, status, why}], version}` and the
  field `Recommendation.location_validation: Optional[LocationValidation]`. This follows the "add optional
  fields" rule in that file.
* `app/backend/adapters/find_care.py`: map the new columns.
* `ResultCard.jsx`: a "Location verified 4/5" badge, plus an expandable six-row checklist (✓ / ✗ / –, with
  `why_*` wording in plain language, e.g. "Phone numbers point to Maharashtra; the address says Gujarat").
* `ScoreBreakdown.jsx`: unchanged (the score does not feed ranking yet).
* `HowWeScore.jsx`: print the score table from `SCORING_CRITERIA.md` verbatim.
* Results header: "N facilities hidden because their location could not be verified" (from
  `n_excluded_unverified_location`). There is no toggle to show them (decision A3).

### 4. Orchestration

* Either one job (`location_validation_scoring` followed by `build_facility_tables`), or keep two jobs and have
  `build_facility_tables` start with a run-job task. Serverless notebooks and SQL-warehouse tasks can sit in one job.
* Rerun order: `location_linkage/00` → `locval 00, 01` → `locval 02` → `03_publish` → `src/01` → `02` → `03` → `04` → `05`.

### 5. Iterate and test

1. **Ground truth.** Label ~60 facilities: is the stated location correct? Cover every score and every
   `failed_checks` pattern, plus the 30 repaired rows. Store as `eval/location_labels.csv`, like `eval/labels.csv`.
2. **Agreement report.** For each score, the share of labelled-correct locations. For each candidate fix in
   `SCORING_REVIEW.md`, the before/after change. A notebook `04_evaluate_scoring` writes
   `bronze_locval_eval` per `scoring_version`.
3. **Silver cross-tab.** Score × `location_confidence` × `identity_conflict`. Cases where silver says `high` and we
   say ≤ 3 (or the reverse) are the first things to label. This needs read access to `workspace.datathon` (Q1).
4. **Ranking impact.** Rerun `find_care` for the acceptance queries in `improvement_plan.md` (C-section 226001,
   NICU Muzaffarpur, …). Diff the top-6 before and after, and explain every facility that moves.
5. **Version every change.** Bump `SCORING_VERSION`, record it in `DECISIONS.md`, and keep the previous
   `bronze_locval_scores` as `bronze_locval_scores_v<old>` for comparison.

## Decisions (2026-11-21)

| # | Question | Decision |
|---|---|---|
| A1 | Where the app reads the score from | `workspace.datathon.silver_location_validation`. |
| A2 | How the score feeds ranking | **Display only** for now. Ranking (`q_location`, `q_coherence`) is unchanged. |
| A3 | Scores ≤ 2 | **Excluded** from `find_care` results entirely. |
| A4 | Order | **Integrate v1.0.0 now**, then tune against a labelled eval set with before/after diffs (step 5). |

## Decisions, round 2 (2026-11-21)

| # | Question | Decision |
|---|---|---|
| A5 | Repaired rows | Silver reads `workspace.datathon.bronze_locval_facilities_repaired`, so the 30 repaired facilities enter the app. |
| A6 | Facilities with no score | They stay in results, flagged: `location_validation_status = 'not_scored'`, quality flag `location_not_validated`, a caveat, and a "Location not validated" badge. |
| A7 | Grain | Scores are published **per `cluster_id`** (the app's `facility_id`) for cross-referencing. Within a cluster, the score is taken from the row silver keeps. The join uses the exact source row (`fac_row_id`), because 11 `unique_id`s appear on two rows each. |
| A8 | Scoring revisions | They go into **v1.1** later (`SCORING_REVIEW.md`). This round is integration only. |
| A9 | Access | "account users" can create tables in `workspace.datathon`, and the app's service principal has `SELECT` on the schema, so new tables are readable by the app. Existing objects are owned by the teammate and back the live app. |

## Implementation order

1. `03_publish_location_scores` notebook, plus a `publish` task in the `location_validation_scoring` job.
2. `02_silver_facilities.sql` join and flag. `04_find_care_function.sql` gate and the
   `n_excluded_unverified_location` column (appended).
3. `schema.py` → adapter → `ResultCard.jsx` badge and checklist → `HowWeScore.jsx` rubric → results-header count.
4. Job wiring (step 4), then a full rebuild and the acceptance queries.
5. Eval set and tuning (step 5).

## Rollout

1. ✅ `03_publish_location_scores` wrote `workspace.datathon.silver_location_validation` (9,989 facilities) and
   `workspace.datathon.bronze_locval_facilities_repaired`. Both are owned by us.
2. ✅ The edited `src/01`–`05` (merged with main's PR #4) ran end to end as a sandbox copy
   (`workspace.default.lvsbx_*`). Results:
   * Silver: 9,989 facilities (live 9,959 + the 30 repaired), all scored.
   * `find_care`: rankings for dialysis/Jaipur, C-section/226001, NICU/Muzaffarpur and trauma/Nagpur are identical
     to live, which confirms the score is display-only.
   * The gate removed 1 weak facility in Lucknow. Across gold it removes the 44 facilities scoring 2: 19 with strong
     evidence for some service, 31 moderate, 5 probable, 39 weak.
   * **Known gap:** the 30 repaired facilities are in silver but not in gold. The repair restored their coordinates,
     `cluster_id` and `source_urls`, but not their specialties, procedures or capabilities, which sit in the
     broken-off fragments. So they have no service evidence yet. Fix: realign those columns from the tail too, and
     keep only values that parse as valid lists.
3. ⏳ **Rebuild the live `workspace.datathon`** with `build_facility_tables` (it now runs the scoring job first).
   This replaces the teammate's tables and `find_care` and changes the live app immediately. Run it as the owner,
   or after agreeing it with them.
4. ⏳ **Deploy the app** (`care-finder`) from the merged branch, after step 3. Before step 3 the new card fields stay
   empty, because the old `find_care` lacks the columns and the adapter tolerates that.
