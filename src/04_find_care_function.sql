-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 04 · `find_care`: service + location → ranked, explained recommendations
-- MAGIC
-- MAGIC Two SQL functions, callable from a notebook, the SQL editor, a dashboard, a Genie space or an app:
-- MAGIC
-- MAGIC * `resolve_location(place)` turns a PIN code, `lat,lon`, city or district into coordinates, and says how it matched.
-- MAGIC * `find_care(service, place, max_km, top_n)` returns the best facilities with a **why** (cited evidence) and a
-- MAGIC   **how** (the arithmetic behind the rank).
-- MAGIC
-- MAGIC **Ranking rule (printed verbatim in every result's `ranking_rule`):** among facilities reachable within the
-- MAGIC service's travel budget (`ref_service_policy`, e.g. 60 min for an emergency C-section, 45 min for dialysis because
-- MAGIC patients travel 3× a week, 240 min for planned cardiac surgery), **High-confidence options come first, then
-- MAGIC Medium, then Low/Probable** (a less certain facility is never ranked above a more certain one). Within each
-- MAGIC confidence group, rank by **Quality**; if two are within 10 Quality
-- MAGIC points, the closer one wins (`greedy_rank`: at each rank take the best remaining Quality, or the closest facility
-- MAGIC within 10 points of it). Facilities beyond the budget follow, in the same confidence order, labelled
-- MAGIC "farther option". Weak (unconfirmed) evidence always comes last. If nothing with strong/moderate/probable evidence is
-- MAGIC inside the search radius, the radius is doubled (up to 300 km) and the result says so.
-- MAGIC
-- MAGIC Travel time = straight-line km × 1.4 ÷ 35 km/h. Quality (0–100) is built in notebook 03 from evidence (≤50),
-- MAGIC readiness (≤30) and record reliability (≤20) minus penalties; every component is returned as its own column.
-- MAGIC
-- MAGIC Each search also returns: the **nearest qualifying facility** if it is not #1 (`is_nearest_alternative`) with a
-- MAGIC trade-off sentence and "what would change this"; a **safety line** for C-section and trauma pointing to the nearest
-- MAGIC 24×7 emergency facility; and a note when the radius was widened or nothing is within the travel budget.
-- MAGIC
-- MAGIC **Location gate:** facilities with `location_validation_score` 0–2 (location could not be verified, see
-- MAGIC `notebooks/location_validation_scoring/SCORING_CRITERIA.md`) are never returned; `n_excluded_unverified_location`
-- MAGIC says how many were left out. Facilities without a score are kept and labelled `not_scored`. The score does not
-- MAGIC change Quality or rank.
-- MAGIC Requires notebooks 01–03.

-- COMMAND ----------

CREATE OR REPLACE FUNCTION workspace.datathon.resolve_location(place STRING)
RETURNS TABLE (lat DOUBLE, lon DOUBLE, matched_as STRING, label STRING, note STRING)
COMMENT 'Resolve a PIN code, "lat,lon", city, post office / village or district name (optionally ", state" or ", district") to coordinates'
RETURN
  WITH q0 AS (SELECT trim(place) AS p),
  q AS (  -- "Raghopur, Bihar" -> name "Raghopur" + hint "Bihar" (not for "lat,lon")
    SELECT p,
           CASE WHEN p RLIKE '^\\s*-?[0-9.]+\\s*,\\s*-?[0-9.]+\\s*$' THEN p ELSE trim(split_part(p, ',', 1)) END AS name,
           CASE WHEN p RLIKE '^\\s*-?[0-9.]+\\s*,\\s*-?[0-9.]+\\s*$' OR NOT p LIKE '%,%' THEN NULL
                ELSE upper(trim(substr(p, instr(p, ',') + 1))) END AS hint
    FROM q0
  ),
  district_hit AS (  -- PIN areas of a district with that exact name
    SELECT g.* FROM q JOIN workspace.datathon.silver_pincode_geo g
      ON upper(g.district) = upper(q.name)
     AND (q.hint IS NULL OR upper(g.state) LIKE concat(q.hint, '%'))
  ),
  as_coords AS (
    SELECT try_cast(regexp_extract(p, '^\\s*(-?[0-9.]+)\\s*,\\s*(-?[0-9.]+)\\s*$', 1) AS DOUBLE) AS lat,
           try_cast(regexp_extract(p, '^\\s*(-?[0-9.]+)\\s*,\\s*(-?[0-9.]+)\\s*$', 2) AS DOUBLE) AS lon,
           'coordinates' AS matched_as, p AS label, CAST(NULL AS STRING) AS note, 1 AS pri
    FROM q WHERE p RLIKE '^\\s*-?[0-9.]+\\s*,\\s*-?[0-9.]+\\s*$'
  ),
  as_pin AS (
    SELECT g.lat, g.lon, 'pin_code', concat('PIN ', g.pincode, ' (', g.district, ', ', g.state, ')'), NULL, 2
    FROM q JOIN workspace.datathon.silver_pincode_geo g ON g.pincode = try_cast(q.p AS INT)
    WHERE q.p RLIKE '^[1-9][0-9]{5}$'
  ),
  as_city AS (  -- centre of facilities that confidently sit in a city of that name
    SELECT percentile(f.lat, 0.5), percentile(f.lon, 0.5), 'city', concat(initcap(q.name), ' (city, from ', count(*), ' facilities)'), NULL, 3
    FROM q JOIN workspace.datathon.silver_facilities f
      ON upper(trim(f.city_raw)) = upper(q.name) AND f.location_confidence = 'high'
     AND (q.hint IS NULL OR upper(f.state) LIKE concat(q.hint, '%') OR upper(f.district) LIKE concat(q.hint, '%'))
    GROUP BY q.name
    -- a district of that name wins over a small locality of the same name elsewhere ("Vaishali" in Ghaziabad)
    HAVING count(*) >= 10 OR NOT EXISTS (SELECT 1 FROM district_hit)
        OR max(upper(f.district)) = upper(q.name)
  ),
  po_cand AS (  -- post offices / villages: India Post office names, suffix (BO, SO, HO, GPO) removed
    SELECT g.pincode, g.district, g.state, g.lat, g.lon,
           CASE WHEN po RLIKE '(H\\.?O|G\\.?P\\.?O)\\.?$' THEN 0 WHEN po RLIKE 'S\\.?O\\.?$' THEN 1 ELSE 2 END AS office_rank,
           CASE WHEN po RLIKE '(H\\.?O|G\\.?P\\.?O)\\.?$' THEN 'head office' WHEN po RLIKE 'S\\.?O\\.?$' THEN 'sub office' ELSE 'branch office' END AS office_type
    FROM q
    JOIN workspace.datathon.silver_pincode_geo g ON g.lat IS NOT NULL
    LATERAL VIEW explode(filter(g.place_names, x -> x RLIKE '\\s(B\\.?O|S\\.?O|H\\.?O|G\\.?P\\.?O)\\.?$'
         AND trim(regexp_replace(x, '\\s+(B\\.?O|S\\.?O|H\\.?O|G\\.?P\\.?O)\\.?$', '')) = upper(q.name))) t AS po
    WHERE q.name NOT RLIKE '^[0-9]'
      AND (q.hint IS NULL OR upper(g.state) LIKE concat(q.hint, '%') OR upper(g.district) LIKE concat(q.hint, '%'))
      -- a name that is also a district only resolves to a post office inside that district ("Vaishali" stays the district)
      AND (NOT EXISTS (SELECT 1 FROM district_hit) OR upper(g.district) = upper(q.name))
  ),
  po_ranked AS (
    SELECT c.*, count(*) OVER (PARTITION BY c.district, c.state) AS n_in_district,
           count(*) OVER () AS n_matches,
           array_sort(collect_set(concat(c.district, ' (', c.state, ')')) OVER ()) AS all_places
    FROM po_cand c
  ),
  as_post_office AS (
    SELECT lat, lon, 'post_office',
           concat(initcap((SELECT name FROM q)), ' (post office, ', office_type, ', PIN ', CAST(pincode AS STRING), ', ', district, ', ', state, ')'),
           CASE WHEN n_matches > 1 THEN concat('"', initcap((SELECT name FROM q)), '" matched ', CAST(n_matches AS STRING),
                ' post offices; using the one in ', district, ' (', state, '). Others: ',
                array_join(slice(array_remove(all_places, concat(district, ' (', state, ')')), 1, 4), '; '),
                '. Type "', initcap((SELECT name FROM q)), ', <district>" to pick another.') END, 4
    FROM po_ranked
    ORDER BY office_rank, n_in_district DESC, pincode
    LIMIT 1
  ),
  as_district AS (
    SELECT percentile(lat, 0.5), percentile(lon, 0.5), 'district', concat(max(district), ' district, ', max(state)), NULL, 5
    FROM district_hit
    HAVING count(*) > 0
  )
  SELECT lat, lon, matched_as, label, note FROM (
    SELECT * FROM as_coords UNION ALL SELECT * FROM as_pin UNION ALL SELECT * FROM as_city
    UNION ALL SELECT * FROM as_post_office UNION ALL SELECT * FROM as_district
  ) ORDER BY pri LIMIT 1;

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.ref_service_policy
COMMENT 'Travel-time budget per service: how long a patient can reasonably travel for it. Used by find_care to decide which facilities are "reachable".'
AS SELECT * FROM VALUES
  ('emergency_csection', 60,  'emergency', 'obstetric emergencies need surgery within about an hour'),
  ('trauma',             60,  'emergency', 'the "golden hour" for serious injuries'),
  ('emergency_24x7',     45,  'emergency', 'an emergency department should be close'),
  ('icu',                60,  'emergency', 'critically ill patients should not travel far'),
  ('cath_lab',           90,  'emergency', 'heart attacks need angioplasty within about 90 minutes'),
  ('nicu',               90,  'urgent',    'sick newborns need intensive care quickly, but often after stabilisation'),
  ('high_risk_delivery', 90,  'urgent',    'planned in advance, but labour can start suddenly'),
  ('blood_bank',         60,  'urgent',    'blood is often needed urgently'),
  ('burn_care',          120, 'urgent',    'serious burns need a burn unit within hours'),
  ('neurosurgery',       120, 'urgent',    'head injuries and strokes are time-critical; elective cases are not'),
  ('ct_scan',            90,  'urgent',    'often needed the same day'),
  ('dialysis',           45,  'recurring', 'patients travel about 3 times a week, so the trip must be short'),
  ('mri',                180, 'planned',   'usually scheduled; a longer trip is acceptable'),
  ('cardiac_surgery',    240, 'planned',   'usually planned; quality matters more than distance'),
  ('oncology',           240, 'planned',   'planned treatment; quality matters more than distance'),
  ('orthopedic_surgery', 180, 'planned',   'usually planned'),
  ('cataract',           180, 'planned',   'planned day surgery')
AS t(service_key, travel_budget_min, urgency, rationale);

-- COMMAND ----------

-- Human verifications: an overlay written by the app (Confirm / Reject on a card). Never merged into silver or gold;
-- find_care reads the latest row per (facility, service, check). check_key = 'service' means the service itself.
CREATE TABLE IF NOT EXISTS workspace.datathon.verifications (
  facility_id STRING, service_key STRING, check_key STRING,
  status STRING COMMENT 'confirmed | rejected',
  reviewer STRING COMMENT 'from the Databricks Apps X-Forwarded-Email header',
  ts TIMESTAMP, note STRING, evidence_url STRING)
COMMENT 'Human verifications overlaid by find_care. Latest row per facility/service/check wins. Never merged into silver/gold.';

-- COMMAND ----------

CREATE OR REPLACE VIEW workspace.datathon.verifications_latest
COMMENT 'Latest verification per facility, service and check, collected per facility x service (read by find_care)'
AS
SELECT facility_id, service_key, collect_list(v) AS verifications,
       max(CASE WHEN check_key = 'service' THEN v.status END) AS verified_service
FROM (
  SELECT facility_id, service_key, check_key,
         max_by(named_struct('check_key', check_key, 'status', status, 'reviewer', reviewer, 'ts', ts,
                             'note', note, 'evidence_url', evidence_url), ts) AS v
  FROM workspace.datathon.verifications
  GROUP BY facility_id, service_key, check_key
)
GROUP BY facility_id, service_key;

-- COMMAND ----------

-- Quality-first ordering with a 10-point distance rule, done greedily: at each position take the best remaining Quality
-- (within the best remaining band), then pick the CLOSEST facility whose Quality is within 10 points of it.
-- Returns the first k facility ids in rank order, each with the best remaining Quality (qstar) when it was picked.
-- (`transform(array(v), name -> ...)` just names an intermediate value; the state carries the remaining list so each
-- step is one pass.) find_care orders anything after position k by band, Quality, distance.
CREATE OR REPLACE FUNCTION workspace.datathon.greedy_rank(a ARRAY<STRUCT<id: STRING, q: INT, km: DOUBLE, band: INT>>, k INT)
RETURNS ARRAY<STRUCT<id: STRING, qstar: INT>>
RETURN aggregate(
  sequence(1, greatest(1, least(size(a), k))),
  named_struct('picked', CAST(array() AS ARRAY<STRUCT<id: STRING, qstar: INT>>), 'rem', a),
  (st, i) -> element_at(transform(array(array_min(transform(st.rem, x -> x.band))), b ->
    element_at(transform(array(array_max(transform(filter(st.rem, x -> x.band = b), x -> x.q))), qs ->
      element_at(transform(array(get(array_sort(filter(st.rem, x -> x.band = b AND x.q >= qs - 10),
          (l, r) -> CASE WHEN l.km < r.km THEN -1 WHEN l.km > r.km THEN 1 WHEN l.q > r.q THEN -1 WHEN l.q < r.q THEN 1 ELSE 0 END), 0)), pk ->
        CASE WHEN pk IS NULL THEN st
             ELSE named_struct('picked', array_append(st.picked, named_struct('id', pk.id, 'qstar', qs)),
                               'rem', filter(st.rem, x -> x.id <> pk.id)) END), 1)), 1)), 1),
  st -> st.picked);

-- COMMAND ----------

CREATE OR REPLACE FUNCTION workspace.datathon.find_care(
  service STRING,
  place   STRING,
  max_km  DOUBLE DEFAULT 75,
  top_n   INT    DEFAULT 5,
  operator_filter STRING DEFAULT NULL)  -- 'public' = government facilities only; NULL = all
RETURNS TABLE (
  rank INT, facility_name STRING, distance_km DOUBLE, evidence_tier STRING, trust_score INT, match_score DOUBLE,
  why STRING, how STRING, caveats ARRAY<STRING>,
  procedures_cited ARRAY<STRING>, capabilities_cited ARRAY<STRING>, equipment_cited ARRAY<STRING>, description_cited STRING,
  source_urls ARRAY<STRING>, district STRING, state STRING, location_confidence STRING,
  phone STRING, website STRING, facility_id STRING, searched_service STRING, searched_from STRING,
  -- added for the app: map pins, contact card, extra context
  lat DOUBLE, lon DOUBLE, address STRING, city STRING, pincode INT, email STRING, facebook STRING,
  facility_type STRING, operator_type STRING, specialties_cited ARRAY<STRING>,
  number_doctors INT, capacity_beds INT, n_source_domains INT, distance_score DOUBLE,
  origin_lat DOUBLE, origin_lon DOUBLE, origin_matched_as STRING,
  -- added for interpretability: score components as numbers, the matching rule, rejected mentions
  pts_evidence INT, pts_sources INT, pts_scale INT, pts_location INT,
  pen_merged INT, pen_facility_type INT, pen_negated INT, pen_numbers INT,
  negated_or_referral_mentions ARRAY<STRING>, match_pattern STRING, max_km_used DOUBLE, n_candidates INT,
  -- Phase 3: quality-first ranking (match_score above now equals quality_score)
  quality_score INT, q_evidence INT, q_readiness INT, q_reliability INT, q_penalties INT,
  q_facility_type INT, q_beds INT, q_support INT, q_sources INT, q_location INT, q_coherence INT,
  support_found ARRAY<STRING>, support_considered ARRAY<STRING>,
  travel_min INT, travel_budget_min INT, urgency STRING, within_budget BOOLEAN, ranking_band STRING, points_below_best INT,
  is_nearest_alternative BOOLEAN, tradeoff_note STRING, counterfactual_note STRING,
  search_note STRING, safety_note STRING, ranking_rule STRING, travel_assumption STRING,
  evidence_method STRING, checks_found INT, checks_total INT,
  evidence_checks ARRAY<STRUCT<check_key: STRING, check_label: STRING, status: STRING, points: INT, max_points: INT,
                               cited_text: STRING, field: STRING, claim_type: STRING>>,
  claims_cited ARRAY<STRUCT<text: STRING, field: STRING, claim_type: STRING>>,
  is_better_farther BOOLEAN,
  -- Phase 4: record coherence (identity) and the confidence cap
  record_coherence_score INT, coh_coords_pin INT, coh_city INT, coh_state INT, coh_located_in INT,
  coh_other_facility INT, coh_duplicate INT, identity_conflict BOOLEAN, identity_conflict_reason STRING,
  possible_duplicate_names ARRAY<STRING>,
  -- Phase 5: one concrete fact to confirm by phone
  call_to_confirm STRING,
  -- Phase 6: human verification overlay
  verifications ARRAY<STRUCT<check_key: STRING, status: STRING, reviewer: STRING, ts: TIMESTAMP, note: STRING, evidence_url: STRING>>,
  verified_service STRING, q_verified INT,
  -- "How solid is this pick?" (#1 only): the ranking re-run with one doubt at a time.
  --   kind 'data': doubts about the records (decide Solid vs Shaky); kind 'situation': the patient's circumstances.
  --   still_first NULL = no facility passes that check at all.
  double_checks ARRAY<STRUCT<kind: STRING, label: STRING, still_first: BOOLEAN, winner: STRING>>,
  pick_strength STRING, pick_strength_note STRING,
  -- other cards: "Would be your best option if you can travel up to 2 hours."
  tip_note STRING,
  -- confidence label (High / Medium / Low / Probable / Unconfirmed); the ranking orders by it before Quality
  confidence_label STRING,
  -- location validation (notebooks/location_validation_scoring): shown on the card; scores <= 2 are excluded
  location_validation_status STRING, location_validation_score INT, location_validation_label STRING,
  location_checks ARRAY<STRUCT<check_key: STRING, check_label: STRING, kind: STRING, status: STRING, why: STRING>>,
  n_excluded_unverified_location INT)
COMMENT 'Ranked facilities for a service near a place: quality-first within a travel-time budget, with cited evidence (why), score arithmetic (how), trade-offs and uncertainty'
RETURN
  WITH loc AS (SELECT * FROM workspace.datathon.resolve_location(place)),
  svc AS (
    SELECT s.service_key, s.service_label, s.text_regex,
           coalesce(p.travel_budget_min, 120) AS budget, coalesce(p.urgency, 'unspecified') AS urgency,
           coalesce(p.rationale, 'default budget') AS rationale
    FROM workspace.datathon.ref_services s
    LEFT JOIN workspace.datathon.ref_service_policy p USING (service_key)
    WHERE s.service_key = lower(trim(service)) OR lower(s.service_label) = lower(trim(service))
       OR array_contains(s.aliases, lower(trim(service)))
    LIMIT 1
  ),
  base AS (  -- every facility with evidence for the service within 300 km
    SELECT g.*, svc.service_label AS svc_label, svc.text_regex AS match_pattern, svc.budget, svc.urgency, svc.rationale,
           loc.label AS loc_label, loc.lat AS origin_lat, loc.lon AS origin_lon, loc.matched_as AS origin_matched_as,
           workspace.datathon.haversine_km(loc.lat, loc.lon, g.lat, g.lon) AS km,
           workspace.datathon.haversine_km(loc.lat, loc.lon, coalesce(g.alt_lat, g.lat), coalesce(g.alt_lon, g.lon)) AS km_alt,
           coalesce(va.verifications, array()) AS verifications, va.verified_service,
           -- checklist with human verifications applied: confirmed -> found (full points), rejected -> contradicted
           transform(g.evidence_checks, c -> CASE
             WHEN get(filter(va.verifications, x -> x.check_key = c.check_key), 0).status = 'confirmed' THEN
               named_struct('check_key', c.check_key, 'check_label', c.check_label, 'status', 'found', 'points', c.max_points,
                            'max_points', c.max_points,
                            'cited_text', concat('Confirmed by ', get(filter(va.verifications, x -> x.check_key = c.check_key), 0).reviewer,
                                                 ' on ', date_format(get(filter(va.verifications, x -> x.check_key = c.check_key), 0).ts, 'd MMM yyyy'),
                                                 coalesce(concat(': ', get(filter(va.verifications, x -> x.check_key = c.check_key), 0).note), '')),
                            'field', 'verification', 'claim_type', 'verified')
             WHEN get(filter(va.verifications, x -> x.check_key = c.check_key), 0).status = 'rejected' THEN
               named_struct('check_key', c.check_key, 'check_label', c.check_label, 'status', 'contradicted', 'points', 0,
                            'max_points', c.max_points,
                            'cited_text', concat('Reported not available by ', get(filter(va.verifications, x -> x.check_key = c.check_key), 0).reviewer,
                                                 ' on ', date_format(get(filter(va.verifications, x -> x.check_key = c.check_key), 0).ts, 'd MMM yyyy'),
                                                 coalesce(concat(': ', get(filter(va.verifications, x -> x.check_key = c.check_key), 0).note), '')),
                            'field', 'verification', 'claim_type', 'verified')
             ELSE c END) AS checks_v
    FROM workspace.datathon.gold_facility_services g
    JOIN svc USING (service_key)
    CROSS JOIN loc
    LEFT JOIN workspace.datathon.verifications_latest va ON va.facility_id = g.facility_id AND va.service_key = g.service_key
    WHERE g.lat IS NOT NULL AND workspace.datathon.haversine_km(loc.lat, loc.lon, g.lat, g.lon) <= greatest(300, max_km)
      AND (operator_filter IS NULL OR g.operator_type = lower(operator_filter))
      -- location validation gate: a facility whose location could not be verified (score 0-2) is never recommended;
      -- one with no score yet stays in, labelled 'not_scored'
      AND coalesce(g.location_validation_score, 3) > 2
  ),
  vdelta AS (  -- Quality points that reviewer verifications add or remove (0 when there is no checklist)
    -- Services ranked by keyword rules have no checklist (evidence_checks IS NULL). Every term must be coalesced:
    -- least()/greatest() skip NULLs, so a NULL here once turned every such facility's Quality into exactly 100.
    SELECT b.*,
           CAST(round((coalesce(aggregate(b.checks_v, 0, (acc, c) -> acc + c.points), 0)
                     - coalesce(aggregate(b.evidence_checks, 0, (acc, c) -> acc + c.points), 0)) * 50.0 / 60) AS INT) AS q_delta
    FROM base b
  ),
  allc AS (  -- verified checks change the evidence points (scaled to the 50-point Quality evidence part)
    SELECT b.* EXCEPT (evidence_checks, quality_score, q_evidence, checks_found, checks_v, q_delta),
           b.checks_v AS evidence_checks,
           CAST(size(filter(b.checks_v, c -> c.status = 'found')) AS INT) AS checks_found,
           b.q_delta AS q_verified,
           least(50, greatest(0, b.q_evidence + b.q_delta)) AS q_evidence,
           greatest(0, least(100, b.quality_score + b.q_delta)) AS quality_score,
           -- a reviewer saying the service itself is not available removes it from the qualifying list;
           -- a reviewer confirming it makes even weak evidence qualify
           CASE WHEN b.verified_service = 'rejected' THEN false
                WHEN b.verified_service = 'confirmed' THEN true
                ELSE b.evidence_tier IN ('strong', 'moderate', 'probable') END AS qualifies,
           -- Confidence label (single source of truth; the app shows it as the card badge). A reviewer's phone
           -- confirmation counts as High; an identity conflict caps it at Medium.
           CASE WHEN b.verified_service = 'confirmed' THEN 'High'
                WHEN b.evidence_tier = 'weak' THEN 'Unconfirmed'
                WHEN b.evidence_tier = 'probable' THEN 'Probable'
                WHEN b.trust_score >= 70 AND NOT coalesce(b.identity_conflict, false) THEN 'High'
                WHEN b.trust_score >= 45 THEN 'Medium'
                ELSE 'Low' END AS confidence_label
    FROM vdelta b
  ),
  radius AS (  -- auto-radius: double the search radius (up to 300 km) until a qualifying facility is inside it
    SELECT min(km) FILTER (WHERE qualifies) AS nearest_q_km,
           CASE WHEN min(km) FILTER (WHERE qualifies) IS NULL OR min(km) FILTER (WHERE qualifies) <= max_km THEN max_km
                WHEN min(km) FILTER (WHERE qualifies) > greatest(300, max_km) THEN max_km
                ELSE least(greatest(300, max_km),
                           max_km * pow(2, ceil(log2(min(km) FILTER (WHERE qualifies) / max_km)))) END AS eff_km
    FROM allc
  ),
  cand AS (
    SELECT a.*, r.eff_km, r.nearest_q_km,
           CAST(round(a.km * 1.4 / 35 * 60) AS INT) AS travel,
           a.km * 1.4 / 35 * 60 <= a.budget AS in_budget,
           CASE WHEN a.qualifies AND a.km * 1.4 / 35 * 60 <= a.budget THEN 1 WHEN a.qualifies THEN 2 ELSE 3 END AS band,
           -- confidence group: 1 High, 2 Medium, 3 Low or Probable (we never put a less certain facility above a more
           -- certain one in the same reachability band, whatever its Quality)
           CASE a.confidence_label WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END AS conf_group,
           -- ordering band used by the ranking: reachable High < reachable Medium < reachable Low/Probable
           -- < farther High < farther Medium < farther Low/Probable < unconfirmed
           CASE WHEN NOT a.qualifies THEN 9
                ELSE CASE WHEN a.km * 1.4 / 35 * 60 <= a.budget THEN 0 ELSE 3 END
                     + CASE a.confidence_label WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END END AS rank_band
    FROM allc a CROSS JOIN radius r
    WHERE a.km <= r.eff_km
  ),
  excl AS (  -- facilities with evidence for this service inside the search radius but an unverified location (score 0-2)
    SELECT CAST(count(DISTINCT g.facility_id) AS INT) AS n
    FROM workspace.datathon.gold_facility_services g
    JOIN svc USING (service_key)
    CROSS JOIN loc CROSS JOIN radius r
    WHERE g.location_validation_score <= 2 AND g.lat IS NOT NULL
      AND workspace.datathon.haversine_km(loc.lat, loc.lon, g.lat, g.lon) <= r.eff_km
      AND (operator_filter IS NULL OR g.operator_type = lower(operator_filter))
  ),
  greedy AS (
    SELECT workspace.datathon.greedy_rank(collect_list(named_struct(
             'id', facility_id, 'q', CAST(quality_score AS INT), 'km', km, 'band', rank_band)), 100) AS ord
    FROM cand WHERE band < 3
  ),
  scen0 AS (  -- double-checks: who would be #1 if we re-ran the ranking with one doubt at a time (no random sampling)
    SELECT map_from_entries(collect_list(struct(facility_id, name))) AS names,
      CAST(max(budget) * 2 AS INT) AS budget2,
      get(workspace.datathon.greedy_rank(
          collect_list(named_struct('id', facility_id, 'q', CAST(quality_score AS INT), 'km', km, 'band', rank_band))
            FILTER (WHERE evidence_tier = 'strong' AND qualifies), 1), 0).id AS w_strong,
      get(workspace.datathon.greedy_rank(
          collect_list(named_struct('id', facility_id, 'q', CAST(quality_score AS INT), 'km', km, 'band', rank_band))
            FILTER (WHERE band < 3 AND n_source_domains > 1), 1), 0).id AS w_multi,
      get(workspace.datathon.greedy_rank(
          collect_list(named_struct('id', facility_id, 'q', CAST(quality_score AS INT), 'km', km_alt,
                                    'band', CASE WHEN km_alt * 1.4 / 35 * 60 <= budget THEN 0 ELSE 3 END + conf_group))
            FILTER (WHERE qualifies), 1), 0).id AS w_alt,
      get(workspace.datathon.greedy_rank(
          collect_list(named_struct('id', facility_id, 'q', CAST(quality_score AS INT), 'km', km,
                                    'band', CASE WHEN km * 1.4 / 35 * 60 <= 2 * budget THEN 0 ELSE 3 END + conf_group))
            FILTER (WHERE qualifies), 1), 0).id AS w_budget,
      get(workspace.datathon.greedy_rank(
          collect_list(named_struct('id', facility_id, 'q', CAST(quality_score - q_readiness AS INT), 'km', km, 'band', rank_band))
            FILTER (WHERE band < 3), 1), 0).id AS w_noready
    FROM cand
  ),
  scen AS (
    SELECT names, array(
      -- doubts about the data: these decide whether #1 is a Solid or a Shaky pick
      named_struct('kind', 'data', 'key', 'strong', 'label', 'Only facilities with detailed evidence count', 'winner', w_strong),
      named_struct('kind', 'data', 'key', 'multi', 'label', 'Facilities found on just one website are ignored', 'winner', w_multi),
      named_struct('kind', 'data', 'key', 'alt', 'label', 'Fuzzy addresses are moved to their other recorded location', 'winner', w_alt),
      -- the patient's situation: shown as tips, never counted against #1
      named_struct('kind', 'situation', 'key', 'budget',
                   'label', concat('You can travel up to ', CASE WHEN budget2 % 60 = 0 THEN concat(CAST(budget2 DIV 60 AS STRING), ' hours')
                                                                 ELSE concat(CAST(budget2 AS STRING), ' min') END),
                   'winner', w_budget),
      named_struct('kind', 'situation', 'key', 'noready',
                   'label', 'Only the evidence matters, not hospital size or backup services like ICU and blood bank',
                   'winner', w_noready)) AS scenarios
    FROM scen0
  ),
  ranked AS (
    SELECT c.*,
      CAST(CASE WHEN array_position(transform(g.ord, o -> o.id), c.facility_id) > 0
                THEN array_position(transform(g.ord, o -> o.id), c.facility_id)
                ELSE coalesce(size(g.ord), 0) + row_number() OVER (
                       PARTITION BY array_position(transform(g.ord, o -> o.id), c.facility_id) > 0
                       ORDER BY c.rank_band, c.quality_score DESC, c.km) END AS INT) AS rnk,
      get(filter(g.ord, o -> o.id = c.facility_id), 0).qstar AS qstar,
      CAST(count(*) OVER () AS INT) AS n_cand,
      min_by(c.facility_id, c.km) OVER (PARTITION BY c.qualifies) AS nearest_id_in_group
    FROM cand c CROSS JOIN greedy g
  ),
  top1 AS (SELECT * FROM ranked WHERE rnk = 1),
  nearest AS (SELECT * FROM ranked WHERE qualifies AND facility_id = nearest_id_in_group),
  er AS (  -- nearest 24x7 emergency facility, for the safety line on emergency services
    SELECT min_by(named_struct('name', e.name, 'km', workspace.datathon.haversine_km(loc.lat, loc.lon, e.lat, e.lon),
                               'phone', e.official_phone),
                  workspace.datathon.haversine_km(loc.lat, loc.lon, e.lat, e.lon)) AS f
    FROM workspace.datathon.gold_facility_services e CROSS JOIN loc
    WHERE e.service_key = 'emergency_24x7' AND e.evidence_tier IN ('strong', 'moderate') AND e.lat IS NOT NULL
      -- only general hospitals with a trustworthy location: not IVF / eye / dental / diagnostic centres
      AND e.facility_type = 'hospital' AND e.location_confidence IN ('high', 'medium') AND e.pen_merged = 0
      AND coalesce(e.location_validation_score, 3) > 2
      AND NOT lower(e.name) RLIKE 'ivf|fertility|\\beye\\b|netra|nethra|vision|dental|diagnostic|imaging|\\bscan|\\blab|skin|derma|cosmetic|physio|rehab|ayurved|homoeo|homeo|psychiatr|de-?addiction'
      AND workspace.datathon.haversine_km(loc.lat, loc.lon, e.lat, e.lon) <= 100
  ),
  notes AS (
    SELECT
      concat_ws(' ',
        (SELECT note FROM loc),
        CASE WHEN r.eff_km > max_km THEN concat('Nothing with confirmed or probable evidence within ', CAST(CAST(max_km AS INT) AS STRING),
                                                ' km, so the search was widened to ', CAST(CAST(r.eff_km AS INT) AS STRING), ' km.') END,
        CASE WHEN r.nearest_q_km IS NULL THEN 'No facility with confirmed or probable evidence within 300 km; every result is unconfirmed.'
             WHEN (SELECT count(*) FROM ranked WHERE band = 1) = 0 THEN
               concat('Nothing confirmed is within the ', CAST((SELECT max(budget) FROM svc) AS STRING), '-minute travel budget for this service. ',
                      'Nearest confirmed option is ', CAST(round(r.nearest_q_km) AS INT), ' km (about ',
                      CAST(round(r.nearest_q_km * 1.4 / 35 * 60) AS INT), ' min) away.') END,
        CASE WHEN (SELECT first(confidence_label) FROM top1) IN ('Medium', 'Low', 'Probable') THEN
          concat('No high-confidence option was found for this service, so even #1 is ',
                 lower((SELECT first(confidence_label) FROM top1)), ' confidence. Call ahead before travelling.') END) AS search_note
    FROM radius r
  ),
  enriched AS (
    SELECT rk.*,
      (rk.qualifies AND rk.facility_id = rk.nearest_id_in_group AND rk.rnk > 1) AS is_near_alt,
      -- the best facility beyond the travel budget, if it is clearly better (10+ Quality points) than a reachable #1
      (rk.band = 2 AND t.band = 1 AND rk.quality_score >= t.quality_score + 10
       AND rk.facility_id = max_by(rk.facility_id, struct(rk.quality_score, -rk.km)) OVER (PARTITION BY rk.band)) AS is_better_farther,
      t.name AS top_name, t.quality_score AS top_q, t.travel AS top_travel, t.checks_found AS top_cf, t.checks_total AS top_ct,
      t.evidence_tier AS top_tier, t.support_found AS top_support, t.conf_group AS top_conf_group,
      t.confidence_label AS top_conf,
      transform(sc.scenarios, x -> named_struct('kind', x.kind, 'label', x.label,
                                                'still_first', x.winner = rk.facility_id,
                                                'winner', element_at(sc.names, x.winner))) AS double_checks,
      -- data checks that put a different facility first (a check nobody passes doesn't count against #1)
      filter(sc.scenarios, x -> x.kind = 'data' AND x.winner IS NOT NULL AND x.winner <> rk.facility_id) AS data_lost,
      filter(sc.scenarios, x -> x.kind = 'situation' AND x.winner = rk.facility_id) AS situation_won,
      sc.names AS names
    FROM ranked rk CROSS JOIN top1 t CROSS JOIN scen sc
  )
  SELECT
    rnk,
    name,
    round(km, 1),
    evidence_tier,
    CAST(trust_score AS INT),
    CAST(quality_score AS DOUBLE),
    concat(
      CASE WHEN verified_service = 'confirmed' THEN 'CONFIRMED BY A REVIEWER: ' WHEN verified_service = 'rejected' THEN 'REPORTED NOT AVAILABLE BY A REVIEWER: ' ELSE '' END,
      CASE band WHEN 2 THEN 'FARTHER OPTION (beyond the travel budget): ' WHEN 3 THEN 'UNCONFIRMED: ' ELSE '' END,
      CASE WHEN evidence_tier = 'probable' THEN 'PROBABLE (call to confirm): ' ELSE '' END,
      name, ' is ', CAST(round(km, 1) AS STRING), ' km (about ', CAST(travel AS STRING), ' min) from ', loc_label, '. ',
      initcap(evidence_tier), ' evidence for ', svc_label, ': ', evidence_summary, '. ',
      'Location: ', location_note) AS why,
    concat(
      'Quality ', CAST(quality_score AS STRING), ' = evidence ', CAST(q_evidence AS STRING), '/50',
      ' + readiness ', CAST(q_readiness AS STRING), '/30 (facility type ', CAST(q_facility_type AS STRING), '/10, beds ',
      CAST(q_beds AS STRING), '/10, supporting services ', CAST(q_support AS STRING), '/10',
      CASE WHEN size(support_found) > 0 THEN concat(': ', array_join(support_found, ', ')) ELSE '' END, ')',
      ' + reliability ', CAST(q_reliability AS STRING), '/20 (sources ', CAST(q_sources AS STRING), '/8, location ',
      CAST(q_location AS STRING), '/6, coherence ', CAST(q_coherence AS STRING), '/6 from a record coherence score of ',
      CAST(record_coherence_score AS STRING), '/100)',
      CASE WHEN q_penalties < 0 THEN concat(' ', CAST(q_penalties AS STRING), ' penalties') ELSE '' END, '. ',
      CASE band
        WHEN 3 THEN 'Ranked after all confirmed/probable options because its evidence is weak.'
        ELSE concat('Travel about ', CAST(travel AS STRING), ' min vs a ', CAST(budget AS STRING), '-min budget (',
                    CASE WHEN in_budget THEN 'reachable' ELSE 'farther option' END, '). Confidence: ', confidence_label,
                    CASE WHEN conf_group > top_conf_group AND band = 1
                         THEN concat(', so it comes after every reachable ', CASE conf_group WHEN 2 THEN 'High' ELSE 'High or Medium' END,
                                     '-confidence option')
                         ELSE '' END,
                    '. At rank ', CAST(rnk AS STRING),
                    ' the best remaining Quality in its confidence group was ', CAST(qstar AS STRING),
                    CASE WHEN quality_score = qstar THEN '; this is that facility'
                         ELSE concat('; this facility is ', CAST(qstar - quality_score AS STRING), ' points below it but closer, and within 10 points the closer one wins') END,
                    '.') END) AS how,
    concat(caveats, array_compact(array(
      CASE WHEN verified_service = 'rejected' THEN concat('A reviewer reported that ', svc_label, ' is not available here (',
        get(filter(verifications, x -> x.check_key = 'service'), 0).reviewer, ', ',
        date_format(get(filter(verifications, x -> x.check_key = 'service'), 0).ts, 'd MMM yyyy'), ').') END,
      CASE WHEN q_verified <> 0 THEN concat('Reviewer verifications changed the evidence points by ', CAST(q_verified AS STRING), ' Quality points.') END))),
    procedures_cited, capabilities_cited, equipment_cited, description_cited,
    source_urls, district, state, location_confidence,
    official_phone, official_website, facility_id, svc_label, loc_label,
    lat, lon, address_text, city_raw, pincode, email, facebook_link,
    facility_type, operator_type, specialties_cited,
    CAST(number_doctors AS INT), CAST(capacity_beds AS INT), n_source_domains,
    round(100 * greatest(0, 1 - km / eff_km)),
    origin_lat, origin_lon, origin_matched_as,
    CAST(pts_evidence AS INT), CAST(pts_sources AS INT), CAST(pts_scale AS INT), CAST(pts_location AS INT),
    CAST(pen_merged AS INT), CAST(pen_facility_type AS INT), CAST(pen_negated AS INT), CAST(pen_numbers AS INT),
    negated_or_referral_mentions, match_pattern, eff_km, n_cand,
    -- Phase 3
    CAST(quality_score AS INT), q_evidence, q_readiness, q_reliability, CAST(q_penalties AS INT),
    q_facility_type, q_beds, q_support, q_sources, q_location, q_coherence,
    support_found, support_considered,
    travel, CAST(budget AS INT), urgency, in_budget,
    CASE band WHEN 1 THEN 'reachable' WHEN 2 THEN 'farther option' ELSE 'unconfirmed' END,
    CASE WHEN band < 3 THEN CAST(qstar - quality_score AS INT) END,
    is_near_alt,
    CASE WHEN is_near_alt THEN concat(
      name, ' is ', CAST(greatest(0, top_travel - travel) AS STRING), ' min closer but has ',
      CASE WHEN checks_total IS NOT NULL THEN concat(CAST(checks_found AS STRING), '/', CAST(checks_total AS STRING), ' evidence items')
           ELSE concat(evidence_tier, ' evidence') END,
      ' for ', svc_label, ' (Quality ', CAST(quality_score AS STRING), '); ', top_name, ' has ',
      CASE WHEN top_ct IS NOT NULL THEN concat(CAST(top_cf AS STRING), '/', CAST(top_ct AS STRING), ' evidence items')
           ELSE concat(top_tier, ' evidence') END,
      CASE WHEN size(array_except(top_support, support_found)) > 0
           THEN concat(' plus ', array_join(array_except(top_support, support_found), ', ')) ELSE '' END,
      ' (Quality ', CAST(top_q AS STRING), ').')
      WHEN is_better_farther THEN concat(
      name, ' has higher Quality (', CAST(quality_score AS STRING), ' vs ', CAST(top_q AS STRING), ' for ', top_name,
      ') but is about ', CAST(travel AS STRING), ' min away, beyond the ', CAST(budget AS STRING), '-minute travel budget for ',
      svc_label, ' (', rationale, '). It is listed as a farther option; consider it if the patient can travel.') END,
    CASE WHEN is_near_alt AND size(filter(evidence_checks, c -> c.status <> 'found')) > 0 THEN
      concat('What would change this: confirming "',
             get(array_sort(filter(evidence_checks, c -> c.status <> 'found'), (a, b) -> b.max_points - a.max_points), 0).check_label,
             '" at ', name, ' would add ',
             CAST(CAST(round(get(array_sort(filter(evidence_checks, c -> c.status <> 'found'), (a, b) -> b.max_points - a.max_points), 0).max_points * 50.0 / 60) AS INT) AS STRING),
             ' Quality points; the gap to #1 is ', CAST(top_q - quality_score AS STRING), ' points',
             CASE WHEN conf_group > top_conf_group
                  THEN concat(', but it is ', confidence_label, ' confidence while #1 is ', top_conf,
                              ', so more points alone would not move it to first.')
                  WHEN quality_score + CAST(round(get(array_sort(filter(evidence_checks, c -> c.status <> 'found'), (a, b) -> b.max_points - a.max_points), 0).max_points * 50.0 / 60) AS INT) >= top_q - 10
                  THEN ', so it would then be within 10 points and, being closer, would rank first.'
                  ELSE ', so that alone would not be enough (a closer facility wins only within 10 points).' END) END,
    (SELECT search_note FROM notes),
    CASE WHEN urgency = 'emergency' AND service_key IN ('emergency_csection', 'trauma') AND (SELECT f FROM er) IS NOT NULL THEN
      concat('If the patient is unstable, go to the nearest 24×7 emergency facility first: ', (SELECT f.name FROM er),
             ' (', CAST(round((SELECT f.km FROM er), 1) AS STRING), ' km',
             CASE WHEN (SELECT f.phone FROM er) IS NOT NULL THEN concat(', ', (SELECT f.phone FROM er)) ELSE '' END, ').') END,
    concat('Among facilities reachable within ', CAST(budget AS STRING), ' minutes (', urgency, ': ', rationale,
           '), High-confidence options come first, then Medium, then Low or Probable: we never rank a less certain ',
           'facility above a more certain one. Within each confidence group we rank by Quality, and if two are within ',
           '10 Quality points the closer one wins (at each rank we take the best remaining Quality, or the closest ',
           'facility within 10 points of it). ',
           'Facilities beyond the budget come after all reachable ones, labelled "farther option". ',
           'Weak (unconfirmed) evidence always comes last. If nothing qualifies within the search radius, it is doubled (up to 300 km).'),
    'Travel time is estimated as straight-line km × 1.4 (road detour) ÷ 35 km/h average speed.',
    evidence_method, CAST(checks_found AS INT), CAST(checks_total AS INT),
    evidence_checks, claims_cited, is_better_farther,
    CAST(record_coherence_score AS INT), CAST(coh_coords_pin AS INT), CAST(coh_city AS INT), CAST(coh_state AS INT),
    CAST(coh_located_in AS INT), CAST(coh_other_facility AS INT), CAST(coh_duplicate AS INT),
    identity_conflict, nullif(identity_conflict_reason, ''), possible_duplicate_names,
    -- the single most useful thing to ask: the missing evidence item worth the most points, else whether it exists at all
    CASE
      WHEN evidence_tier = 'weak' THEN concat('Ask whether they offer ', svc_label, ' at all: the record only implies it.')
      WHEN evidence_tier = 'probable' THEN concat('Ask whether they perform ', svc_label,
                                                  ': the record lists the department but never names the procedure.')
      WHEN size(filter(evidence_checks, c -> c.status <> 'found')) > 0 THEN
        concat('Ask about "', get(array_sort(filter(evidence_checks, c -> c.status <> 'found'),
                                                   (a, b) -> b.max_points - a.max_points), 0).check_label,
               '": the record does not mention it',
               CASE WHEN get(array_sort(filter(evidence_checks, c -> c.status <> 'found'), (a, b) -> b.max_points - a.max_points), 0).status = 'contradicted'
                    THEN ' (or says it is not available)' ELSE '' END, '.')
      WHEN urgency = 'emergency' THEN concat('Ask whether they can handle ', svc_label, ' right now.')
      ELSE concat('Ask whether ', svc_label, ' is available on the day you plan to go, and the cost.')
    END,
    verifications, verified_service, q_verified,
    CASE WHEN rnk = 1 THEN double_checks END,
    CASE WHEN rnk = 1 THEN CASE WHEN size(data_lost) = 0 THEN 'Solid' ELSE 'Shaky' END END,
    CASE
      WHEN rnk <> 1 THEN NULL
      WHEN size(data_lost) = 0 THEN 'Solid pick: stays #1 even if we doubt the data.'
      ELSE concat('Shaky pick: ',
        CASE get(data_lost, 0).key
          WHEN 'strong' THEN 'if we only count detailed evidence'
          WHEN 'multi' THEN CASE WHEN coalesce(n_source_domains, 0) <= 1 THEN 'if its one website is wrong'
                                 ELSE 'if we ignore facilities found on just one website' END
          ELSE CASE WHEN alt_lat IS NOT NULL THEN 'if it is really at the other address on record'
                    ELSE 'if fuzzy addresses are really at their other location' END END,
        ', ', element_at(names, get(data_lost, 0).winner), ' is #1',
        CASE WHEN size(data_lost) > 1 THEN concat(' (', CAST(size(data_lost) AS STRING), ' of 3 double-checks change #1)') ELSE '' END,
        '.')
    END,
    CASE WHEN rnk <> 1 AND size(situation_won) > 0 THEN
      concat('Would be your best option if ',
             array_join(transform(situation_won, x -> concat(lower(substr(x.label, 1, 1)), substr(x.label, 2))), ', or if '), '.')
    END,
    confidence_label,
    location_validation_status, CAST(location_validation_score AS INT), location_validation_label, location_checks,
    (SELECT n FROM excl)
  FROM enriched
  WHERE rnk <= top_n OR is_near_alt OR is_better_farther
  ORDER BY rnk;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Try it

-- COMMAND ----------

SELECT rank, facility_name, distance_km, evidence_tier, trust_score, match_score, why, how, caveats
FROM workspace.datathon.find_care('dialysis', 'Jaipur');

-- COMMAND ----------

SELECT rank, facility_name, distance_km, evidence_tier, trust_score, why, caveats
FROM workspace.datathon.find_care('emergency c-section', '226001', 50, 5);   -- PIN code in Lucknow

-- COMMAND ----------

SELECT rank, facility_name, distance_km, evidence_tier, trust_score, why, caveats
FROM workspace.datathon.find_care('nicu', 'Patna', 100, 5);
