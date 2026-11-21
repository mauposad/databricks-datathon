# Virtue Foundation India Healthcare Datathon

Step-0 repository setup for collaborative work on the Virtue Foundation India
healthcare dataset in Databricks.

## Databricks workspace

- Workspace: `https://dbc-92f895df-b358.cloud.databricks.com`
- CLI profile: each collaborator uses their own local profile name
- Shared workspace area: `/Workspace/Datathon-2026-Shared`
- Git-backed Databricks Repos: planned
- Unity Catalog destination: to be selected
- Compute: to be selected

The checked-in [`databricks.yml`](databricks.yml) intentionally does not create
any jobs, pipelines, clusters, catalogs, schemas, or tables yet. It provides a
development bundle target and gives each authenticated user an isolated bundle
deployment path beneath the shared workspace area.

## Local authentication

Install the Databricks CLI, then authenticate with browser-based OAuth. Each
team member should choose a unique local profile name. Do not commit tokens or
a local `.databrickscfg` file.

Run these commands from the repository root:

```bash
databricks auth login \
  --host https://dbc-92f895df-b358.cloud.databricks.com \
  --profile YOUR_PROFILE_NAME
```

Verify workspace access before running any bundle commands:

```bash
databricks workspace list /Workspace/Datathon-2026-Shared \
  --profile YOUR_PROFILE_NAME
```

The workspace listing should return the contents of the shared folder. This is
the authoritative access check. In some CLI versions, `databricks auth
profiles` may display `Valid: NO` even when authenticated API commands work;
that status is not sufficient to diagnose a failed login.

Use the selected profile for bundle commands by setting it in the shell:

```bash
export DATABRICKS_CONFIG_PROFILE=YOUR_PROFILE_NAME
databricks bundle validate --target dev
```

Expected result:

```text
Validation OK!
```

On Windows PowerShell, use:

```powershell
$env:DATABRICKS_CONFIG_PROFILE = "YOUR_PROFILE_NAME"
databricks bundle validate --target dev
```

The bundle is intentionally profile-neutral. Do not add your personal profile
name to `databricks.yml`; the profile is local to each collaborator’s machine.

### Repairing an existing profile with the wrong workspace

If a profile already exists for another workspace, log it out first, then log
in again. Do not escape the colon in `https://`; use the URL exactly as shown.

```bash
databricks auth logout --profile YOUR_PROFILE_NAME
databricks auth login \
  --host https://dbc-92f895df-b358.cloud.databricks.com \
  --profile YOUR_PROFILE_NAME
```

For the current profile specifically:

```bash
databricks auth logout --profile mekkomau
databricks auth login \
  --host https://dbc-92f895df-b358.cloud.databricks.com \
  --profile mekkomau
```

The profile is local to each person’s computer; teammates should replace
`mekkomau` with their own profile name. The checked-in bundle contains no
personal profile name or credential.

If browser authentication reports success but workspace access still fails,
check that the login uses the exact workspace host above and that the user has
been added to the shared workspace. The team member who created the workspace
may need to grant workspace access and access to
`/Workspace/Datathon-2026-Shared`.

## Git-backed Repo workflow

Each collaborator should clone this Git repository into a Databricks Repo in
`/Workspace/Datathon-2026-Shared`. Keep Git branch ownership clear; use feature
branches for notebooks and code, and pull/rebase before sharing changes.

The CLI bundle configuration is useful for later deployment of jobs, pipelines,
and other resources. It is not required to create a Repo or to browse the
workspace.

## Cleaned data: `workspace.datathon`

The job `build_facility_tables` (defined in `resources/build_facility_tables.job.yml`) runs the SQL
notebooks in `src/` on the Serverless Starter Warehouse and rebuilds these objects. It only reads from
the Marketplace share, which stays untouched.

| Object | Layer | Grain | Purpose |
|---|---|---|---|
| `silver_pincode_geo` | silver | one row per PIN code | Robust PIN location (placeholder + outlier coordinates removed), district/state, ambiguity counts |
| `silver_facilities` | silver | one row per facility (`cluster_id`) | Deduplicated, parsed claim arrays, resolved location + confidence, data-quality flags |
| `ref_state_aliases`, `ref_services` | reference | | State spelling fixes; the keyword rules that define each searchable service |
| `gold_facility_services` | gold | one row per facility × service | Cited evidence, evidence tier, 0–100 trust score with its components, caveats |
| `find_care(service, place, max_km, top_n)` | function | | Ranked recommendations with a `why` (citations) and `how` (score arithmetic) |

```sql
SELECT * FROM workspace.datathon.find_care('dialysis', 'Jaipur');
SELECT * FROM workspace.datathon.find_care('emergency c-section', '226001', 50, 5);
```

Rebuild everything (about 6 minutes):

```bash
databricks bundle deploy --target dev
databricks bundle run build_facility_tables --target dev
```

## Next setup decisions

Before deploying Databricks resources, the team still needs to choose:

1. The Unity Catalog catalog and schema for the Marketplace data.
2. Whether analysis will use serverless, an existing shared compute resource, or
   a job cluster.
3. The first resource to manage as code, such as an ingestion notebook, SQL
   warehouse query, job, or pipeline.
