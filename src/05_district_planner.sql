-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 05 · District planner
-- MAGIC
-- MAGIC For health planners rather than patients: per district and headline service, how far is the nearest facility with
-- MAGIC confirmed or probable evidence, and the nearest **quality facility** (strong/moderate evidence and Quality ≥ 70),
-- MAGIC next to NFHS-5 district indicators (institutional births, C-section rate, insurance, anaemia, blood sugar, blood
-- MAGIC pressure).
-- MAGIC
-- MAGIC * District centre = median of its PIN-area centres; travel time = km × 1.4 ÷ 35 km/h (same as `find_care`).
-- MAGIC * `ref_nfhs_district_match` maps NFHS-5 district names to India Post districts within the same state and records
-- MAGIC   the rule used (exact, spacing, known rename, prefix for truncated names, ≤ 2 letters different).
-- MAGIC
-- MAGIC Requires notebooks 01–04.

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.ref_nfhs_district_match
COMMENT 'NFHS-5 district -> India Post district (same state): exact, space-insensitive, known rename, prefix (NFHS names are sometimes truncated), or up to 2 letters different. match_rule says which.'
AS
WITH post AS (
  SELECT DISTINCT district, state FROM workspace.datathon.silver_pincode_geo WHERE lat IS NOT NULL AND district IS NOT NULL
),
nfhs AS (
  SELECT trim(n.district_name) AS nfhs_district, trim(n.state_ut) AS nfhs_state,
         coalesce(a.state, trim(n.state_ut)) AS state,
         workspace.datathon.norm_place(n.district_name) AS nd
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.nfhs_5_district_health_indicators n
  LEFT JOIN workspace.datathon.ref_state_aliases a ON a.alias = workspace.datathon.norm_place(replace(n.state_ut, 'Maharastra', 'Maharashtra'))
),
renames(nd, pd) AS (VALUES  -- official renames / alternative names (NFHS name -> India Post name, both normalised)
  ('belgaum', 'belagavi'), ('mysore', 'mysuru'), ('gurgaon', 'gurugram'), ('bangalore', 'bengaluru urban'),
  ('bangalore rural', 'bengaluru rural'), ('koch bihar', 'cooch behar'), ('purba medinipur', 'medinipur east'),
  ('paschim medinipur', 'medinipur west'), ('dakshin dinajpur', 'south dinajpur'), ('uttar dinajpur', 'north dinajpur'),
  ('debagarh', 'deogarh'), ('firozpur', 'ferozepur'), ('muktsar', 'sri muktsar sahib'), ('shupiyan', 'shopian'),
  ('sahibzada ajit singh nagar', 's a s nagar'), ('kushinagar', 'kushi nagar'), ('hardwar', 'haridwar'),
  ('gulbarga', 'kalaburagi'), ('bijapur', 'vijayapura'), ('shimoga', 'shivamogga'), ('tumkur', 'tumakuru'),
  ('bellary', 'ballari'), ('chikmagalur', 'chikkamagaluru'), ('allahabad', 'prayagraj'), ('faizabad', 'ayodhya'),
  ('sri potti sriramulu nello', 'spsr nellore'), ('sri potti sriramulu nello', 'nellore'), ('uttar bastar kanker', 'kanker'),
  ('the dangs', 'dangs'), ('the dangs', 'dang'), ('chhota udaipur', 'chhotaudepur'), ('chhota udaipur', 'chhota udepur'),
  ('mewat', 'nuh'), ('punch', 'poonch'), ('purbi singhbhum', 'east singhbhum'), ('pashchimi singhbhum', 'west singhbhum'),
  ('khandwa east nimar', 'khandwa'), ('khandwa east nimar', 'east nimar'), ('bid', 'beed'), ('baudh', 'boudh'),
  ('subarnapur', 'sonepur'), ('subarnapur', 'subarnapur'), ('jalor', 'jalore'), ('thoothukkudi', 'thoothukudi'),
  ('thoothukkudi', 'tuticorin'), ('jyotiba phule nagar', 'amroha'), ('mahamaya nagar', 'hathras'),
  ('sant ravidas nagar bhadohi', 'bhadohi'), ('sant ravidas nagar bhadohi', 'sant ravidas nagar'), ('kanshiram nagar', 'kasganj'),
  ('garhwal', 'pauri garhwal'), ('garhwal', 'pauri'), ('koch bihar', 'coochbehar'), ('koch bihar', 'cooch bihar'),
  ('uttar dinajpur', 'uttar dinajpur'), ('dakshin dinajpur', 'dakshin dinajpur'), ('north twenty four pargana', 'north parganas'),
  ('south twenty four pargana', 'south parganas'), ('hugli', 'hooghly'), ('lower dibang valley', 'lower dibang valley'),
  ('puducherry', 'pondicherry'), ('yanam', 'yanam'), ('chandel', 'chandel')
),
cand AS (
  SELECT n.*, p.district AS post_district, p.state AS post_state,
    CASE
      WHEN workspace.datathon.norm_place(p.district) = n.nd THEN 0
      WHEN replace(workspace.datathon.norm_place(p.district), ' ', '') = replace(n.nd, ' ', '') THEN 1
      WHEN EXISTS (SELECT 1 FROM renames r WHERE r.nd = n.nd AND r.pd = workspace.datathon.norm_place(p.district)) THEN 2
      WHEN length(n.nd) >= 6 AND (workspace.datathon.norm_place(p.district) LIKE concat(n.nd, '%')
                                   OR n.nd LIKE concat(workspace.datathon.norm_place(p.district), '%')) THEN 3
      WHEN length(n.nd) >= 6 AND levenshtein(workspace.datathon.norm_place(p.district), n.nd) <= 2 THEN 4
    END AS rule_rank
  FROM nfhs n JOIN post p ON p.state = n.state
)
SELECT nfhs_district, nfhs_state, post_district, post_state,
       CASE min_rule WHEN 0 THEN 'exact' WHEN 1 THEN 'spacing' WHEN 2 THEN 'known rename' WHEN 3 THEN 'prefix' ELSE 'spelling (<= 2 letters)' END AS match_rule
FROM (
  SELECT nfhs_district, nfhs_state, min(rule_rank) AS min_rule,
         min_by(post_district, struct(rule_rank, levenshtein(workspace.datathon.norm_place(post_district), nd))) AS post_district,
         min_by(post_state, struct(rule_rank, levenshtein(workspace.datathon.norm_place(post_district), nd))) AS post_state
  FROM cand WHERE rule_rank IS NOT NULL
  GROUP BY nfhs_district, nfhs_state
)
;

-- COMMAND ----------

-- Per district x headline service: how far is the nearest confirmed or probable facility, and the nearest
-- quality facility (strong/moderate evidence and Quality >= 70), measured from the district centre
-- (median of its PIN-area centres). Travel time uses the same assumption as find_care: km x 1.4 / 35 km/h.
CREATE OR REPLACE TABLE workspace.datathon.gold_district_access
COMMENT 'District planner: travel time from each district centre to the nearest qualifying and nearest quality facility per headline service, with NFHS-5 indicators. Quality facility = strong/moderate evidence and Quality >= 70.'
AS
WITH districts AS (
  SELECT district, state, percentile(lat, 0.5) AS d_lat, percentile(lon, 0.5) AS d_lon, count(*) AS n_pin_areas
  FROM workspace.datathon.silver_pincode_geo
  WHERE lat IS NOT NULL AND district IS NOT NULL
  GROUP BY district, state
),
svc AS (
  SELECT s.service_key, s.service_label, coalesce(p.travel_budget_min, 120) AS budget
  FROM workspace.datathon.ref_services s
  LEFT JOIN workspace.datathon.ref_service_policy p USING (service_key)
  WHERE s.service_key IN ('emergency_csection', 'nicu', 'dialysis', 'trauma', 'cardiac_surgery', 'mri', 'emergency_24x7')
),
fac AS (
  SELECT g.service_key, g.facility_id, g.name, g.evidence_tier, g.quality_score, g.lat, g.lon,
         g.evidence_tier IN ('strong', 'moderate') AND g.quality_score >= 70 AS is_quality
  FROM workspace.datathon.gold_facility_services g
  JOIN svc USING (service_key)
  WHERE g.lat IS NOT NULL AND g.evidence_tier IN ('strong', 'moderate', 'probable')
    AND coalesce(g.location_validation_score, 3) > 2  -- unverified locations (score 0-2) are not used
),
pairs AS (
  SELECT d.district, d.state, d.d_lat, d.d_lon, d.n_pin_areas, f.*,
         workspace.datathon.haversine_km(d.d_lat, d.d_lon, f.lat, f.lon) AS km
  FROM districts d CROSS JOIN fac f
),
agg AS (
  SELECT p.district, p.state, p.service_key, max(p.d_lat) AS district_lat, max(p.d_lon) AS district_lon,
         max(p.n_pin_areas) AS n_pin_areas,
         min_by(named_struct('id', facility_id, 'name', name, 'tier', evidence_tier, 'q', quality_score), km) AS nearest,
         min(km) AS nearest_km,
         min_by(named_struct('id', facility_id, 'name', name, 'tier', evidence_tier, 'q', quality_score), km) FILTER (WHERE is_quality) AS nq,
         min(km) FILTER (WHERE is_quality) AS quality_km,
         count_if(km * 1.4 / 35 * 60 <= s.budget) AS n_reachable,
         max(s.budget) AS budget, max(s.service_label) AS service_label
  FROM pairs p JOIN svc s USING (service_key)
  GROUP BY p.district, p.state, p.service_key
),
nfhs AS (  -- NFHS-5 indicators, averaged when two NFHS districts map to one India Post district
  SELECT m.post_district AS district, m.post_state AS state,
         array_join(collect_set(m.nfhs_district), ' + ') AS nfhs_district, max(m.match_rule) AS nfhs_match_rule,
         round(avg(n.institutional_birth_5y_pct), 1) AS institutional_birth_pct,
         round(avg(n.institutional_birth_in_public_facility_5y_pct), 1) AS institutional_birth_public_pct,
         round(avg(n.births_delivered_by_csection_5y_pct), 1) AS csection_rate_pct,
         round(avg(n.hh_member_covered_health_insurance_pct), 1) AS health_insurance_pct,
         round(avg(n.all_w15_49_who_are_anaemic_pct), 1) AS women_anaemic_pct,
         round(avg(n.w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct), 1) AS women_high_blood_sugar_pct,
         round(avg(n.m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct), 1) AS men_high_blood_sugar_pct,
         round(avg(n.w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct), 1) AS women_high_bp_pct
  FROM workspace.datathon.ref_nfhs_district_match m
  JOIN databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.nfhs_5_district_health_indicators n
    ON trim(n.district_name) = m.nfhs_district AND trim(n.state_ut) = m.nfhs_state
  GROUP BY m.post_district, m.post_state
)
SELECT a.district, a.state, a.service_key, a.service_label, a.district_lat, a.district_lon, a.n_pin_areas,
  a.nearest.name AS nearest_facility, a.nearest.id AS nearest_facility_id, a.nearest.tier AS nearest_tier,
  a.nearest.q AS nearest_quality, round(a.nearest_km, 1) AS nearest_km, CAST(round(a.nearest_km * 1.4 / 35 * 60) AS INT) AS nearest_travel_min,
  a.nq.name AS quality_facility, a.nq.id AS quality_facility_id, a.nq.q AS quality_facility_quality,
  round(a.quality_km, 1) AS quality_km, CAST(round(a.quality_km * 1.4 / 35 * 60) AS INT) AS quality_travel_min,
  CAST(a.budget AS INT) AS travel_budget_min,
  coalesce(a.quality_km * 1.4 / 35 * 60 <= a.budget, false) AS quality_within_budget,
  CAST(a.n_reachable AS INT) AS n_reachable,
  n.nfhs_district, n.nfhs_match_rule, n.institutional_birth_pct, n.institutional_birth_public_pct, n.csection_rate_pct,
  n.health_insurance_pct, n.women_anaemic_pct, n.women_high_blood_sugar_pct, n.men_high_blood_sugar_pct, n.women_high_bp_pct
FROM agg a
LEFT JOIN nfhs n ON n.district = a.district AND n.state = a.state;

-- COMMAND ----------

-- Gap check: districts where the nearest quality facility is beyond the travel budget, per service
SELECT service_key, travel_budget_min,
       count(*) AS districts,
       count_if(NOT quality_within_budget) AS districts_without_quality_facility_in_budget,
       round(percentile(quality_travel_min, 0.5)) AS median_travel_min_to_quality_facility
FROM workspace.datathon.gold_district_access
GROUP BY ALL ORDER BY 4 DESC;
