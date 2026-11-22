-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 02 · Silver: facilities
-- MAGIC
-- MAGIC Builds `workspace.datathon.silver_facilities`: **one trustworthy-shaped row per real facility**, with every
-- MAGIC original claim kept (for citation) and explicit data-quality flags instead of silent fixes.
-- MAGIC
-- MAGIC | Problem in the raw share | What this notebook does |
-- MAGIC |---|---|
-- MAGIC | ~88 rows are CSV fragments (text shifted into wrong columns) | read `bronze_locval_facilities_repaired` (location_validation_scoring 01): the 30 split facilities are merged back with their coordinates and `cluster_id`; fragments are dropped |
-- MAGIC | duplicate rows for the same entity | one row per `cluster_id` (keeps the most complete; remembers how many were collapsed) |
-- MAGIC | list columns stored as JSON strings, with repeats and placeholders ("no specific equipment information…") | parse to arrays, de-duplicate, drop placeholders |
-- MAGIC | doctors / beds / year stored as text, some impossible | cast, null out implausible values, flag it (incl. 200+ beds with < 10 doctors) |
-- MAGIC | dental or eye clinics matching general keywords ("atraumatic extraction" → trauma) | `scope_family` = dental / eye when all clinical specialties are dental / eye care |
-- MAGIC | 234 spellings of "state" | normalise via alias table; final state/district comes from location, not free text |
-- MAGIC | coordinates and PIN code disagree for ~1 in 5 facilities | compare coordinates vs PIN vs city/state text, pick the side with more support, record a confidence |
-- MAGIC | some records merge several facilities | flag records whose own text places them in another state or district |
-- MAGIC
-- MAGIC | is the location consistent across pincode, city, district, postal circle and map point? | join `silver_location_validation` (0–5 score per `cluster_id`); no score → flag `location_not_validated` |
-- MAGIC
-- MAGIC Requires notebook 01 (`silver_pincode_geo`, `haversine_km`) and the `location_validation_scoring` job
-- MAGIC (`bronze_locval_facilities_repaired`, `silver_location_validation` in this schema).

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

-- Does the phrase name a *different* hospital/clinic than the facility itself? ("referred to Cloudnine Hospital ...")
-- Takes the distinctive words of each "<Proper Name> Hospital/Clinic/Institute" in the phrase (4+ letters, not
-- generic or department words like "care", "super", "cancer", "sports injury") and calls it another facility only if
-- none of them appears in the facility's own name, allowing spelling variants (Ayush ~ Aayush, Sriram ~ Sri Ram).
CREATE OR REPLACE FUNCTION workspace.datathon.mentions_other_facility(phrase STRING, own_name STRING)
RETURNS BOOLEAN
RETURN exists(
  regexp_extract_all(phrase, '((?:[A-Z][A-Za-z.&\']+ ){1,4})(?:Hospitals?|Clinic|Medical College|Institute|Nursing Home|Healthcare|Medical Centre|Medical Center)', 1),
  c -> size(filter(split(lower(c), '[^a-z]+'), w -> length(w) >= 4 AND w NOT IN
          ('super', 'speciality', 'specialty', 'specialities', 'multi', 'multispeciality', 'care', 'city', 'general', 'government',
           'district', 'civil', 'memorial', 'medical', 'research', 'centre', 'center', 'private', 'limited', 'india', 'indian',
           'national', 'this', 'their', 'with', 'from', 'other', 'nearby', 'local', 'major', 'leading', 'children', 'women',
           'mother', 'trust', 'teaching', 'advanced', 'charitable', 'cancer', 'oncology', 'neuro', 'heart', 'cardiac',
           'cardiothoracic', 'kidney', 'pain', 'fertility', 'sports', 'injury', 'cornea', 'retina', 'baby', 'well', 'robotic',
           'orthopaedic', 'orthopedic', 'ortho', 'surgery', 'surgical', 'spine', 'trauma', 'dialysis', 'diabetes', 'skin',
           'dental', 'maternity', 'child', 'eye', 'vision', 'chest', 'top', 'best', 'list', 'listed', 'among', 'cataract',
           'failure', 'health', 'check', 'wellness', 'joint', 'replacement', 'breast', 'stroke', 'sleep', 'liver', 'gastro', 'lung',
           'bone', 'hand', 'neurosurgery', 'neurology', 'hospitals', 'clinics', 'international', 'ayushman', 'card',
           'empanelled', 'certified', 'aesthetic', 'infertility', 'gynecology', 'gynaecology', 'obstetrics', 'pediatric',
           'paediatric', 'neonatal', 'provides', 'expert', 'tertiary', 'bedded', 'personalised', 'specialized',
           'specialised', 'page', 'polyclinic', 'nursing', 'home', 'government', 'municipal', 'primary', 'community'))) > 0
   AND NOT exists(
          filter(split(lower(c), '[^a-z]+'), w -> length(w) >= 4),
          w -> contains(regexp_replace(lower(own_name), '[^a-z]', ''), w)
            OR exists(split(lower(own_name), '[^a-z]+'), o -> length(o) >= 4 AND levenshtein(o, w) <= 1)));

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
  -- the share's facilities table with CSV-split rows repaired (see notebooks/location_validation_scoring/01)
  FROM workspace.datathon.bronze_locval_facilities_repaired f
  WHERE repair_status IN ('clean', 'repaired_head', 'head_no_tail')
    AND organization_type = 'facility' AND cluster_id IS NOT NULL AND cluster_id <> ''
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
    concat_ws(' ', array_join(capabilities, ' '), description) AS evidence_text,
    -- clinical specialties minus ancillary ones that dental/eye clinics also list (radiology for X-rays, etc.)
    filter(transform(specialties, x -> lower(x)),
           x -> x NOT IN ('radiology', 'familymedicine', 'anesthesia', 'anesthesiology', 'pathology', 'preventivemedicine')) AS core_specialties
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
  f.city_supports_coords, f.city_supports_pin,
  round(f.km_coords_to_pin, 1)                       AS km_coords_to_pin,
  f.pin_district, f.pin_state, f.pin_n_districts, f.coords_district, f.coords_state, f.claimed_state,
  f.city_raw, f.state_raw, f.postcode_raw, f.address_text, f.lat_raw, f.lon_raw,
  -- scale (a 200+ bed hospital reporting fewer than 10 doctors is almost certainly a partial count, e.g. KGMU = 1)
  CASE WHEN f.doctors_raw  BETWEEN 1 AND 3000
        AND NOT (f.capacity_raw BETWEEN 200 AND 5000 AND f.doctors_raw < 10) THEN f.doctors_raw END AS number_doctors,
  CASE WHEN f.capacity_raw BETWEEN 1 AND 5000 THEN f.capacity_raw END  AS capacity_beds,
  -- specialty scope: a facility whose clinical specialties are all dental (or all eye care) cannot match
  -- general services like trauma or NICU, even if a keyword appears ("atraumatic extraction", "tooth trauma")
  CASE
    WHEN size(f.core_specialties) > 0 AND forall(f.core_specialties, x -> x RLIKE '^(dent|oral)|odont|dentistry|maxillofacial|cleft|tmj') THEN 'dental'
    -- "<X> Dental Clinic" / "<X> Eye Hospital" are dental / eye care whatever specialties were auto-listed
    WHEN lower(f.name) RLIKE '\\bdental\\b|dentist|\\bdent(o|al)? ?care\\b' AND NOT lower(f.name) RLIKE 'medical college|general hospital|multi' THEN 'dental'
    WHEN lower(f.name) RLIKE '\\beye (hospital|clinic|care|cent(re|er)|institute)|netralaya|nethralaya|\\bnetra\\b' AND NOT lower(f.name) RLIKE 'medical college|general hospital|multi' THEN 'eye'
    WHEN size(f.core_specialties) > 0 AND forall(f.core_specialties, x -> x RLIKE 'ophthalm|retina|cornea|glaucoma|oculoplast|strabism|cataract|uveitis|optometr|vitreo|^eye') THEN 'eye'
    WHEN size(f.core_specialties) = 0 AND (f.facility_type = 'dentist' OR lower(f.name) RLIKE '\\bdental\\b|dentist') THEN 'dental'
    WHEN size(f.core_specialties) = 0 AND lower(f.name) RLIKE '\\beye\\b|netra|nethra|ophthalm|lasik' THEN 'eye'
  END AS scope_family,
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
    CASE WHEN f.doctors_raw BETWEEN 1 AND 9 AND f.capacity_raw BETWEEN 200 AND 5000 THEN 'implausible_doctor_count' END,
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

-- MAGIC %md
-- MAGIC ## Record coherence: does the record describe one facility, in one place?
-- MAGIC
-- MAGIC * `silver_possible_duplicates`: pairs of *different* records within 3 km whose normalised names (without
-- MAGIC   "hospital", "clinic", "pvt", "ltd", punctuation, ...) are identical, or differ by 1 letter (8+ letters) or
-- MAGIC   2 letters (12+ letters). Flagged, never merged.
-- MAGIC * `silver_identity_claims`: every claim a record makes about *who and where* it is (coordinates, PIN code, city,
-- MAGIC   state, "located in" places, other hospitals named in its description, near-duplicate neighbours), each marked
-- MAGIC   as agreeing or not with the resolved location.
-- MAGIC * `record_coherence_score` (0–100) = 100 minus named deductions, each its own `coh_*` column:
-- MAGIC
-- MAGIC | component | deduction | when |
-- MAGIC |---|---|---|
-- MAGIC | `coh_coords_pin` | −25 / −10 | coordinates are > 75 km / 25–75 km from the stated PIN code |
-- MAGIC | `coh_city` | −10 | the city text matches neither the resolved PIN area nor its district |
-- MAGIC | `coh_state` | −15 | the record's own state field names a different state |
-- MAGIC | `coh_located_in` | −20 | the text says it is located in a district > 100 km away |
-- MAGIC | `coh_other_facility` | −10 | the description names a different hospital or clinic |
-- MAGIC | `coh_duplicate` | −10 | a near-duplicate record sits nearby |
-- MAGIC
-- MAGIC Missing information is not a conflict and costs nothing. **`identity_conflict`** (possible merged record, a
-- MAGIC near-duplicate, or a coordinates/PIN conflict nothing could settle) caps the confidence label at Medium.

-- COMMAND ----------

CREATE OR REPLACE FUNCTION workspace.datathon.norm_facility_name(s STRING)
RETURNS STRING
RETURN trim(regexp_replace(regexp_replace(lower(s),
  '\\b(hospitals?|clinics?|nursing home|pvt|private|ltd|limited|the|and|multi ?-?speciality|multi ?-?specialty|super ?-?speciality|super ?-?specialty|speciality|specialty|centre|center|medical|research|institute|healthcare|health care|care|dr|dental|dentist|eye|child|children|heart|ortho|orthopaedic|orthopedic|maternity|polyclinic|diagnostics?|college|general|memorial|trust)\\b|[^a-z ]', ' '),
  '\\s+', ' '));

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.silver_possible_duplicates
COMMENT 'Pairs of different facility records that look like the same facility (near-identical normalised names, within 3 km or same PIN). Flagged, never merged.'
AS
WITH f AS (
  SELECT facility_id, name, pincode, lat, lon,
         -- distinctive part of the name: no generic words, no city name ("The Dental Hub Ahmedabad" -> "hub")
         trim(regexp_replace(workspace.datathon.norm_facility_name(name),
              concat('\\b(', coalesce(nullif(workspace.datathon.norm_place(city_raw), ''), '#'), ')\\b'), '')) AS nname,
         -- focus words must match: "Verma Hospital" and "Verma Dental Clinic" are not the same facility
         filter(array('dental', 'eye', 'child', 'heart', 'ortho', 'maternity', 'cancer', 'ivf'), w -> lower(name) RLIKE w) AS focus,
         CAST(floor(lat) AS INT) AS clat, CAST(floor(lon) AS INT) AS clon
  FROM workspace.datathon.silver_facilities
  WHERE lat IS NOT NULL
),
cells AS (  -- each facility in its own and the 8 neighbouring 1-degree cells, so pairs across a cell edge are found
  SELECT f.*, clat + dx AS nlat, clon + dy AS nlon
  FROM f CROSS JOIN (SELECT explode(sequence(-1, 1)) AS dx) CROSS JOIN (SELECT explode(sequence(-1, 1)) AS dy)
)
SELECT a.facility_id, b.facility_id AS duplicate_id, b.name AS duplicate_name,
       round(workspace.datathon.haversine_km(a.lat, a.lon, b.lat, b.lon), 2) AS km_apart,
       levenshtein(a.nname, b.nname) AS name_edit_distance
FROM f a
JOIN cells b ON b.nlat = a.clat AND b.nlon = a.clon AND b.facility_id <> a.facility_id
WHERE length(a.nname) >= 5 AND a.focus = b.focus
  -- short names must match exactly ("yadav dental" vs "madhav dental" is two edits but a different clinic)
  AND levenshtein(a.nname, b.nname) <= CASE WHEN length(a.nname) >= 12 THEN 2 WHEN length(a.nname) >= 8 THEN 1 ELSE 0 END
  AND workspace.datathon.haversine_km(a.lat, a.lon, b.lat, b.lon) <= 3;

-- COMMAND ----------

-- Which city names are used for which districts? Learned from records whose coordinates and PIN code agree, so that
-- "Bangalore" in Bengaluru Urban or "Kochi" in Ernakulam are not counted as conflicts (3+ such records needed).
CREATE OR REPLACE TABLE workspace.datathon.ref_city_districts
COMMENT 'City spellings seen for each district, learned from facilities whose coordinates and PIN code agree (3+ facilities)'
AS
SELECT upper(trim(city_raw)) AS city, district, state, count(*) AS n_facilities
FROM workspace.datathon.silver_facilities
WHERE location_check = 'agree' AND length(trim(city_raw)) >= 3 AND district IS NOT NULL
GROUP BY ALL
HAVING count(*) >= 3;

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.silver_identity_claims
COMMENT 'Every claim a record makes about who and where it is, and whether it agrees with the resolved location'
AS
SELECT facility_id, 'coordinates' AS claim_type, concat(CAST(round(lat_raw, 5) AS STRING), ',', CAST(round(lon_raw, 5) AS STRING)) AS claim_value,
       'latitude/longitude' AS source_field,
       workspace.datathon.haversine_km(lat_raw, lon_raw, lat, lon) <= 25 AS agrees_with_location
FROM workspace.datathon.silver_facilities WHERE lat_raw IS NOT NULL
UNION ALL
SELECT facility_id, 'pin_code', CAST(pincode AS STRING), 'address_zipOrPostcode',
       CASE WHEN pin_district IS NULL THEN NULL WHEN location_source = 'pin_centroid' THEN true ELSE km_coords_to_pin <= 25 END
FROM workspace.datathon.silver_facilities WHERE pincode IS NOT NULL
UNION ALL
SELECT s.facility_id, 'city', s.city_raw, 'address_city',
       coalesce(CASE WHEN s.location_source = 'coordinates' THEN s.city_supports_coords ELSE s.city_supports_pin END, false)
         OR rc.city IS NOT NULL
         OR coalesce(workspace.datathon.city_matches(s.city_raw, array(upper(s.district))), false)
FROM workspace.datathon.silver_facilities s
LEFT JOIN workspace.datathon.ref_city_districts rc ON rc.city = upper(trim(s.city_raw)) AND rc.district = s.district
WHERE length(trim(s.city_raw)) >= 3
UNION ALL
SELECT facility_id, 'state', state_raw, 'address_stateOrRegion', claimed_state = state
FROM workspace.datathon.silver_facilities WHERE claimed_state IS NOT NULL
UNION ALL
SELECT facility_id, 'located_in_text', place, 'capability/description', false
FROM workspace.datathon.silver_facilities LATERAL VIEW explode(far_places_in_text) t AS place
UNION ALL
-- another facility named in the description: only names that match a real facility in the dataset (so department
-- names like "Dentistry Clinic" don't count), and not the facility's own name
SELECT DISTINCT o.facility_id, 'other_facility_named', o.sentence, 'description', false
FROM (
  SELECT s.facility_id, s.name, trim(sentence) AS sentence,
         workspace.datathon.norm_facility_name(cand) AS ncand
  FROM workspace.datathon.silver_facilities s
  LATERAL VIEW explode(split(coalesce(s.description, ''), '\\.(\\s|$)')) t AS sentence
  LATERAL VIEW explode(regexp_extract_all(sentence,
    '((?:[A-Z][A-Za-z.&\']+ ){1,4})(?:Hospitals?|Clinic|Medical College|Institute|Nursing Home|Healthcare|Medical Centre|Medical Center)', 1)) u AS cand
  WHERE workspace.datathon.mentions_other_facility(sentence, s.name)
) o
JOIN (SELECT DISTINCT workspace.datathon.norm_facility_name(name) AS n FROM workspace.datathon.silver_facilities) k
  ON k.n = o.ncand AND length(o.ncand) >= 5 AND o.ncand <> workspace.datathon.norm_facility_name(o.name)
UNION ALL
SELECT facility_id, 'possible_duplicate', concat(duplicate_name, ' (', CAST(km_apart AS STRING), ' km away)'), 'name', false
FROM workspace.datathon.silver_possible_duplicates;

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.silver_facilities
COMMENT 'Silver: one row per facility (deduplicated on cluster_id), parsed claim arrays kept for citation, resolved location with confidence, data-quality flags, and a record coherence score with named components'
AS
WITH dup AS (
  SELECT facility_id, collect_set(duplicate_id) AS possible_duplicate_of, collect_set(duplicate_name) AS possible_duplicate_names
  FROM workspace.datathon.silver_possible_duplicates GROUP BY facility_id
),
other AS (
  SELECT facility_id, collect_list(claim_value) AS other_facilities_named
  FROM workspace.datathon.silver_identity_claims WHERE claim_type = 'other_facility_named' GROUP BY facility_id
),
c AS (
  SELECT s.*,
    coalesce(dup.possible_duplicate_of, array()) AS possible_duplicate_of,
    coalesce(dup.possible_duplicate_names, array()) AS possible_duplicate_names,
    coalesce(other.other_facilities_named, array()) AS other_facilities_named,
    CASE location_check WHEN 'conflict' THEN -25 WHEN 'near' THEN -10 ELSE 0 END AS coh_coords_pin,
    CASE WHEN length(trim(s.city_raw)) >= 3
          AND NOT coalesce(CASE WHEN s.location_source = 'coordinates' THEN s.city_supports_coords ELSE s.city_supports_pin END, false)
          AND rc.city IS NULL
          AND NOT coalesce(workspace.datathon.city_matches(s.city_raw, array(upper(s.district))), false)
         THEN -10 ELSE 0 END AS coh_city,
    CASE WHEN claimed_state IS NOT NULL AND state IS NOT NULL AND claimed_state <> state THEN -15 ELSE 0 END AS coh_state,
    CASE WHEN size(far_places_in_text) > 0 THEN -20 ELSE 0 END AS coh_located_in,
    CASE WHEN other.facility_id IS NOT NULL THEN -10 ELSE 0 END AS coh_other_facility,
    CASE WHEN dup.facility_id IS NOT NULL THEN -10 ELSE 0 END AS coh_duplicate
  FROM workspace.datathon.silver_facilities s
  LEFT JOIN dup USING (facility_id)
  LEFT JOIN other USING (facility_id)
  LEFT JOIN (SELECT city, district AS rc_district FROM workspace.datathon.ref_city_districts) rc
         ON rc.city = upper(trim(s.city_raw)) AND rc.rc_district = s.district
),
lv AS (  -- location validation score per cluster_id (notebooks/location_validation_scoring, SCORING_CRITERIA.md)
  SELECT facility_id, location_validation_score, location_validation_label, location_validation_passed,
         location_validation_s, location_checks, failed_checks AS location_failed_checks, scoring_version AS location_scoring_version
  FROM workspace.datathon.silver_location_validation
  WHERE location_validation_status = 'scored'
)
SELECT c.* EXCEPT (quality_flags),
  lv.location_validation_score, lv.location_validation_label, lv.location_validation_passed,
  lv.location_validation_s, lv.location_checks, lv.location_failed_checks, lv.location_scoring_version,
  CASE WHEN lv.facility_id IS NULL THEN 'not_scored' ELSE 'scored' END AS location_validation_status,
  100 + coh_coords_pin + coh_city + coh_state + coh_located_in + coh_other_facility + coh_duplicate AS record_coherence_score,
  (possible_merged_record OR size(possible_duplicate_of) > 0 OR (location_check = 'conflict' AND location_confidence = 'low')) AS identity_conflict,
  concat_ws('; ',
    CASE WHEN possible_merged_record THEN concat('the record says it is located in ', array_join(far_places_in_text, ', ')) END,
    CASE WHEN size(possible_duplicate_of) > 0 THEN concat('a near-duplicate record is nearby (', array_join(possible_duplicate_names, ', '), ')') END,
    CASE WHEN location_check = 'conflict' AND location_confidence = 'low' THEN 'coordinates and PIN code disagree and nothing settles which is right' END
  ) AS identity_conflict_reason,
  array_compact(concat(quality_flags, array(
    CASE WHEN size(possible_duplicate_of) > 0 THEN 'possible_duplicate' END,
    CASE WHEN coh_city < 0 THEN 'city_text_disagrees' END,
    CASE WHEN coh_other_facility < 0 THEN 'other_facility_named' END,
    CASE WHEN lv.facility_id IS NULL THEN 'location_not_validated' END,
    CASE WHEN lv.location_validation_score <= 2 THEN 'location_unverified' END
  ))) AS quality_flags
FROM c LEFT JOIN lv USING (facility_id);

-- COMMAND ----------

-- Health check: how many facilities fall into each location-confidence bucket and flag
SELECT location_confidence, location_check, count(*) AS facilities
FROM workspace.datathon.silver_facilities
GROUP BY ALL ORDER BY 1, 2;

-- COMMAND ----------

SELECT flag, count(*) AS facilities
FROM workspace.datathon.silver_facilities LATERAL VIEW explode(quality_flags) t AS flag
GROUP BY flag ORDER BY 2 DESC;

-- COMMAND ----------

-- Health check: location validation score per facility (location_validation_scoring); NULL = not scored
SELECT location_validation_status, location_validation_score, location_validation_label, count(*) AS facilities
FROM workspace.datathon.silver_facilities
GROUP BY ALL ORDER BY 1, 2 DESC;
