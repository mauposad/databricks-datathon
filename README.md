# Virtue Foundation India Healthcare Datathon

Step-0 repository setup for collaborative work on the Virtue Foundation India
healthcare dataset in Databricks.

## Databricks workspace

- Workspace: `https://dbc-92f895df-b358.cloud.databricks.com`
- CLI profile: each collaborator uses their own local profile name
- Shared workspace area: `/Workspace/Datathon-2026-Shared`
- Git-backed Databricks Repos: planned
- Unity Catalog catalog: `databricks_virtue_foundation_dataset_dais_2026`
- Unity Catalog schema: `virtue_foundation_dataset`
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
| `silver_facilities` | silver | one row per facility (`cluster_id`) | Deduplicated, parsed claim arrays, resolved location + confidence, data-quality flags, `record_coherence_score` with named `coh_*` deductions, `identity_conflict` |
| `silver_identity_claims` | silver | one row per identity claim | Coordinates, PIN, city, state, "located in" places, other facilities named, near-duplicates, each marked as agreeing with the resolved location or not |
| `silver_possible_duplicates` | silver | one row per record pair | Different records within 3 km with near-identical distinctive names and the same focus; flagged, never merged |
| `ref_city_districts` | reference | city × district | City spellings learned from records whose coordinates and PIN agree ("Bangalore" ↔ Bengaluru Urban) |
| `ref_state_aliases`, `ref_services` | reference | | State spelling fixes; the keyword rules that define each searchable service |
| `gold_facility_services` | gold | one row per facility × service | Cited evidence, evidence tier, 0–100 trust score with its components, caveats |
| `facility_phrases` | gold (helper) | one row per phrase | Every verbatim phrase of every record (procedures, capabilities, equipment, description sentences, specialties) |
| `ref_service_requirements` | reference | one row per service × check | Evidence dimensions for the 6 headline services (not a clinical checklist); points sum to 60 |
| `gold_facility_service_checks` | gold | one row per facility × service × check | found / unknown / contradicted, with the phrase that decided it; missing = unknown, never a penalty |
| `ref_service_support` | reference | one row per service × supporting service | Supporting services that count toward readiness (e.g. ICU + blood bank + NICU for C-section) |
| `ref_service_policy` | reference | one row per service | Travel-time budget and urgency (C-section 60 min, dialysis 45 min, cardiac surgery 240 min, ...) |
| `verifications`, `verifications_latest` | overlay | one row per reviewer decision | Confirm / Reject from the app (reviewer = Databricks Apps user). `find_care` applies the latest decision per facility × service × check; never merged into silver/gold, and kept across rebuilds |
| `gold_district_access` | gold (planner) | district × headline service | Travel time from each district centre to the nearest quality facility (strong/moderate, Quality ≥ 70) and nearest facility with any evidence, with NFHS-5 indicators |
| `ref_nfhs_district_match` | reference | NFHS district | NFHS-5 district → India Post district (98% matched; rule recorded: exact, spacing, rename, prefix, spelling) |
| `resolve_location(place)` | function | | PIN code, `lat,lon`, city, **post office / village** ("Raghopur", or "Sadikpur, Bihar" to disambiguate) or district → coordinates, with a note when a name is ambiguous |
| `find_care(service, place, max_km, top_n, operator_filter)` | function | | Quality-first ranking within the travel budget, with a `why` (citations), `how` (Quality arithmetic), evidence checklist, labelled quotes, call-to-confirm, nearest-option trade-off, safety line and search notes; `operator_filter => 'public'` for government facilities only |

**How results are ranked** (also returned verbatim in every row's `ranking_rule`): among facilities reachable within
the service's travel budget, rank by Quality (0–100 = evidence ≤50 + readiness ≤30 + record reliability ≤20 −
penalties). If two are within 10 Quality points, the closer one wins. Facilities beyond the budget come next, labelled
"farther option"; weak (unconfirmed) evidence always comes last. If nothing qualifies in the radius, it is doubled up
to 300 km. Travel time = straight-line km × 1.4 ÷ 35 km/h.

**How solid is this pick?** Every search double-checks #1 by re-running the ranking three times, each time doubting
one part of the data (only detailed evidence counts; facilities found on just one website are ignored; fuzzy
addresses moved to their other recorded location). #1 is a **Solid pick** if it stays on top every time; otherwise a
**Shaky pick**, naming who would take its place ("Shaky pick: if its one website is wrong, X is #1."). Two
situation checks (travel twice as far; only the evidence matters, not hospital size or backup services) never count
against #1; they become tips on other cards ("Would be your best option if you can travel up to 2 hours."). No random
sampling.

```sql
SELECT * FROM workspace.datathon.find_care('dialysis', 'Jaipur');
SELECT * FROM workspace.datathon.find_care('emergency c-section', '226001', 50, 5);
SELECT * FROM workspace.datathon.find_care('trauma', 'Raghopur');                  -- village / post office
SELECT * FROM workspace.datathon.find_care('emergency c-section', '226001', 50, 5, 'public');  -- government only
```

### Matching quality (hand-labelled evaluation)

`eval/` holds 82 hand-labelled facility × service pairs and a script that reports precision/recall
(see [`eval/README.md`](eval/README.md)). A facility counts as offering a service when its tier is strong or moderate.

| version | precision | recall |
|---|---|---|
| keyword baseline (any alias anywhere) | 0.80 | 0.76 |
| original rules (v1) | 0.78 | 0.76 |
| exclusions + claim types + dental/eye scope gate | **1.00** | 0.75 |
| + `probable` tier (large/teaching hospital lists the specialty) | **1.00** | 1.00 |

Of 16 random `probable` rows, 7 were confirmed and 9 genuinely unclear, so `probable` is shown as "call to confirm".

Rebuild everything (about 6 minutes):

```bash
databricks bundle deploy --target dev
databricks bundle run build_facility_tables --target dev
```

## Next setup decisions

Before deploying Databricks resources, the team still needs to choose:

1. Whether analysis will use serverless, an existing shared compute resource, or
   a job cluster.
2. The first resource to manage as code, such as an ingestion notebook, SQL
   warehouse query, job, or pipeline.

The shared dataset can be referenced with the fully qualified namespace:

```text
databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.<table>
```
