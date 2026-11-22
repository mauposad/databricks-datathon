# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Virtue Foundation India Healthcare Datathon on Databricks, at the bronze/exploration stage. There are no tests or build tooling. Code is Databricks notebooks in source format (`# Databricks notebook source` / `# COMMAND ----------` / `# MAGIC`), synced to the workspace by the Asset Bundle (`databricks.yml`; `resources/` holds the `location_validation_scoring` job). Notebooks run on **serverless** compute.

The user wants questions instead of assumptions about data semantics (which location source is "true", how to collapse a pincode to one point, etc.). Surface the choice; don't pick silently.

## Databricks layout

- Workspace host: `https://dbc-92f895df-b358.cloud.databricks.com`
- Shared workspace folder: `/Workspace/Datathon-2026-Shared`
- Dataset (read-only **Delta Sharing** catalog): `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.<table>`. Tables: `facilities`, `india_post_pincode_directory`, `nfhs_5_district_health_indicators`. Always use the fully qualified three-part name.
- Writable location: `workspace.default` (create table/volume). Our tables use the `bronze_loclink_` prefix. Users cannot create schemas in `workspace`. `workspace.datathon` (silver/gold, owned by a teammate) is not readable by every member.
- Data gotchas: the pincode directory has **one row per post office** (~8.5 per pincode), and its latitude/longitude are strings containing `'NA'` (use `try_cast`). `facilities` columns are almost all strings; ~90 rows look column-shifted (`address_countryCode` != `IN`).

## Bundle structure

- `databricks.yml` defines the bundle and a single `dev` target (`mode: development`, default). It deploys to `/Workspace/Datathon-2026-Shared/${bundle.name}/${workspace.current_user.short_name}`, so each collaborator gets an isolated deployment path.
- New resources (jobs, pipelines, etc.) go in `resources/*.yml`. The bundle picks them up through `include`.
- The `care_finder` app name is the bundle variable `care_finder_app_name` (default `care-finder`, the live app owned by a teammate). Dev mode does **not** prefix app names, so deploy your own copy with `--var care_finder_app_name=care-finder-<you>` or the deploy collides with the live app. `databricks bundle sync` uploads files without deploying the app.
- Search vocabulary: `src/06_ref_service_groups.sql` (broad groups + everyday terms) sits on top of `ref_services` (src/03). New terms go there, not in the app; re-run `app/scripts/snapshot_reference.py` after changing either.
- `workspace.datathon` objects (silver/gold tables, `find_care`) are owned by a teammate and back the live app; "account users" can create tables there. Don't rebuild them from your machine without agreeing it first. To test changes to `src/*.sql`, rewrite `workspace.datathon.` to `workspace.default.lvsbx_` in a copy and run that (the backend can point at it with `CARE_SCHEMA=default CARE_OBJECT_PREFIX=lvsbx_`).
- The bundle is deliberately **profile-neutral**. Never add a `profile:` or any personal profile name or credential to `databricks.yml`. The CLI profile is chosen per machine through `DATABRICKS_CONFIG_PROFILE`.

## Commands

```bash
# Authenticate (one-time, per collaborator, browser OAuth)
databricks auth login --host https://dbc-92f895df-b358.cloud.databricks.com --profile <PROFILE>

# Authoritative access check (`databricks auth profiles` may show "Valid: NO" even when auth works)
databricks workspace list /Workspace/Datathon-2026-Shared --profile <PROFILE>

# Bundle operations
export DATABRICKS_CONFIG_PROFILE=<PROFILE>
databricks bundle validate --target dev   # expect "Validation OK!"
databricks bundle deploy --target dev
```

To fix a profile that points at the wrong workspace, run `databricks auth logout --profile <PROFILE>` and then log in again. Pass the host URL unescaped.

## Notebooks

- `notebooks/location_linkage/`: facility-coordinate vs. pincode-location analysis. `00_build_location_pairs` builds all `bronze_loclink_*` tables. `01`–`10` are one notebook per region definition. `11` covers source disagreement and `12` compares pincode-point strategies. `13` overlays GHSL urban-centre population clusters (external download, CC BY 4.0) on the pairs. Shared code is in `_common.py`, loaded with `%run ./_common`, and every notebook first runs `%pip install geopandas==1.0.1`. See that folder's README for run order and outputs.
- `notebooks/location_validation_scoring/`: location validation score (0–5, pass ≥ 3) per facility → `bronze_locval_*` tables. Rules in its `SCORING_CRITERIA.md`, rationale in `DECISIONS.md`. Bundle job `location_validation_scoring` (`resources/location_validation_scoring.job.yml`) runs `location_linkage/00` + its notebooks `00`–`02` on serverless.
- Region notebooks all write into `bronze_loclink_region_summary` with `replaceWhere scheme=...`, so run them sequentially, not in parallel.
- Job-run notebook output is capped at 10 MB for `jobs export-run`; notebook 13 sits near it.
- Serverless runtime has old plotly (5.9: no `Scattermap`; px fails on unused categorical levels) and pandas 1.5.

To test a notebook headlessly: `databricks bundle deploy`, then `databricks jobs submit` a one-time `notebook_task` (no cluster spec = serverless) pointing at `/Workspace/Datathon-2026-Shared/virtue-foundation-india-healthcare-datathon/<user>/files/notebooks/...`. `databricks jobs get-run-output <task_run_id>` shows errors.

## Collaboration workflow

Collaborators clone this repo into a Git-backed Databricks Repo under `/Workspace/Datathon-2026-Shared`. Work happens on feature branches; pull/rebase before sharing changes.
