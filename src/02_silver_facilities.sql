-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 02 · Silver: facilities
-- MAGIC
-- MAGIC Builds `workspace.datathon.silver_facilities`: **one trustworthy-shaped row per real facility**, with every
-- MAGIC original claim kept (for citation) and explicit data-quality flags instead of silent fixes.
-- MAGIC
-- MAGIC | Problem in the raw share | What this notebook does |
-- MAGIC |---|---|
-- MAGIC | ~88 rows are CSV fragments (text shifted into wrong columns) | keep only `organization_type = 'facility'` |
-- MAGIC | duplicate rows for the same entity | one row per `cluster_id` (keeps the most complete; remembers how many were collapsed) |
-- MAGIC | list columns stored as JSON strings, with repeats and placeholders ("no specific equipment information…") | parse to arrays, de-duplicate, drop placeholders |
-- MAGIC | doctors / beds / year stored as text, some impossible | cast, null out implausible values, flag it |
-- MAGIC | 234 spellings of "state" | normalise via alias table; final state/district comes from location, not free text |
-- MAGIC | coordinates and PIN code disagree for ~1 in 5 facilities | compare coordinates vs PIN vs city/state text, pick the side with more support, record a confidence |
-- MAGIC | some records merge several facilities | flag records whose own text places them in another state or district |
-- MAGIC
-- MAGIC Requires notebook 01 (`silver_pincode_geo`, `haversine_km`).

-- COMMAND ----------

-- Normalise a place string: lowercase, '&' -> 'and', drop punctuation/digits, squash spaces.
CREATE OR REPLACE FUNCTION workspace.datathon.norm_place(s STRING)
RETURNS STRING
RETURN trim(regexp_replace(regexp_replace(lower(s), '&', ' and '), '[^a-z]+', ' '));

-- COMMAND ----------

-- Parse a JSON-array-as-string column into a clean, de-duplicated array; drops blanks and "no information" placeholders.
CREATE OR REPLACE FUNCTION workspace.datathon.clean_list(s STRING)
RETURNS ARRAY<STRING>
RETURN array_distinct(filter(
  transform(from_json(s, 'array<string>'), x -> trim(x)),
  x -> x IS NOT NULL AND x <> '' AND lower(x) <> 'null'
       AND NOT x RLIKE '(?i)(no specific|not available|not specified|not mentioned|no information|no details|provided content|unknown)'));

-- COMMAND ----------

-- Does a free-text city plausibly match one of a list of (upper-case) place names?
CREATE OR REPLACE FUNCTION workspace.datathon.city_matches(city STRING, names ARRAY<STRING>)
RETURNS BOOLEAN
RETURN CASE WHEN city IS NULL OR length(trim(city)) < 3 OR names IS NULL THEN NULL
  ELSE exists(names, n ->
         n = upper(trim(city))
      OR (length(trim(city)) >= 4 AND (n LIKE concat(upper(trim(city)), '%') OR upper(trim(city)) LIKE concat(n, '%')))
      OR (length(trim(city)) >= 5 AND levenshtein(n, upper(trim(city))) <= 2))
END;

-- COMMAND ----------

-- State alias lookup. `in_text` = safe to search for inside free text (full names only, no 2-letter codes).
CREATE OR REPLACE TABLE workspace.datathon.ref_state_aliases
COMMENT 'Maps messy state spellings to canonical state names (canonical = India Post spelling)'
AS
WITH canonical AS (
  SELECT DISTINCT state FROM workspace.datathon.silver_pincode_geo WHERE state IS NOT NULL
),
manual(alias, state, in_text) AS (
  VALUES
  ('up', 'Uttar Pradesh', false), ('u p', 'Uttar Pradesh', false), ('uttarpradesh', 'Uttar Pradesh', true), ('uttar prades h', 'Uttar Pradesh', false),
  ('mp', 'Madhya Pradesh', false), ('m p', 'Madhya Pradesh', false), ('madhyapradesh', 'Madhya Pradesh', true), ('madhya', 'Madhya Pradesh', false),
  ('tamilnadu', 'Tamil Nadu', true), ('tn', 'Tamil Nadu', false),
  ('orissa', 'Odisha', true),
  ('chattisgarh', 'Chhattisgarh', true), ('chhatisgarh', 'Chhattisgarh', true), ('cg', 'Chhattisgarh', false),
  ('uttaranchal', 'Uttarakhand', true), ('uttranchal', 'Uttarakhand', true), ('u k', 'Uttarakhand', false), ('uk', 'Uttarakhand', false),
  ('telengana', 'Telangana', true), ('ts', 'Telangana', false),
  ('gj', 'Gujarat', false), ('mh', 'Maharashtra', false), ('ms', 'Maharashtra', false), ('br', 'Bihar', false),
  ('dl', 'Delhi', false), ('nct', 'Delhi', false), ('nct of delhi', 'Delhi', false), ('nct delhi', 'Delhi', false), ('new delhi', 'Delhi', false),
  ('delhi ncr', 'Delhi', false), ('ncr delhi', 'Delhi', false), ('west delhi', 'Delhi', false), ('east delhi', 'Delhi', false),
  ('south delhi', 'Delhi', false), ('north west delhi', 'Delhi', false), ('south east delhi area', 'Delhi', false),
  ('pondicherry', 'Puducherry', true), ('u t of puducherry', 'Puducherry', false),
  ('chandigarh ut', 'Chandigarh', false), ('punjab region', 'Punjab', false),
  ('j and k', 'Jammu And Kashmir', false), ('jk', 'Jammu And Kashmir', false), ('kashmir', 'Jammu And Kashmir', false), ('jammu j and k', 'Jammu And Kashmir', false),
  ('daman and diu', 'The Dadra And Nagar Haveli And Daman And Diu', true),
  ('dadra and nagar haveli', 'The Dadra And Nagar Haveli And Daman And Diu', true),
  ('dadra and nagar haveli and daman and diu', 'The Dadra And Nagar Haveli And Daman And Diu', false),
  ('north goa', 'Goa', false), ('south goa', 'Goa', false)
)
SELECT alias, state, in_text FROM manual
UNION ALL
SELECT workspace.datathon.norm_place(state), state, true FROM canonical
WHERE workspace.datathon.norm_place(state) NOT IN (SELECT alias FROM manual);

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.silver_facilities
COMMENT 'Silver: one row per facility (deduplicated on cluster_id), parsed claim arrays kept for citation, resolved location with confidence, and data-quality flags'
AS
WITH raw AS (
  SELECT f.*,
         row_number() OVER (PARTITION BY cluster_id
                            ORDER BY length(coalesce(capability, '')) + length(coalesce(procedure, '')) DESC, unique_id) AS rn,
         count(*)            OVER (PARTITION BY cluster_id) AS n_raw_rows,
         collect_set(unique_id) OVER (PARTITION BY cluster_id) AS all_unique_ids
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities f
  WHERE organization_type = 'facility' AND cluster_id IS NOT NULL
),
base AS (
  SELECT
    cluster_id                                                   AS facility_id,
    unique_id,
    all_unique_ids,
    n_raw_rows,
    trim(name)                                                   AS name,
    CASE lower(facilityTypeId) WHEN 'farmacy' THEN 'pharmacy' WHEN 'null' THEN NULL ELSE lower(facilityTypeId) END AS facility_type,
    CASE lower(operatorTypeId) WHEN 'government' THEN 'public' WHEN 'null' THEN NULL ELSE lower(operatorTypeId) END AS operator_type,
    nullif(nullif(trim(description), ''), 'null')                AS description,
    workspace.datathon.clean_list(specialties)                   AS specialties,
    workspace.datathon.clean_list(procedure)                     AS procedures,
    workspace.datathon.clean_list(equipment)                     AS equipment,
    workspace.datathon.clean_list(capability)                    AS capabilities,
    filter(from_json(source_urls, 'array<string>'), u -> u IS NOT NULL AND u <> '') AS source_urls,
    -- numbers: keep only plausible values
    try_cast(numberDoctors AS INT)                               AS doctors_raw,
    try_cast(capacity AS INT)                                    AS capacity_raw,
    try_cast(yearEstablished AS INT)                             AS year_raw,
    -- contact & raw address (kept verbatim for display / citation)
    nullif(officialPhone, 'null')                                AS official_phone,
    nullif(officialWebsite, 'null')                              AS official_website,
    nullif(email, 'null')                                        AS email,
    CASE WHEN facebookLink RLIKE '^https?://' THEN facebookLink END AS facebook_link,
    concat_ws(', ', nullif(address_line1, 'null'), nullif(address_line2, 'null'), nullif(address_line3, 'null')) AS address_text,
    nullif(trim(address_city), 'null')                           AS city_raw,
    nullif(trim(address_stateOrRegion), 'null')                  AS state_raw,
    address_zipOrPostcode                                        AS postcode_raw,
    try_cast(regexp_extract(address_zipOrPostcode, '([1-9][0-9]{5})', 1) AS INT) AS pincode,
    CASE WHEN latitude BETWEEN 6 AND 37.5 AND longitude BETWEEN 68 AND 97.5 THEN latitude END  AS lat_raw,
    CASE WHEN latitude BETWEEN 6 AND 37.5 AND longitude BETWEEN 68 AND 97.5 THEN longitude END AS lon_raw,
    (latitude IS NOT NULL AND NOT (latitude BETWEEN 6 AND 37.5 AND longitude BETWEEN 68 AND 97.5)) AS coords_outside_india,
    yearEstablished, numberDoctors, capacity
  FROM raw WHERE rn = 1
),
claimed AS (  -- what the record's own state field says, normalised
  SELECT b.facility_id,
         coalesce(a1.state, a2.state) AS claimed_state
  FROM base b
  LEFT JOIN workspace.datathon.ref_state_aliases a1
         ON a1.alias = workspace.datathon.norm_place(b.state_raw)
  LEFT JOIN workspace.datathon.ref_state_aliases a2
         ON a2.alias = workspace.datathon.norm_place(element_at(split(b.state_raw, '[,;]'), -1))
),
pin_cells AS (
  SELECT pincode, district, state, lat, lon, place_names,
         CAST(floor(lat) AS INT) AS clat, CAST(floor(lon) AS INT) AS clon
  FROM workspace.datathon.silver_pincode_geo WHERE lat IS NOT NULL
),
fac_cells AS (
  SELECT b.facility_id, b.lat_raw, b.lon_raw,
         CAST(floor(b.lat_raw) AS INT) + dx AS clat, CAST(floor(b.lon_raw) AS INT) + dy AS clon
  FROM base b
  CROSS JOIN (SELECT explode(sequence(-1, 1)) AS dx)
  CROSS JOIN (SELECT explode(sequence(-1, 1)) AS dy)
  WHERE b.lat_raw IS NOT NULL
),
nearest AS (  -- the PIN area whose centre is closest to the facility's own coordinates
  SELECT fc.facility_id,
         min_by(struct(pc.pincode, pc.district, pc.state, pc.place_names),
                workspace.datathon.haversine_km(fc.lat_raw, fc.lon_raw, pc.lat, pc.lon)) AS nn,
         min(workspace.datathon.haversine_km(fc.lat_raw, fc.lon_raw, pc.lat, pc.lon))  AS nn_km
  FROM fac_cells fc JOIN pin_cells pc USING (clat, clon)
  GROUP BY fc.facility_id
),
geo AS (
  SELECT b.*, c.claimed_state,
         p.district AS pin_district, p.state AS pin_state, p.lat AS pin_lat, p.lon AS pin_lon,
         p.n_districts AS pin_n_districts, p.place_names AS pin_place_names,
         n.nn.pincode AS coords_nearest_pincode, n.nn.district AS coords_district, n.nn.state AS coords_state,
         n.nn.place_names AS coords_place_names,
         workspace.datathon.haversine_km(b.lat_raw, b.lon_raw, p.lat, p.lon) AS km_coords_to_pin
  FROM base b
  JOIN claimed c USING (facility_id)
  LEFT JOIN workspace.datathon.silver_pincode_geo p ON p.pincode = b.pincode
  LEFT JOIN nearest n USING (facility_id)
),
votes AS (
  SELECT g.*,
    CASE
      WHEN lat_raw IS NULL AND pin_lat IS NULL THEN 'no_location'
      WHEN lat_raw IS NULL THEN 'pin_only'
      WHEN pin_lat IS NULL THEN 'coords_only'
      WHEN km_coords_to_pin <= 25 THEN 'agree'
      WHEN km_coords_to_pin <= 75 THEN 'near'
      ELSE 'conflict'
    END AS location_check,
    coalesce(workspace.datathon.city_matches(city_raw, array_union(coalesce(coords_place_names, array()), array(upper(coords_district)))), false) AS city_supports_coords,
    coalesce(workspace.datathon.city_matches(city_raw, array_union(coalesce(pin_place_names, array()), array(upper(pin_district)))), false)       AS city_supports_pin,
    coalesce(claimed_state = coords_state, false) AS state_supports_coords,
    coalesce(claimed_state = pin_state, false)    AS state_supports_pin
  FROM geo g
),
resolved AS (
  SELECT v.*,
    CAST(city_supports_coords AS INT) + CAST(state_supports_coords AND NOT state_supports_pin AS INT) AS coords_votes,
    CAST(city_supports_pin AS INT)    + CAST(state_supports_pin AND NOT state_supports_coords AS INT) AS pin_votes
  FROM votes v
),
located AS (
  SELECT r.*,
    CASE
      WHEN location_check IN ('agree', 'near', 'coords_only') THEN 'coordinates'
      WHEN location_check = 'pin_only' THEN 'pin_centroid'
      WHEN location_check = 'conflict' AND pin_votes > coords_votes THEN 'pin_centroid'
      WHEN location_check = 'conflict' THEN 'coordinates'
    END AS location_source,
    CASE
      WHEN location_check = 'agree' THEN 'high'
      WHEN location_check IN ('near', 'coords_only') THEN 'medium'
      -- two independent signals (city text + one of coords/PIN) outvote the third
      WHEN location_check = 'conflict' AND coords_votes > pin_votes AND city_supports_coords THEN 'medium'
      WHEN location_check = 'conflict' AND pin_votes > coords_votes AND city_supports_pin THEN 'medium'
      WHEN location_check IN ('conflict', 'pin_only') THEN 'low'
      ELSE 'none'
    END AS location_confidence,
    CASE
      WHEN location_check = 'agree'       THEN 'Coordinates and PIN code agree (within 25 km).'
      WHEN location_check = 'near'        THEN concat('Coordinates are ', CAST(round(km_coords_to_pin) AS INT), ' km from the PIN code area; roughly consistent.')
      WHEN location_check = 'coords_only' THEN 'Has coordinates but no usable PIN code to cross-check them.'
      WHEN location_check = 'pin_only'    THEN 'No coordinates; location approximated by the centre of its PIN code area.'
      WHEN location_check = 'no_location' THEN 'No usable coordinates or PIN code.'
      WHEN pin_votes > coords_votes       THEN concat('Coordinates are ', CAST(round(km_coords_to_pin) AS INT), ' km from the stated PIN code; city/state text supports the PIN, so the PIN area centre is used (approximate).')
      WHEN coords_votes > pin_votes       THEN concat('Coordinates are ', CAST(round(km_coords_to_pin) AS INT), ' km from the stated PIN code; city/state text supports the coordinates, so they are used.')
      ELSE concat('Coordinates are ', CAST(round(km_coords_to_pin) AS INT), ' km from the stated PIN code and nothing else settles which is right. Location is uncertain.')
    END AS location_note
  FROM resolved r
),
final_geo AS (
  SELECT l.*,
    CASE WHEN location_source = 'coordinates' THEN lat_raw ELSE pin_lat END AS lat,
    CASE WHEN location_source = 'coordinates' THEN lon_raw ELSE pin_lon END AS lon,
    CASE WHEN location_check IN ('agree', 'near') OR location_source = 'pin_centroid' THEN pin_district ELSE coalesce(coords_district, pin_district) END AS district,
    coalesce(
      CASE WHEN location_check IN ('agree', 'near') OR location_source = 'pin_centroid' THEN pin_state ELSE coalesce(coords_state, pin_state) END,
      claimed_state) AS state,
    concat_ws(' ', array_join(capabilities, ' '), description) AS evidence_text
  FROM located l
),
state_mentions AS (  -- states named in the record's own descriptive text
  SELECT f.facility_id, collect_set(a.state) AS states_in_text
  FROM final_geo f
  JOIN workspace.datathon.ref_state_aliases a
    ON a.in_text AND lower(f.evidence_text) RLIKE concat('\\b', a.alias, '\\b')
  GROUP BY f.facility_id
),
district_pins AS (
  -- every PIN area labelled with a district; distance to the *nearest* one is robust to India Post's
  -- oversized district labels and to districts that share a name across states
  SELECT upper(district) AS d, district AS dname, lat AS dlat, lon AS dlon
  FROM workspace.datathon.silver_pincode_geo
  WHERE lat IS NOT NULL AND length(district) >= 4
),
located_in AS (
  -- "located in X" / "based in X" phrases where X is a real district name, and no PIN area of that district is
  -- within 100 km of where we placed the facility. Nearby districts (New Delhi vs West Delhi, Mumbai vs Thane) are ignored.
  SELECT facility_id,
         collect_set(concat(dname, ' (~', CAST(round(km, -1) AS INT), ' km away)')) AS far_places_in_text
  FROM (
    SELECT c.facility_id, dc.dname,
           min(workspace.datathon.haversine_km(c.lat, c.lon, dc.dlat, dc.dlon)) AS km
    FROM (
      SELECT facility_id, lat, lon, upper(trim(cand)) AS cand
      FROM final_geo
      LATERAL VIEW explode(regexp_extract_all(evidence_text,
        '(?i)(?:located|based|situated|branch(?:es)?|centres?|centers?) (?:in|at) ([A-Za-z][A-Za-z .-]{2,30}?)(?=,| India|\\.|;| and |\\)|$)', 1)) t AS cand
      WHERE lat IS NOT NULL
    ) c
    JOIN district_pins dc ON dc.d = c.cand
    GROUP BY c.facility_id, dc.dname
  )
  WHERE km > 100
  GROUP BY facility_id
)
SELECT
  f.facility_id,
  f.unique_id,
  f.all_unique_ids,
  f.n_raw_rows,
  f.name,
  f.facility_type,
  f.operator_type,
  -- resolved location
  f.lat, f.lon, f.district, f.state, f.pincode,
  f.location_source, f.location_confidence, f.location_check, f.location_note,
  round(f.km_coords_to_pin, 1)                       AS km_coords_to_pin,
  f.pin_district, f.pin_state, f.pin_n_districts, f.coords_district, f.coords_state, f.claimed_state,
  f.city_raw, f.state_raw, f.postcode_raw, f.address_text, f.lat_raw, f.lon_raw,
  -- scale
  CASE WHEN f.doctors_raw  BETWEEN 1 AND 3000 THEN f.doctors_raw END   AS number_doctors,
  CASE WHEN f.capacity_raw BETWEEN 1 AND 5000 THEN f.capacity_raw END  AS capacity_beds,
  CASE WHEN f.year_raw BETWEEN 1800 AND year(current_date()) THEN f.year_raw END AS year_established,
  -- claims (kept verbatim for citation)
  f.description, f.specialties, f.procedures, f.equipment, f.capabilities,
  f.source_urls,
  size(f.source_urls)                                AS n_source_urls,
  size(array_distinct(transform(f.source_urls, u -> regexp_extract(u, '^https?://(?:www\\.)?([^/]+)', 1)))) AS n_source_domains,
  f.official_phone, f.official_website, f.email, f.facebook_link,
  -- merge signals
  -- informational only (states are often mentioned for referrals, chains, patient origin):
  array_except(coalesce(sm.states_in_text, array()), array_compact(array(f.state, f.claimed_state))) AS other_states_in_text,
  -- the actual merge signal: the record says it is located somewhere > 100 km from where it is placed
  coalesce(li.far_places_in_text, array()) AS far_places_in_text,
  -- quality flags
  array_compact(array(
    CASE WHEN f.location_confidence IN ('low', 'none') THEN 'location_uncertain' END,
    CASE WHEN f.location_check = 'conflict' THEN 'coords_pin_conflict' END,
    CASE WHEN f.coords_outside_india THEN 'coords_outside_india' END,
    CASE WHEN f.claimed_state IS NOT NULL AND f.state IS NOT NULL AND f.claimed_state <> f.state THEN 'state_field_disagrees' END,
    CASE WHEN f.pin_n_districts > 1 THEN 'pin_spans_districts' END,
    CASE WHEN (f.doctors_raw IS NOT NULL AND NOT f.doctors_raw BETWEEN 1 AND 3000)
           OR (f.capacity_raw IS NOT NULL AND NOT f.capacity_raw BETWEEN 1 AND 5000)
           OR (f.year_raw IS NOT NULL AND NOT f.year_raw BETWEEN 1800 AND year(current_date())) THEN 'implausible_number_removed' END,
    CASE WHEN f.n_raw_rows > 1 THEN 'duplicate_rows_collapsed' END
  )) AS quality_flags_base
FROM final_geo f
LEFT JOIN state_mentions sm USING (facility_id)
LEFT JOIN located_in li USING (facility_id);

-- COMMAND ----------

-- Add the merge / source flags (need the columns computed above).
CREATE OR REPLACE TABLE workspace.datathon.silver_facilities
COMMENT 'Silver: one row per facility (deduplicated on cluster_id), parsed claim arrays kept for citation, resolved location with confidence, and data-quality flags'
AS
SELECT * EXCEPT (quality_flags_base),
  size(far_places_in_text) > 0 AS possible_merged_record,
  array_compact(concat(quality_flags_base, array(
    CASE WHEN size(far_places_in_text) > 0 THEN 'possible_merged_record' END,
    CASE WHEN n_source_domains <= 1 THEN 'single_source' END
  ))) AS quality_flags
FROM workspace.datathon.silver_facilities;

-- COMMAND ----------

-- Health check: how many facilities fall into each location-confidence bucket and flag
SELECT location_confidence, location_check, count(*) AS facilities
FROM workspace.datathon.silver_facilities
GROUP BY ALL ORDER BY 1, 2;

-- COMMAND ----------

SELECT flag, count(*) AS facilities
FROM workspace.datathon.silver_facilities LATERAL VIEW explode(quality_flags) t AS flag
GROUP BY flag ORDER BY 2 DESC;
