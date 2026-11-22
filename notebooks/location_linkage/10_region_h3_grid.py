# Databricks notebook source
# MAGIC %md
# MAGIC # 10 · Location linkage by **H3 hexagon grid (administration-free)**
# MAGIC
# MAGIC **Region definition:** H3 cell (resolution `h3_res` from notebook 00) containing the facility coordinates. Equal-area cells remove any dependence on administrative boundaries.
# MAGIC
# MAGIC Equal-area **H3 hexagons** around the facility coordinates (resolution set by `h3_res` in notebook 00; res 3 cells are ~12,000 km²). This scheme ignores every administrative boundary, so it shows *where* on the map the error concentrates without any naming or boundary-matching artefacts. Cell IDs are not human-readable; use the maps.
# MAGIC
# MAGIC Requires notebook `00_build_location_pairs` to have run. Widgets: `primary_strategy` picks which pincode
# MAGIC point drives the maps and headline tables (every strategy is still reported in the summary and in
# MAGIC section 8). Results are written to `bronze_loclink_region_summary` (rows for `scheme = 'h3_grid'`).
# MAGIC
# MAGIC **Reading guide:** distance and offset are measured *from the pincode point to the facility point*.
# MAGIC Categories other than `FAC_OK__PIN_OK` are kept and drawn: orange marks = pincode side unusable (shown at the
# MAGIC facility point), aqua marks = facility coordinates unusable (shown at the pincode point).

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 --quiet

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

ra = RegionAnalysis("h3_grid", max_region_panels=24)
ra.overview()

# COMMAND ----------

# MAGIC %md ## 1 · Coverage: linkage category per region (nothing dropped)

# COMMAND ----------

ra.coverage()

# COMMAND ----------

# MAGIC %md ## 2 · Full distance breakdown per region (mean, median, percentiles, threshold counts, direction)
# MAGIC Persisted to `bronze_loclink_region_summary`. All strategies are included; the display shows the primary one.

# COMMAND ----------

ra.summary_stats()

# COMMAND ----------

# MAGIC %md ## 3 · Average difference by region (mean vs median, IQR)
# MAGIC A mean far above the median means a few very wrong records dominate that region.

# COMMAND ----------

ra.average_by_region()

# COMMAND ----------

# MAGIC %md ## 4 · Distribution per region and threshold exceedance

# COMMAND ----------

ra.distribution()

# COMMAND ----------

ra.threshold_heatmap()

# COMMAND ----------

# MAGIC %md ## 5 · Maps: median by region, and every ordered pair

# COMMAND ----------

ra.choropleth()

# COMMAND ----------

ra.pairs_map()

# COMMAND ----------

# MAGIC %md ## 6 · One map per region (pairs, outline, non-OK records)
# MAGIC "leaving frame" counts facilities whose point lies outside the zoomed panel; their lines are cut at the edge.

# COMMAND ----------

ra.region_panels()

# COMMAND ----------

# MAGIC %md ## 7 · Direction of the offset
# MAGIC A uniform rose (R near 0) suggests random noise. A lobe (R near 1) suggests a systematic shift, e.g. a whole batch geocoded to one city.

# COMMAND ----------

ra.direction()

# COMMAND ----------

# MAGIC %md ## 8 · Sensitivity to the pincode-point strategy

# COMMAND ----------

ra.strategy_sensitivity()

# COMMAND ----------

# MAGIC %md ## 9 · Region assignment agreement
# MAGIC Does the region by this scheme's definition match the region that the facility point, and the pincode point, actually fall in?

# COMMAND ----------

ra.assignment_agreement()

# COMMAND ----------

# MAGIC %md ## 10 · Largest individual disagreements (for manual inspection)

# COMMAND ----------

ra.outliers(40)
