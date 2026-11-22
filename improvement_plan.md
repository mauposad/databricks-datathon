# Care Finder: correctness + quality-first ranking plan

> Paste this into a new Claude Code session opened in `databricks-datathon/`. It is self-contained.
> **Top priority: transparency and interpretability.** Every score, rank and claim must be traceable to
> verbatim facility text or a printed rule. No black boxes; the LLM never ranks.

## Context

CMU Datathon (Virtue Foundation India facility finder). Input: a service + a location. Output: best facilities
with cited evidence (WHY) and the scoring logic (HOW), stating uncertainty. Must run on Databricks Free Edition.

- Repo: `databricks-datathon` (GitHub `mauposad/databricks-datathon`). `main` contains the merged pipeline and app.
  Start a new branch from `main`, e.g. `feature/quality-ranking`.
- Pipeline (Databricks SQL notebooks, all outputs in `workspace.datathon`):
  - `src/01_silver_pincode_geo.sql` → `silver_pincode_geo` (one row per PIN, robust lat/lon, `place_names` incl. post office names), `haversine_km()`
  - `src/02_silver_facilities.sql` → `silver_facilities` (dedup on `cluster_id`, location voting, `far_places_in_text`, `possible_merged_record`, `quality_flags`)
  - `src/03_gold_facility_services.sql` → `ref_services` (regex rules per service) and `gold_facility_services` (one row per facility × service, `evidence_tier`, `trust_score` with `pts_*`/`pen_*` columns, verbatim citations, `caveats`)
  - `src/04_find_care_function.sql` → `resolve_location(place)` and `find_care(service, place, max_km, top_n)`; currently `match = 0.6 × trust + 0.4 × distance`, weak tier never outranks strong/moderate
  - Job: `resources/build_facility_tables.job.yml`
- App: `app/` (FastAPI backend + React/Vite frontend, Databricks App). Read `interface_build_plan.md` first.
  - `app/backend/adapters/find_care.py` maps `find_care` rows to the universal contract in `app/backend/schema.py`
  - `app/backend/chat.py`: Llama 3.3 70B (`databricks-meta-llama-3-3-70b-instruct`) only parses the query and words the reply; keyword/template fallback
  - `app/frontend/src/speech.js`: browser Web Speech API (`en-IN`)
- Data source (read-only share): `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.{facilities, india_post_pincode_directory, nfhs_5_district_health_indicators}`
- Running SQL locally: Databricks CLI profile `datathon`, Serverless warehouse `ce4eb527f62e5ff7`:
  `databricks api post /api/2.0/sql/statements -p datathon --json '{"warehouse_id":"ce4eb527f62e5ff7","statement":"...","wait_timeout":"50s"}'`
  Never write to the share; write only to `workspace.datathon`.

## What testing against live data found (the problems to fix)

1. **False-positive service matches** (from random samples of strong/moderate rows in `gold_facility_services`):
   - cardiac_surgery: "Blood Vessel Bypass Surgery" matches (a 30-bed child hospital ranks #5 for cardiac surgery in Jaipur)
   - trauma: `trauma` matches "atraumatic", "trauma management in pediatric dentistry", and "listed as an affiliated institution in a 2016 paper"
   - cath_lab: `\bstent` matches "bile duct stenting", "biliary stenting"
   - nicu: "Ambulance … labeled ICU, NICU" counts as NICU equipment
   - mri: "equipment visible in the photo … appears to show a circular-bore device" (speculation); that record also names another hospital (Cloudnine)
   - burn_care and others: long department dumps ("Specializations: Burns Management, Cardiology, General Medicine, …") count like real statements
2. **Trust saturates, so distance decides.** 19% of strong rows hit `pts_evidence = 60`; median strong trust = 75, p90 = 92.
   In Patna/Nagpur/Lucknow the top 6 are all strong with trust 85–100, so order ≈ distance. A 20-bed nursing home is #1 for trauma (Nagpur) and C-section (226001 Lucknow).
3. **Large hospitals under-documented → ranked as weak.** KGMU Lucknow (4,000 beds), AIIMS Patna, AIIMS Nagpur, IGIMS Patna are `weak` for emergency C-section (specialty listed, procedure never named). Weak can never outrank moderate.
4. **Quality vs distance.** NICU near Muzaffarpur: moderate-only hospitals (trust 42–47, 0.1 km) rank #2–#3, above strong hospitals with trust 65–70 ~63 km away.
5. **Implausible doctor counts** (KGMU = 1 doctor, AIIMS Patna = 6) are shown as "1 doctors" tags.
6. **Village names don't resolve:** `resolve_location('Raghopur')` returns nothing, though post office names are in `silver_pincode_geo.place_names`.
7. **Coverage gaps:** 146 of 741 districts have no strong/moderate dialysis facility within 75 km; the list is then padded with weak results.

## Plan (do in this order; commit after each phase)

### Phase 1: Correct matching, measured
1. **Labelled evaluation set.** Create `eval/labels.csv` with ~60 (facility_id, service_key, label ∈ {yes, no, unclear}, note) rows:
   ~10 each for dialysis, emergency_csection, nicu, trauma, cardiac_surgery, mri, deliberately including the false positives above,
   KGMU/AIIMS C-section rows, and some `possible_merged_record` rows. Label by reading the facility's text (procedures, capabilities,
   equipment, description). Add `eval/evaluate.sql` (or a notebook) that reports precision/recall per service for the current rules vs the new ones.
   Keep a keyword+distance baseline for comparison. Report numbers in the README.
2. **Regex fixes in `ref_services`** (03): trauma `\btrauma\b` + exclude dental context (`dental|dentistry|tooth|teeth|oral surgeon`);
   cath_lab exclude stents near `bile|biliary|ureter|ureteric|dj|pcn|ptbd`; cardiac_surgery "bypass" only with `coronary|cardiac|cabg|heart`;
   equipment hits ignored when the phrase is about an `ambulance|vehicle|van`. Re-check each with the eval set.
3. **Claim-type classifier** (new column per cited phrase, in 03): `direct` (default), `list_dump` (phrase has ≥8 comma/semicolon items or
   starts with `departments|specializations|specialities|services include`), `hedged` (`appears|likely|indicates|visible in|photo|referenced|suggests|may`),
   `third_party` (`affiliat|paper|study|partner|tie-up|associated with`, or a different facility name, reuse `far_places_in_text` logic),
   `negated` (existing negation regex). Only `direct` counts fully; `list_dump` counts at most as weak→moderate; `hedged` = weak + flag;
   `third_party` and `negated` don't count and are shown struck through in the UI. Store as `claims_cited ARRAY<STRUCT<text, field, claim_type>>`
   so the card can label each quote.
4. **Specialty scope gate:** if all of a facility's specialties are dental (or all ophthalmology), it can't match non-dental (non-eye) services.
5. **Doctor-count sanity:** null `number_doctors` in silver when `capacity_beds >= 200 AND number_doctors < 10`; add flag `implausible_doctor_count`.

### Phase 2: Evidence checklist (capability graph) for headline services
6. New table `ref_service_requirements(service_key, check_key, check_label, regex, fields ARRAY<STRING>, points INT, links_service STRING)`
   for 6 services (dialysis, emergency_csection, nicu, trauma, cardiac_surgery, mri). Example emergency_csection:
   obstetrics specialty (5) · C-section named explicitly (20) · operating theatre (10) · anaesthesia (10) · blood availability (10, `links_service='blood_bank'`) · 24×7 / emergency (5).
   Points per service sum to 60 so `pts_evidence` keeps its range. Label in UI as "evidence dimensions, not a clinical checklist".
7. New table `gold_facility_service_checks` (one row per facility × service × check): `status ∈ {found, unknown, contradicted}`, `cited_text`, `field`, `claim_type`.
   Missing = unknown (0 points, never a penalty). For headline services, `pts_evidence` = sum of found checks; other services keep current rules.
8. **New tier `probable`** between moderate and weak: service specialty listed AND (capacity_beds ≥ 100 OR name matches `medical college|institute of medical sciences|aiims|district hospital`).
   Caveat text: "Procedure not named in the record; <facility> lists <specialty> and <beds> beds. Call to confirm." Tier order: strong > moderate > probable > weak.

### Phase 3: Quality-first ranking (rewrite of find_care logic)
9. Split the score:
   - **Quality (0–100)** = service evidence depth (≤50, scaled from checklist) + service readiness (≤30: hospital vs clinic, bed band,
     supporting services relevant to this service, e.g. ICU + blood bank for C-section, 24×7 for trauma, using other rows of
     `gold_facility_services`) + record reliability (≤20: source domains, location confidence, coherence) − existing penalties.
     Store every component as its own column.
   - **Estimated travel time** = km × 1.4 ÷ 35 km/h (print this assumption in UI).
10. New table `ref_service_policy(service_key, travel_budget_min, urgency, rationale)`: emergency_csection 60, trauma 60, nicu 90,
    dialysis 45 (recurring 3×/week), mri 180, cardiac_surgery 240, oncology 240, others sensible defaults. Shown in "How we score".
11. **Ranking rule (print verbatim in the UI and in `how`):** "Among facilities reachable within this service's travel budget, we rank by
    Quality. If two are within 10 Quality points, the closer one wins. Facilities beyond the budget appear only if nothing within it
    qualifies, labelled 'farther option'." Tier order still applies (weak never above probable/moderate/strong).
    Implement in `find_care` (keep old output columns; append new ones at the end so the adapter keeps working).
12. **Auto-radius:** if no strong/moderate/probable facility is within the budget, expand (×2 up to 300 km) and return a note:
    "Nearest confirmed option is N km away." Don't pad with weak results without saying so.
13. **Nearest-option card + counterfactual:** if the nearest qualifying facility isn't #1, return it flagged `is_nearest_alternative`
    with a generated trade-off sentence: "<Nearest> is X min closer but has a/b evidence items for <service>; <#1> has c/b plus ICU and blood bank."
    Also: "What would change this: confirming <missing check> at <nearest> would add P quality points (gap is G)." Pure arithmetic on stored components.
14. **Safety line** for urgent services (C-section, trauma): "If the patient is unstable, go to the nearest 24×7 emergency facility first." with that facility shown.

### Phase 4: Record coherence (identity fingerprints)
15. In silver, add `silver_identity_claims` (facility_id, claim_type, claim_value, source_field, agrees_with_location BOOL) and a
    `record_coherence_score` built from named components: coords↔PIN agreement, city text agreement, state field agreement,
    no far "located in" places, no other facility name in description, no near-duplicate neighbour.
    Near-duplicate detection in SQL: normalise names (strip hospital/clinic/pvt/ltd/punctuation), compare within the same 1° grid cell
    (reuse `fac_cells` pattern) with `levenshtein` ≤ 2; store `possible_duplicate_of` (flag, don't merge).
16. Feed coherence into the reliability part of Quality. Rule: unresolved identity conflict caps the confidence label at Medium.

### Phase 5: Location + app UX
17. `resolve_location`: add a post-office/village match step (match `place_names` in `silver_pincode_geo`, priority after PIN, before district).
    Test with 'Raghopur', 'Sadikpur', 'Hanriya'.
18. App cards (`ResultCard.jsx`, `ScoreBreakdown.jsx`, `HowWeScore.jsx`, adapter + `schema.py`): show the ✓/?/✗ checklist with quotes and
    claim-type labels, Quality components, travel-time estimate + assumption, the ranking rule, nearest-option card with trade-off sentence,
    "What would change this", safety line, "Call to confirm: <one fact to check>" with phone button.
19. Chat transparency: show "Searching: <service> near <place>, <km> km (understood by LLM|keywords)" above results using
    `ChatResponse.query`/`parsed_by`. Add a grounding check on the LLM reply: every facility name and number in the reply must appear in
    the results, else use `template_reply`.
20. Optional: "Government / free only" filter on `operator_type`; Hindi (`hi-IN` speech + "reply in the user's language" in the prompt).

### Phase 6 (stretch)
21. Verification overlay: `workspace.datathon.verifications(facility_id, service_key, check_key, status, reviewer, ts, note, evidence_url)`;
    reviewer from Databricks Apps `X-Forwarded-Email`; LEFT JOIN in `find_care`; Confirm/Reject buttons; never write into silver/gold.
22. District planner view: per district, travel time to nearest quality facility per service, alongside NFHS-5 indicators
    (e.g. `institutional_birth_in_public_facility_5y_pct`).
23. Stability: 3–6 named scenarios (uncertain locations swapped to their alternate, only strong evidence counts, single-source claims ignored)
    → "Stays #1 in k of n scenarios". No unexplained random sampling.

## Acceptance checks
- Eval set: precision per headline service reported before/after; no known false positive from the list above survives.
- `find_care('emergency c-section','226001',50,6)`: KGMU appears as `probable`, not hidden; a 20-bed nursing home only beats tertiary
  hospitals when its Quality is genuinely within 10 points.
- `find_care('nicu','Muzaffarpur',100,6)`: strong hospital ranks above moderate-only ones; nearest-option card explains the trade-off.
- `resolve_location('Raghopur')` returns a Bihar location with `matched_as = 'post_office'`.
- Every card states WHY (verbatim quotes + field) and HOW (components + printed rule); no hidden weights.
- Rebuild order works end-to-end: 01 → 02 → 03 → 04 (update the job YAML if new notebooks are added); app still runs against the new `find_care`.
