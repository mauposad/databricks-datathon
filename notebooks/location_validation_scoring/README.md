# Location validation scoring

This pipeline gives every facility a `location_validation_score` (0–5; 3 or higher passes) before it moves on
from bronze. The score comes from cross-checking pincode, city/state, district + region, circle + division,
coordinates and phone numbers.

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
`../location_linkage/00_build_location_pairs` and notebooks `00` and `01` in parallel, then runs `02`.

You can also run the notebooks interactively in this order: `location_linkage/00` (if `bronze_loclink_offices`
is stale), then `00` → `01` → `02`.

| Notebook | Writes |
|---|---|
| `00_ingest_phone_reference` | `bronze_locval_mobile_prefix` (each mobile series 6000–9999 → telecom circle, from the CSV or a model). Also writes the CSVs and models into the `locval_ref` volume. |
| `01_repair_facility_rows` | `bronze_locval_facilities_repaired` (every source row; CSV-split rows merged back), `bronze_locval_repair_log` |
| `02_score_locations` | `bronze_locval_scores` (one row per facility), `bronze_locval_phone_numbers` (facility × number), `bronze_locval_score_summary` |

Shared code is in `_scoring_common.py`, loaded with `%run ./_scoring_common`. That file itself runs
`../location_linkage/_common`, so both pipelines use the same state spellings, text normalisation and output
widgets (`out_catalog` / `out_schema`, default `workspace.default`).

## Downstream use

```sql
SELECT * FROM workspace.default.bronze_locval_scores WHERE location_validation_passed
```

## External data and licences

* hstsethi/in-mob-prefix, CC BY 4.0, pinned to commit `153ba80`. Attribution is required when results are shared.
* Google libphonenumber (`phonenumbers` 9.0.44), Apache-2.0.
* India Post pincode directory, via the datathon Delta Sharing catalog.
