-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 01 · Silver: PIN code geography
-- MAGIC
-- MAGIC Builds `workspace.datathon.silver_pincode_geo`: **one row per PIN code** with a robust location and its district/state.
-- MAGIC
-- MAGIC Why: the raw India Post directory is one row per *post office*, so joining on PIN fans out rows, and its
-- MAGIC coordinates are noisy (~12.6k missing, plus offices placed hundreds of km from their own district).
-- MAGIC We therefore:
-- MAGIC 1. drop coordinates outside India's bounding box,
-- MAGIC 2. drop **placeholder** coordinates: exact values (e.g. latitude 15.5934) repeated across dozens of offices in 3+ districts,
-- MAGIC 3. drop office coordinates more than 120 km from the median of their 3-digit PIN prefix (postal sorting district).
-- MAGIC    We use the PIN prefix, not the "district" column, because India Post's district label can span huge areas
-- MAGIC    (Bastar offices 250 km away are labelled RAIPUR). PINs with no good office coordinates fall back to the prefix median,
-- MAGIC 4. take the **median** of what is left (one bad office can't drag the PIN centroid),
-- MAGIC 5. keep the ambiguity (how many districts/states a PIN spans) instead of hiding it.
-- MAGIC
-- MAGIC Source is read-only (Marketplace share); all outputs go to `workspace.datathon`.

-- COMMAND ----------

CREATE SCHEMA IF NOT EXISTS workspace.datathon
COMMENT 'CMU Datathon 2026: cleaned (silver) and app-ready (gold) tables built from the Virtue Foundation share';

-- COMMAND ----------

-- Great-circle distance in km, reused by every later notebook.
CREATE OR REPLACE FUNCTION workspace.datathon.haversine_km(lat1 DOUBLE, lon1 DOUBLE, lat2 DOUBLE, lon2 DOUBLE)
RETURNS DOUBLE
COMMENT 'Great-circle distance in kilometres between two lat/lon points'
RETURN 6371.0 * 2 * asin(sqrt(
  pow(sin(radians(lat2 - lat1) / 2), 2) +
  cos(radians(lat1)) * cos(radians(lat2)) * pow(sin(radians(lon2 - lon1) / 2), 2)));

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.silver_pincode_geo
COMMENT 'One row per PIN code: robust median location (outlier offices removed), primary district/state, and ambiguity counts'
AS
WITH po AS (
  SELECT
    CAST(pincode AS INT)                                   AS pincode,
    initcap(trim(district))                                AS district,
    CASE WHEN upper(trim(statename)) IN ('NA', '') THEN NULL
         ELSE upper(trim(statename)) END                   AS state_u,
    upper(trim(officename))                                AS officename,
    upper(trim(divisionname))                              AS divisionname,
    try_cast(latitude AS DOUBLE)                           AS lat,
    try_cast(longitude AS DOUBLE)                          AS lon
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory
  WHERE pincode BETWEEN 110000 AND 999999
),
po_bbox AS (
  SELECT *, (lat BETWEEN 6 AND 37.5 AND lon BETWEEN 68 AND 97.5) AS in_bbox FROM po
),
-- Placeholder values: an exact latitude (or longitude) shared by 40+ offices spread over 3+ districts is filler
-- (e.g. lat = 15.5934 or 15.59 paired with random longitudes), not a real location.
placeholder_lat AS (
  SELECT round(lat, 4) AS v FROM po_bbox WHERE in_bbox GROUP BY 1 HAVING count(*) >= 40 AND count(DISTINCT district) >= 3
),
placeholder_lon AS (
  SELECT round(lon, 4) AS v FROM po_bbox WHERE in_bbox GROUP BY 1 HAVING count(*) >= 40 AND count(DISTINCT district) >= 3
),
po_in_india AS (
  SELECT p.*,
         p.in_bbox AND pl.v IS NULL AND pn.v IS NULL AS coord_ok,
         (pl.v IS NOT NULL OR pn.v IS NOT NULL)      AS is_placeholder
  FROM po_bbox p
  LEFT JOIN placeholder_lat pl ON pl.v = round(p.lat, 4)
  LEFT JOIN placeholder_lon pn ON pn.v = round(p.lon, 4)
),
district_median AS (
  SELECT state_u, district,
         percentile(lat, 0.5) AS d_lat, percentile(lon, 0.5) AS d_lon
  FROM po_in_india WHERE coord_ok
  GROUP BY state_u, district
),
-- The first 3 PIN digits are a postal sorting district: a second, independent sanity check.
prefix_median AS (
  SELECT CAST(pincode / 1000 AS INT) AS pin3,
         percentile(lat, 0.5) AS p_lat, percentile(lon, 0.5) AS p_lon
  FROM po_in_india WHERE coord_ok
  GROUP BY 1
),
po_checked AS (
  -- The PIN prefix is the outlier yardstick, not the district: India Post's "district" label can span huge postal
  -- areas (e.g. Bastar offices, 494xxx, are labelled RAIPUR), which would make good Raipur-city coordinates look wrong.
  SELECT p.*,
         coalesce(x.p_lat, d.d_lat) AS d_lat, coalesce(x.p_lon, d.d_lon) AS d_lon,
         p.coord_ok
           AND coalesce(workspace.datathon.haversine_km(p.lat, p.lon, x.p_lat, x.p_lon) <= 120, true) AS coord_kept
  FROM po_in_india p
  LEFT JOIN district_median d USING (state_u, district)
  LEFT JOIN prefix_median x ON x.pin3 = CAST(p.pincode / 1000 AS INT)
)
SELECT
  pincode,
  mode(district)                                          AS district,
  initcap(mode(state_u))                                  AS state,
  count(DISTINCT district)                                AS n_districts,
  count(DISTINCT state_u)                                 AS n_states,
  array_sort(collect_set(district))                       AS all_districts,
  count(*)                                                AS n_post_offices,
  count_if(coord_kept)                                    AS n_offices_geocoded,
  count_if(coord_ok AND NOT coord_kept)                   AS n_offices_outlier_dropped,
  count_if(is_placeholder)                                AS n_offices_placeholder_dropped,
  coalesce(percentile(CASE WHEN coord_kept THEN lat END, 0.5), percentile(d_lat, 0.5)) AS lat,
  coalesce(percentile(CASE WHEN coord_kept THEN lon END, 0.5), percentile(d_lon, 0.5)) AS lon,
  CASE WHEN count_if(coord_kept) > 0 THEN 'post_office_median'
       WHEN max(d_lat) IS NOT NULL   THEN 'pin_prefix_median'
       ELSE NULL END                                      AS geo_method,
  -- every place name tied to this PIN, used later to check a facility's free-text city
  array_distinct(concat(collect_set(officename), collect_set(divisionname), collect_set(upper(district)))) AS place_names
FROM po_checked
GROUP BY pincode;

-- COMMAND ----------

-- Quick health check
SELECT count(*) AS pins,
       count_if(lat IS NULL) AS pins_without_location,
       count_if(geo_method = 'pin_prefix_median') AS pins_using_prefix_fallback,
       count_if(n_districts > 1) AS pins_spanning_districts,
       count_if(n_states > 1) AS pins_spanning_states,
       sum(n_offices_placeholder_dropped) AS office_coords_dropped_as_placeholders,
       sum(n_offices_outlier_dropped) AS office_coords_dropped_as_outliers
FROM workspace.datathon.silver_pincode_geo;

-- COMMAND ----------

-- Spot check: city head-office PINs should land on the real cities
-- (Vadodara 390001 ~22.3,73.2 · Raipur 492001 ~21.25,81.63 · Agra 282001 ~27.18,78.01 · Bengaluru 560001 ~12.97,77.59)
SELECT pincode, district, round(lat, 2) AS lat, round(lon, 2) AS lon, geo_method
FROM workspace.datathon.silver_pincode_geo
WHERE pincode IN (390001, 492001, 282001, 560001, 400049, 834001)
ORDER BY pincode;
