# Databricks notebook source
# MAGIC %md
# MAGIC # 09 · Location linkage by **Zonal Council (broad zone)**
# MAGIC
# MAGIC **Region definition:** Zonal Council of the pincode-directory state (`dir_state`). Notebook 09 also compares the zone under the other state sources.
# MAGIC
# MAGIC Broad zones from India's **Zonal Councils** (Northern, Central, Eastern, Western, Southern, plus the North Eastern Council). Andaman & Nicobar and Lakshadweep are special invitees, not members, so they form `Islands (no zonal council)`. The zone is taken from the pincode-directory state; section 0 shows how the zone changes under the other state sources.
# MAGIC
# MAGIC Requires notebook `00_build_location_pairs` to have run. Widgets: `primary_strategy` picks which pincode
# MAGIC point drives the maps and headline tables (every strategy is still reported in the summary and in
# MAGIC section 8). Results are written to `bronze_loclink_region_summary` (rows for `scheme = 'zonal_council'`).
# MAGIC
# MAGIC **Reading guide:** distance and offset are measured *from the pincode point to the facility point*.
# MAGIC Categories other than `FAC_OK__PIN_OK` are kept and drawn: orange marks = pincode side unusable (shown at the
# MAGIC facility point), aqua marks = facility coordinates unusable (shown at the pincode point).

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 --quiet

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

ra = RegionAnalysis("zonal_council", max_region_panels=8)
ra.overview()

# COMMAND ----------

# MAGIC %md ## 0 · Zone under each state source
# MAGIC Same Zonal Council mapping, applied to: the pincode-directory state, the state written on the record, the state containing the facility coordinates, and the state containing the pincode point.

# COMMAND ----------

z = ra.fr.assign(zone_dir=ra.fr["zonal_council"], zone_stated=ra.fr["zonal_council_from_stated_state"],
                 zone_fac_pt=ra.fr["zonal_council__fac_pt"], zone_pin_pt=ra.fr["zonal_council__pin_pt"])
cols = ["zone_dir", "zone_stated", "zone_fac_pt", "zone_pin_pt"]
display(pd.DataFrame({c: z[c].fillna(UNASSIGNED).value_counts() for c in cols}).fillna(0).astype(int).reset_index())
display(pd.crosstab(z["zone_dir"].fillna(UNASSIGNED), z["zone_fac_pt"].fillna(UNASSIGNED), margins=True))

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
