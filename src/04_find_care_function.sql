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
-- MAGIC **Ranking rule:** `match_score = 0.6 × trust_score + 0.4 × distance_score`, where
-- MAGIC `distance_score = 100 × (1 − km / max_km)`. Tiers are ranked as bands: *strong/moderate* first, then *probable*
-- MAGIC (large or teaching hospitals that list the specialty but never name the procedure, labelled "call to confirm"),
-- MAGIC then *weak* (specialty-only or description-only), which only appear to fill the list, labelled as unconfirmed.
-- MAGIC
-- MAGIC Trade-off made explicit: a well-evidenced hospital a bit further away beats a poorly evidenced one next door,
-- MAGIC but distance still matters (40% of the score).
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
  negated_or_referral_mentions ARRAY<STRING>, match_pattern STRING, max_km_used DOUBLE, n_candidates INT)
COMMENT 'Ranked facilities for a service near a place, with cited evidence (why) and score arithmetic (how)'
RETURN
  WITH loc AS (SELECT * FROM workspace.datathon.resolve_location(place)),
  svc AS (
    SELECT service_key, service_label, text_regex FROM workspace.datathon.ref_services
    WHERE service_key = lower(trim(service)) OR lower(service_label) = lower(trim(service))
       OR array_contains(aliases, lower(trim(service)))
    LIMIT 1
  ),
  cand AS (
    SELECT g.*, svc.service_label AS svc_label, loc.label AS loc_label,
         svc.text_regex AS match_pattern,
         loc.lat AS origin_lat, loc.lon AS origin_lon, loc.matched_as AS origin_matched_as,
           workspace.datathon.haversine_km(loc.lat, loc.lon, g.lat, g.lon) AS km
    FROM workspace.datathon.gold_facility_services g
    JOIN svc USING (service_key)
    CROSS JOIN loc
    WHERE g.lat IS NOT NULL
  ),
  scored AS (
    SELECT *,
           round(100 * greatest(0, 1 - km / max_km)) AS distance_score,
           round(0.6 * trust_score + 0.4 * round(100 * greatest(0, 1 - km / max_km)), 1) AS match_score,
           evidence_tier = 'weak' AS is_weak,
           CASE evidence_tier WHEN 'probable' THEN 1 WHEN 'weak' THEN 2 ELSE 0 END AS tier_band
    FROM cand WHERE km <= max_km
  ),
  ranked AS (
    SELECT *, CAST(row_number() OVER (ORDER BY tier_band, match_score DESC, km) AS INT) AS rnk,
           CAST(count(*) OVER () AS INT) AS n_cand FROM scored
  )
  SELECT
    rnk,
    name,
    round(km, 1),
    evidence_tier,
    CAST(trust_score AS INT),
    match_score,
    concat(
      CASE WHEN is_weak THEN 'UNCONFIRMED: ' WHEN evidence_tier = 'probable' THEN 'PROBABLE (call to confirm): ' ELSE '' END,
      name, ' is ', CAST(round(km, 1) AS STRING), ' km from ', loc_label, '. ',
      initcap(evidence_tier), ' evidence for ', svc_label, ': ', evidence_summary, '. ',
      'Location: ', location_note) AS why,
    concat(
      'match ', CAST(match_score AS STRING), ' = 0.6 x trust ', CAST(trust_score AS STRING),
      ' + 0.4 x distance ', CAST(CAST(distance_score AS INT) AS STRING), ' (', CAST(round(km, 1) AS STRING), ' of ', CAST(CAST(max_km AS INT) AS STRING), ' km). ',
      'trust = evidence ', CAST(pts_evidence AS STRING), '/60 + sources ', CAST(pts_sources AS STRING), '/15 (', CAST(n_source_domains AS STRING), ' websites)',
      ' + size ', CAST(pts_scale AS STRING), '/10 + location ', CAST(pts_location AS STRING), '/15',
      CASE WHEN pen_merged < 0 THEN concat(' ', CAST(pen_merged AS STRING), ' possible merged record') ELSE '' END,
      CASE WHEN pen_facility_type < 0 THEN concat(' ', CAST(pen_facility_type AS STRING), ' not a hospital') ELSE '' END,
      CASE WHEN pen_negated < 0 THEN concat(' ', CAST(pen_negated AS STRING), ' negative/referral mention') ELSE '' END,
      CASE WHEN pen_numbers < 0 THEN concat(' ', CAST(pen_numbers AS STRING), ' implausible numbers') ELSE '' END,
      '.') AS how,
    caveats,
    procedures_cited, capabilities_cited, equipment_cited, description_cited,
    source_urls, district, state, location_confidence,
    official_phone, official_website, facility_id, svc_label, loc_label,
    lat, lon, address_text, city_raw, pincode, email, facebook_link,
    facility_type, operator_type, specialties_cited,
    CAST(number_doctors AS INT), CAST(capacity_beds AS INT), n_source_domains, distance_score,
    origin_lat, origin_lon, origin_matched_as,
    CAST(pts_evidence AS INT), CAST(pts_sources AS INT), CAST(pts_scale AS INT), CAST(pts_location AS INT),
    CAST(pen_merged AS INT), CAST(pen_facility_type AS INT), CAST(pen_negated AS INT), CAST(pen_numbers AS INT),
    negated_or_referral_mentions, match_pattern, max_km, n_cand
  FROM ranked
  WHERE rnk <= top_n
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
