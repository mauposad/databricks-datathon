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
-- MAGIC patients travel 3× a week, 240 min for planned cardiac surgery), rank by **Quality**; if two are within 10 Quality
-- MAGIC points, the closer one wins (`greedy_rank`: at each rank take the best remaining Quality, or the closest facility
-- MAGIC within 10 points of it). Facilities beyond the budget follow, labelled
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
-- MAGIC Requires notebooks 01–03.

-- COMMAND ----------

CREATE OR REPLACE FUNCTION workspace.datathon.resolve_location(place STRING)
RETURNS TABLE (lat DOUBLE, lon DOUBLE, matched_as STRING, label STRING)
COMMENT 'Resolve a PIN code, "lat,lon", city or district name to coordinates'
RETURN
  WITH q AS (SELECT trim(place) AS p),
  as_coords AS (
    SELECT try_cast(regexp_extract(p, '^\\s*(-?[0-9.]+)\\s*,\\s*(-?[0-9.]+)\\s*$', 1) AS DOUBLE) AS lat,
           try_cast(regexp_extract(p, '^\\s*(-?[0-9.]+)\\s*,\\s*(-?[0-9.]+)\\s*$', 2) AS DOUBLE) AS lon,
           'coordinates' AS matched_as, p AS label, 1 AS pri
    FROM q WHERE p RLIKE '^\\s*-?[0-9.]+\\s*,\\s*-?[0-9.]+\\s*$'
  ),
  as_pin AS (
    SELECT g.lat, g.lon, 'pin_code', concat('PIN ', g.pincode, ' (', g.district, ', ', g.state, ')'), 2
    FROM q JOIN workspace.datathon.silver_pincode_geo g ON g.pincode = try_cast(q.p AS INT)
    WHERE q.p RLIKE '^[1-9][0-9]{5}$'
  ),
  as_city AS (  -- centre of facilities that confidently sit in a city of that name
    SELECT percentile(f.lat, 0.5), percentile(f.lon, 0.5), 'city', concat(initcap(q.p), ' (city, from ', count(*), ' facilities)'), 3
    FROM q JOIN workspace.datathon.silver_facilities f
      ON upper(trim(f.city_raw)) = upper(q.p) AND f.location_confidence = 'high'
    GROUP BY q.p HAVING count(*) > 0
  ),
  as_district AS (
    SELECT percentile(g.lat, 0.5), percentile(g.lon, 0.5), 'district', concat(max(g.district), ' district, ', max(g.state)), 4
    FROM q JOIN workspace.datathon.silver_pincode_geo g ON upper(g.district) = upper(q.p)
    GROUP BY q.p HAVING count(*) > 0
  )
  SELECT lat, lon, matched_as, label FROM (
    SELECT * FROM as_coords UNION ALL SELECT * FROM as_pin UNION ALL SELECT * FROM as_city UNION ALL SELECT * FROM as_district
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
  top_n   INT    DEFAULT 5)
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
  is_better_farther BOOLEAN)
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
  allc AS (  -- every facility with evidence for the service within 300 km
    SELECT g.*, svc.service_label AS svc_label, svc.text_regex AS match_pattern, svc.budget, svc.urgency, svc.rationale,
           loc.label AS loc_label, loc.lat AS origin_lat, loc.lon AS origin_lon, loc.matched_as AS origin_matched_as,
           workspace.datathon.haversine_km(loc.lat, loc.lon, g.lat, g.lon) AS km,
           g.evidence_tier IN ('strong', 'moderate', 'probable') AS qualifies
    FROM workspace.datathon.gold_facility_services g
    JOIN svc USING (service_key)
    CROSS JOIN loc
    WHERE g.lat IS NOT NULL AND workspace.datathon.haversine_km(loc.lat, loc.lon, g.lat, g.lon) <= greatest(300, max_km)
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
           CASE WHEN a.qualifies AND a.km * 1.4 / 35 * 60 <= a.budget THEN 1 WHEN a.qualifies THEN 2 ELSE 3 END AS band
    FROM allc a CROSS JOIN radius r
    WHERE a.km <= r.eff_km
  ),
  greedy AS (
    SELECT workspace.datathon.greedy_rank(collect_list(named_struct(
             'id', facility_id, 'q', CAST(quality_score AS INT), 'km', km, 'band', band)), 100) AS ord
    FROM cand WHERE band < 3
  ),
  ranked AS (
    SELECT c.*,
      CAST(CASE WHEN array_position(transform(g.ord, o -> o.id), c.facility_id) > 0
                THEN array_position(transform(g.ord, o -> o.id), c.facility_id)
                ELSE coalesce(size(g.ord), 0) + row_number() OVER (
                       PARTITION BY array_position(transform(g.ord, o -> o.id), c.facility_id) > 0
                       ORDER BY c.band, c.quality_score DESC, c.km) END AS INT) AS rnk,
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
      AND NOT lower(e.name) RLIKE 'ivf|fertility|\\beye\\b|netra|nethra|vision|dental|diagnostic|imaging|\\bscan|\\blab|skin|derma|cosmetic|physio|rehab|ayurved|homoeo|homeo|psychiatr|de-?addiction'
      AND workspace.datathon.haversine_km(loc.lat, loc.lon, e.lat, e.lon) <= 100
  ),
  notes AS (
    SELECT
      concat_ws(' ',
        CASE WHEN r.eff_km > max_km THEN concat('Nothing with confirmed or probable evidence within ', CAST(CAST(max_km AS INT) AS STRING),
                                                ' km, so the search was widened to ', CAST(CAST(r.eff_km AS INT) AS STRING), ' km.') END,
        CASE WHEN r.nearest_q_km IS NULL THEN 'No facility with confirmed or probable evidence within 300 km; every result is unconfirmed.'
             WHEN (SELECT count(*) FROM ranked WHERE band = 1) = 0 THEN
               concat('Nothing confirmed is within the ', CAST((SELECT max(budget) FROM svc) AS STRING), '-minute travel budget for this service. ',
                      'Nearest confirmed option is ', CAST(round(r.nearest_q_km) AS INT), ' km (about ',
                      CAST(round(r.nearest_q_km * 1.4 / 35 * 60) AS INT), ' min) away.') END) AS search_note
    FROM radius r
  ),
  enriched AS (
    SELECT rk.*,
      (rk.qualifies AND rk.facility_id = rk.nearest_id_in_group AND rk.rnk > 1) AS is_near_alt,
      -- the best facility beyond the travel budget, if it is clearly better (10+ Quality points) than a reachable #1
      (rk.band = 2 AND t.band = 1 AND rk.quality_score >= t.quality_score + 10
       AND rk.facility_id = max_by(rk.facility_id, struct(rk.quality_score, -rk.km)) OVER (PARTITION BY rk.band)) AS is_better_farther,
      t.name AS top_name, t.quality_score AS top_q, t.travel AS top_travel, t.checks_found AS top_cf, t.checks_total AS top_ct,
      t.evidence_tier AS top_tier, t.support_found AS top_support
    FROM ranked rk CROSS JOIN top1 t
  )
  SELECT
    rnk,
    name,
    round(km, 1),
    evidence_tier,
    CAST(trust_score AS INT),
    CAST(quality_score AS DOUBLE),
    concat(
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
      CAST(q_location AS STRING), '/8, coherence ', CAST(q_coherence AS STRING), '/4)',
      CASE WHEN q_penalties < 0 THEN concat(' ', CAST(q_penalties AS STRING), ' penalties') ELSE '' END, '. ',
      CASE band
        WHEN 3 THEN 'Ranked after all confirmed/probable options because its evidence is weak.'
        ELSE concat('Travel about ', CAST(travel AS STRING), ' min vs a ', CAST(budget AS STRING), '-min budget (',
                    CASE WHEN in_budget THEN 'reachable' ELSE 'farther option' END, '). At rank ', CAST(rnk AS STRING),
                    ' the best remaining Quality was ', CAST(qstar AS STRING),
                    CASE WHEN quality_score = qstar THEN '; this is that facility'
                         ELSE concat('; this facility is ', CAST(qstar - quality_score AS STRING), ' points below it but closer, and within 10 points the closer one wins') END,
                    '.') END) AS how,
    caveats,
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
             CASE WHEN quality_score + CAST(round(get(array_sort(filter(evidence_checks, c -> c.status <> 'found'), (a, b) -> b.max_points - a.max_points), 0).max_points * 50.0 / 60) AS INT) >= top_q - 10
                  THEN ', so it would then be within 10 points and, being closer, would rank first.'
                  ELSE ', so that alone would not be enough (a closer facility wins only within 10 points).' END) END,
    (SELECT search_note FROM notes),
    CASE WHEN urgency = 'emergency' AND service_key IN ('emergency_csection', 'trauma') AND (SELECT f FROM er) IS NOT NULL THEN
      concat('If the patient is unstable, go to the nearest 24×7 emergency facility first: ', (SELECT f.name FROM er),
             ' (', CAST(round((SELECT f.km FROM er), 1) AS STRING), ' km',
             CASE WHEN (SELECT f.phone FROM er) IS NOT NULL THEN concat(', ', (SELECT f.phone FROM er)) ELSE '' END, ').') END,
    concat('Among facilities reachable within ', CAST(budget AS STRING), ' minutes (', urgency, ': ', rationale,
           '), we rank by Quality. If two are within 10 Quality points, the closer one wins (at each rank we take the best ',
           'remaining Quality, or the closest facility within 10 points of it). ',
           'Facilities beyond the budget come after all reachable ones, labelled "farther option". ',
           'Weak (unconfirmed) evidence always comes last. If nothing qualifies within the search radius, it is doubled (up to 300 km).'),
    'Travel time is estimated as straight-line km × 1.4 (road detour) ÷ 35 km/h average speed.',
    evidence_method, CAST(checks_found AS INT), CAST(checks_total AS INT),
    evidence_checks, claims_cited, is_better_farther
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
