# Location validation scoring

This pipeline gives every facility a `location_validation_score` (0–5; 3 or higher passes) before it moves on
from bronze. The score (v1.1) is a weighted sum (MCDM, swing weights) of five cross-checks: pincode, city/state,
district + region, circle + division and coordinates. Phone numbers are no longer scored.

* Rules: [`SCORING_CRITERIA.md`](SCORING_CRITERIA.md)
* The reasoning behind every rule, and the row repairs: [`DECISIONS.md`](DECISIONS.md)

## Run

Run it as a bundle job (all tasks on serverless):

```bash
export DATABRICKS_CONFIG_PROFILE=<PROFILE>
databricks bundle deploy --target dev
databricks bundle run location_validation_scoring --target dev
```

The job (`resources/location_validation_scoring.job.yml`) runs
`../location_linkage/00_build_location_pairs` and notebook `01` in parallel, then `02`, then `03` (publish).
**`03` writes into `workspace.datathon`** (the live app's schema): to test, run `01` and `02` on their own.
`build_facility_tables` runs this whole job as its first task, before silver.

You can also run the notebooks interactively in this order: `location_linkage/00` (if `bronze_loclink_offices`
is stale), then `01` → `02`.

| Notebook | Writes |
|---|---|
| `01_repair_facility_rows` | `bronze_locval_facilities_repaired` (every source row; CSV-split rows merged back), `bronze_locval_repair_log` |
| `02_score_locations` | `bronze_locval_scores` (one row per facility), `bronze_locval_score_summary`, and once per version a snapshot of the previous run (`bronze_locval_scores_v1_0_0`) |
| `03_publish_location_scores` | Into `workspace.datathon` for the app: `silver_location_validation` (**one row per `facility_id` = `cluster_id`**, using the row silver keeps for the cluster) and `bronze_locval_facilities_repaired` (read by `src/02_silver_facilities.sql`) |

Shared code is in `_scoring_common.py`, loaded with `%run ./_scoring_common`. That file itself runs
`../location_linkage/_common`, so both pipelines use the same state spellings, text normalisation and output
widgets (`out_catalog` / `out_schema`, default `workspace.default`).

## Downstream use (Care Finder)

* `src/02_silver_facilities.sql` reads the repaired rows (the 30 split facilities now enter silver) and joins
  `silver_location_validation`. A facility with no score gets `location_validation_status = 'not_scored'` and the
  quality flag `location_not_validated`; a score of 0-2 adds `location_unverified`.
* `find_care` and the district planner leave out facilities scoring 0-2 and report how many in
  `n_excluded_unverified_location`. The score is shown on the card (badge + five checks), and its weighted sum `location_validation_s` gives the 6
  `q_location` points of Quality and the 15 `pts_location` points of Trust (`src/03_gold_facility_services.sql`).
* Plan and decisions: [`../../location_scoring_integration_plan.md`](../../location_scoring_integration_plan.md).

```sql
SELECT * FROM workspace.datathon.silver_location_validation WHERE location_validation_passed
```

## External data and licences

* India Post pincode directory, via the datathon Delta Sharing catalog.
