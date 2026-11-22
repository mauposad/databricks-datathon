# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Build the facility ↔ pincode location pairs (bronze)
# MAGIC
# MAGIC **Run this first.** Every other notebook in `notebooks/location_linkage/` reads the tables written here.
# MAGIC
# MAGIC Each facility has two candidate locations:
# MAGIC
# MAGIC 1. **Facility point**: `facilities.latitude / longitude`
# MAGIC 2. **Pincode point**: derived from the India Post directory offices that share `facilities.address_zipOrPostcode`
# MAGIC
# MAGIC The directory lists **post offices**, not pincodes (~8.5 offices per pincode, up to ~150), so a pincode has
# MAGIC no single coordinate. How we collapse it to one point is an open team decision, so this notebook builds
# MAGIC **every** candidate strategy and the downstream notebooks report all of them:
# MAGIC
# MAGIC | strategy | meaning |
# MAGIC |---|---|
# MAGIC | `office_median` | per-coordinate median of all geocoded, in-India offices |
# MAGIC | `office_mean` | mean of the same offices |
# MAGIC | `office_median_trimmed` | median after dropping offices > `trim_km` from the first-pass median |
# MAGIC | `main_office_mean` | mean of HO + PO offices only (branch offices excluded) |
# MAGIC | `nearest_office` | the pincode's office closest to the facility (best case) |
# MAGIC
# MAGIC Nothing is dropped. Every facility row stays, labelled with a **pair category**
# MAGIC `FAC_<facility-point status>__PIN_<pincode status>`, so bad records stay visible on the maps.
# MAGIC
# MAGIC ### Outputs (`<out_catalog>.<out_schema>.bronze_loclink_*`)
# MAGIC | table | grain |
# MAGIC |---|---|
# MAGIC | `offices` | one row per directory office, parsed coords + spatial ADM1/ADM2 + status |
# MAGIC | `pincodes` | one row per pincode: every strategy's point, office spread, modal postal/admin labels + ambiguity |
# MAGIC | `pairs` | one row per facility row × strategy: both points, distance, bearing, N/E offset, category |
# MAGIC | `facility_regions` | one row per facility row: statuses + region label under every scheme (definition / at facility point / at pincode point) |
# MAGIC | `region_shapes` | one row per scheme × region: polygon WKT used for maps |
# MAGIC | `adm2_labels` | one row per ADM2 polygon: majority postal/district label (how approximate postal outlines are made) |

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 plotly==5.24.1 --quiet

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

dbutils.widgets.text("trim_km", "50", "Trim radius for office_median_trimmed (km)")
dbutils.widgets.text("coastal_snap_km", "10", "Snap points within N km of India's polygons")
dbutils.widgets.text("h3_res", "3", "H3 resolution for the h3_grid scheme")
dbutils.widgets.text("swap_match_km", "25", "Swapped lat/lon must land within N km of pincode point")
dbutils.widgets.text("swap_min_km", "100", "...and the unswapped distance must exceed N km")

TRIM_KM = float(dbutils.widgets.get("trim_km"))
SNAP_KM = float(dbutils.widgets.get("coastal_snap_km"))
H3_RES = int(dbutils.widgets.get("h3_res"))
SWAP_MATCH_KM = float(dbutils.widgets.get("swap_match_km"))
SWAP_MIN_KM = float(dbutils.widgets.get("swap_min_km"))
print(dict(out=f"{OUT_CATALOG}.{OUT_SCHEMA}", trim_km=TRIM_KM, snap_km=SNAP_KM, h3_res=H3_RES,
           swap=(SWAP_MATCH_KM, SWAP_MIN_KM)))

# COMMAND ----------

# MAGIC %md ## 1 · Boundaries

# COMMAND ----------

ensure_boundaries()
adm1 = load_adm1()
adm2 = load_adm2(adm1)
print(f"ADM1 polygons: {len(adm1)}, ADM2 polygons: {len(adm2)}, ADM2 without a parent state: {adm2['state'].isna().sum()}")

# COMMAND ----------

# MAGIC %md ## 2 · Post offices: parse coordinates and locate each office

# COMMAND ----------

off_cols = ["circlename", "regionname", "divisionname", "officename", "pincode", "officetype", "delivery",
            "district", "statename", "latitude", "longitude"]
off = (spark.table(src("india_post_pincode_directory"))
       .withColumn("office_row_id", F.sha2(F.concat_ws("||", *[F.coalesce(F.col(c).cast("string"), F.lit("<null>")) for c in off_cols]), 256))
       .toPandas())
off["office_row_id"] = off["office_row_id"] + "-" + off.groupby("office_row_id").cumcount().astype(str)
off["lat"] = pd.to_numeric(off["latitude"], errors="coerce")
off["lon"] = pd.to_numeric(off["longitude"], errors="coerce")
loc = locate_points(off["lat"], off["lon"], adm2, SNAP_KM)
off = pd.concat([off, loc], axis=1)
off["point_status"] = point_status(off["loc_status"])
off["state_district"] = off["statename"].fillna("NA") + " | " + off["district"].fillna("NA")
off["spatial_state_matches_statename"] = np.where(off["point_status"] == "OK", off["adm_state"] == off["statename"], None)

print(f"offices: {len(off):,}")
display(off["loc_status"].value_counts().rename_axis("loc_status").reset_index(name="offices"))
display(off[off["point_status"] == "OK"]["spatial_state_matches_statename"].value_counts()
        .rename_axis("office coords inside its own statename polygon").reset_index(name="offices"))

# COMMAND ----------

# MAGIC %md ## 3 · Pincodes: one row per pincode, every strategy's point + spread + modal labels

# COMMAND ----------

ok_off = off[off["point_status"] == "OK"].copy()
by_pin = ok_off.groupby("pincode")

pins = off.groupby("pincode").agg(n_offices=("office_row_id", "size")).join(
    off.assign(no_coords=off["loc_status"] == "MISSING", outside=off["loc_status"] == "OUTSIDE_INDIA")
       .groupby("pincode")[["no_coords", "outside"]].sum()
       .rename(columns={"no_coords": "n_offices_no_coords", "outside": "n_offices_outside_india"}))
pins["n_offices_geocoded_ok"] = by_pin.size().reindex(pins.index).fillna(0).astype(int)

med = by_pin[["lat", "lon"]].median()
pins[["lat_office_median", "lon_office_median"]] = med.reindex(pins.index).to_numpy()
mean = by_pin[["lat", "lon"]].mean()
pins[["lat_office_mean", "lon_office_mean"]] = mean.reindex(pins.index).to_numpy()
main = ok_off[ok_off["officetype"].isin(["HO", "PO"])].groupby("pincode")
pins[["lat_main_office_mean", "lon_main_office_mean"]] = main[["lat", "lon"]].mean().reindex(pins.index).to_numpy()
pins["n_main_offices"] = main.size().reindex(pins.index).fillna(0).astype(int)

ok_off = ok_off.join(med.rename(columns={"lat": "med_lat", "lon": "med_lon"}), on="pincode")
ok_off["km_from_pin_median"] = haversine_km(ok_off["lat"], ok_off["lon"], ok_off["med_lat"], ok_off["med_lon"])
trimmed = ok_off[ok_off["km_from_pin_median"] <= TRIM_KM].groupby("pincode")
pins[["lat_office_median_trimmed", "lon_office_median_trimmed"]] = trimmed[["lat", "lon"]].median().reindex(pins.index).to_numpy()
pins["n_offices_trimmed_kept"] = trimmed.size().reindex(pins.index).fillna(0).astype(int)
spread = ok_off.groupby("pincode")["km_from_pin_median"]
pins["spread_max_km"] = spread.max().reindex(pins.index)
pins["spread_p90_km"] = spread.quantile(0.9).reindex(pins.index)
pins["spread_median_km"] = spread.median().reindex(pins.index)


def modal(col):
    """Most frequent value per pincode over ALL offices (ties -> alphabetical), its share, and distinct count."""
    c = (off.dropna(subset=[col]).groupby(["pincode", col]).size().reset_index(name="n")
         .sort_values(["pincode", "n", col], ascending=[True, False, True]))
    top = c.drop_duplicates("pincode").set_index("pincode")
    tot = c.groupby("pincode")["n"].sum()
    return top[col], (top["n"] / tot).rename(f"{col}_modal_share"), c.groupby("pincode")[col].nunique()


for col, out in [("circlename", "circle"), ("regionname", "region"), ("divisionname", "division"),
                 ("statename", "state"), ("state_district", "state_district")]:
    v, share, nd = modal(col)
    pins[out] = v.reindex(pins.index)
    pins[f"{out}_modal_share"] = share.reindex(pins.index)
    pins[f"{out}_n_distinct"] = nd.reindex(pins.index).fillna(0).astype(int)

pins = pins.reset_index()
pins["pincode"] = pins["pincode"].astype("int64")
print(f"pincodes: {len(pins):,}; without any usable office point: {(pins['n_offices_geocoded_ok'] == 0).sum():,}")
display(pins.describe().T)

# COMMAND ----------

# MAGIC %md ## 4 · Facilities: statuses for both sides

# COMMAND ----------

fac_src = spark.table(src("facilities"))
fac = (fac_src.withColumn("fac_row_id", F.sha2(F.concat_ws("||", *[F.coalesce(F.col(c).cast("string"), F.lit("<null>"))
                                                                  for c in fac_src.columns]), 256))
       .select("fac_row_id", "unique_id", "name", "address_line1", "address_city", "address_stateOrRegion",
               "address_zipOrPostcode", "address_countryCode", "latitude", "longitude", "coordinates")
       .toPandas())
fac["fac_row_id"] = fac["fac_row_id"] + "-" + fac.groupby("fac_row_id").cumcount().astype(str)
fac["dup_unique_id"] = fac["unique_id"].duplicated(keep=False) & fac["unique_id"].notna()
fac["row_shift_suspect"] = fac["address_countryCode"].notna() & (fac["address_countryCode"] != "IN")

# pincode side
raw = fac["address_zipOrPostcode"].map(lambda x: None if x is None or (isinstance(x, float) and np.isnan(x)) else str(x))
fac["pin_clean"] = raw.map(lambda x: None if x is None else re.sub(r"\s+", "", x))
fac["pin_was_cleaned"] = (raw.notna() & (fac["pin_clean"] != raw)).astype(bool)
pin_index = pins.set_index("pincode")
is_missing = fac["pin_clean"].map(lambda x: x is None or x.lower() in ("", "null", "none", "na", "nan")).to_numpy(bool)
is_valid = ~is_missing & fac["pin_clean"].map(lambda x: bool(x) and re.fullmatch(r"[1-9]\d{5}", x) is not None).to_numpy(bool)
pin_int = pd.to_numeric(fac["pin_clean"].where(is_valid), errors="coerce")
in_dir = pin_int.isin(pin_index.index).to_numpy(bool)
has_geo = in_dir & pin_int.map(pin_index["n_offices_geocoded_ok"]).fillna(0).gt(0).to_numpy(bool)
fac["pin_status"] = np.select([is_missing, ~is_valid, ~in_dir, ~has_geo],
                              ["MISSING", "MALFORMED", "NOT_IN_DIRECTORY", "NO_GEOCODED_OFFICES"], "OK")
fac["pin_int"] = pin_int.where(in_dir)

# facility point side
fac["fac_lat"] = pd.to_numeric(fac["latitude"], errors="coerce")
fac["fac_lon"] = pd.to_numeric(fac["longitude"], errors="coerce")
floc = locate_points(fac["fac_lat"], fac["fac_lon"], adm2, SNAP_KM)
fac["fac_loc_status"] = floc["loc_status"]
fac["fac_point_status"] = point_status(floc["loc_status"])
fac["fac_adm_state"] = floc["adm_state"]
fac["fac_adm2_label"] = floc["adm2_label"]

display(pd.crosstab(fac["fac_point_status"], fac["pin_status"], margins=True))
print(f"duplicate unique_id rows: {fac['dup_unique_id'].sum()}, row-shift suspects: {fac['row_shift_suspect'].sum()}, "
      f"pins cleaned of whitespace: {fac['pin_was_cleaned'].sum()}")

# COMMAND ----------

# MAGIC %md ## 5 · Pairs: facility row × strategy

# COMMAND ----------

def pair_metrics(df):
    """Adds dist/bearing/offsets/swap check. Computed whenever both points are numeric (even if a side is not OK)."""
    both = df["fac_lat"].notna() & df["fac_lon"].notna() & df["pin_lat"].notna()
    d = df.copy()
    for c in ["dist_km", "bearing_deg", "d_north_km", "d_east_km", "swapped_dist_km"]:
        d[c] = np.nan
    b = d[both]
    d.loc[both, "dist_km"] = haversine_km(b["pin_lat"], b["pin_lon"], b["fac_lat"], b["fac_lon"])
    d.loc[both, "bearing_deg"] = bearing_deg(b["pin_lat"], b["pin_lon"], b["fac_lat"], b["fac_lon"])
    d.loc[both, "d_north_km"] = (b["fac_lat"] - b["pin_lat"]) * KM_PER_DEG
    d.loc[both, "d_east_km"] = (b["fac_lon"] - b["pin_lon"]) * KM_PER_DEG * np.cos(np.radians((b["fac_lat"] + b["pin_lat"]) / 2))
    sw = both & d["fac_lon"].between(-90, 90)
    s = d[sw]
    d.loc[sw, "swapped_dist_km"] = haversine_km(s["pin_lat"], s["pin_lon"], s["fac_lon"], s["fac_lat"])
    d["swap_suspect"] = (d["swapped_dist_km"] < SWAP_MATCH_KM) & (d["dist_km"] > SWAP_MIN_KM)
    d["bucket"] = bucket_of(d["dist_km"])
    return d


base_cols = ["fac_row_id", "fac_lat", "fac_lon", "fac_point_status", "pin_status", "pin_int"]
frames = []
for strat in ["office_median", "office_mean", "office_median_trimmed", "main_office_mean"]:
    f = fac[base_cols].copy()
    f["strategy"] = strat
    f["pin_lat"] = f["pin_int"].map(pin_index[f"lat_{strat}"])
    f["pin_lon"] = f["pin_int"].map(pin_index[f"lon_{strat}"])
    frames.append(f)

# nearest office: closest usable office of the same pincode to the facility point
cand = fac.loc[fac["fac_point_status"] == "OK", ["fac_row_id", "pin_int", "fac_lat", "fac_lon"]].dropna(subset=["pin_int"])
cand["pin_int"] = cand["pin_int"].astype("int64")
cand = cand.merge(ok_off[["pincode", "lat", "lon"]], left_on="pin_int", right_on="pincode")
cand["d"] = haversine_km(cand["fac_lat"], cand["fac_lon"], cand["lat"], cand["lon"])
nearest = cand.loc[cand.groupby("fac_row_id")["d"].idxmin()].set_index("fac_row_id")
f = fac[base_cols].copy()
f["strategy"] = "nearest_office"
f["pin_lat"] = f["fac_row_id"].map(nearest["lat"])
f["pin_lon"] = f["fac_row_id"].map(nearest["lon"])
frames.append(f)

pairs = pd.concat(frames, ignore_index=True)
pairs["pin_point_status"] = pairs["pin_status"]
pairs.loc[(pairs["pin_status"] == "OK") & pairs["pin_lat"].isna(), "pin_point_status"] = "NO_POINT_FOR_STRATEGY"
# nearest_office without usable facility coords: the pincode is fine, the strategy just cannot be evaluated
pairs.loc[(pairs["strategy"] == "nearest_office") & (pairs["pin_status"] == "OK") & (pairs["fac_point_status"] != "OK"),
          "pin_point_status"] = "OK_BUT_NEEDS_FAC_POINT"
pairs["pair_category"] = "FAC_" + pairs["fac_point_status"] + "__PIN_" + pairs["pin_point_status"]
pairs = pair_metrics(pairs)
pairs = pairs.drop(columns=["fac_point_status", "pin_status", "pin_int"])

display(pairs.groupby(["strategy", "pair_category"]).size().unstack(0, fill_value=0))
display(pairs[pairs["pair_category"] == "FAC_OK__PIN_OK"].groupby("strategy")["dist_km"]
        .describe(percentiles=[.1, .25, .5, .75, .9, .95, .99]).round(2))

# COMMAND ----------

# MAGIC %md ## 6 · Region labels for every scheme

# COMMAND ----------

# majority label per ADM2 polygon from the offices inside it, used to locate a *point* in postal regions
adm2_lab = adm2[["shapeID", "shapeName", "state", "adm2_label"]].copy()
for col, out in [("circlename", "postal_circle"), ("regionname", "postal_region"), ("divisionname", "postal_division"),
                 ("state_district", "dir_district")]:
    c = (ok_off.groupby(["adm2_label", col]).size().reset_index(name="n")
         .sort_values(["adm2_label", "n", col], ascending=[True, False, True]))
    tot = c.groupby("adm2_label")["n"].sum()
    top = c.drop_duplicates("adm2_label").set_index("adm2_label")
    adm2_lab[out] = adm2_lab["adm2_label"].map(top[col])
    adm2_lab[f"{out}_share"] = adm2_lab["adm2_label"].map(top["n"] / tot)
adm2_lab["n_offices_inside"] = adm2_lab["adm2_label"].map(ok_off.groupby("adm2_label").size()).fillna(0).astype(int)
print(f"ADM2 polygons with no geocoded office inside (no postal label): {(adm2_lab['n_offices_inside'] == 0).sum()}")
a2 = adm2_lab.drop_duplicates("adm2_label").set_index("adm2_label")

# pincode point used for "__pin_pt" labels is office_median (fixed, independent of the primary_strategy widget)
ploc = locate_points(fac["pin_int"].map(pin_index["lat_office_median"]),
                     fac["pin_int"].map(pin_index["lon_office_median"]), adm2, SNAP_KM)
fac["pin_adm_state"] = ploc["adm_state"].where(ploc["loc_status"].isin(["WITHIN", "SNAPPED"]))
fac["pin_adm2_label"] = ploc["adm2_label"].where(ploc["loc_status"].isin(["WITHIN", "SNAPPED"]))
fac_ok = fac["fac_point_status"] == "OK"
fac_a2 = fac["fac_adm2_label"].where(fac_ok)
fac_st = fac["fac_adm_state"].where(fac_ok)

fr = fac[["fac_row_id", "unique_id", "name", "address_line1", "address_city", "address_stateOrRegion",
          "address_zipOrPostcode", "pin_clean", "pin_was_cleaned", "fac_lat", "fac_lon", "fac_loc_status",
          "fac_point_status", "pin_status", "dup_unique_id", "row_shift_suspect"]].copy()
for out, pcol in [("postal_circle", "circle"), ("postal_region", "region"), ("postal_division", "division"),
                  ("dir_state", "state"), ("dir_district", "state_district")]:
    fr[out] = fac["pin_int"].map(pin_index[pcol])
    fr[f"pin_{pcol}_n_distinct"] = fac["pin_int"].map(pin_index[f"{pcol}_n_distinct"])
    fr[f"pin_{pcol}_modal_share"] = fac["pin_int"].map(pin_index[f"{pcol}_modal_share"])
    if out == "dir_state":
        fr[f"{out}__fac_pt"], fr[f"{out}__pin_pt"] = fac_st, fac["pin_adm_state"]
    else:
        fr[f"{out}__fac_pt"] = fac_a2.map(a2[out])
        fr[f"{out}__pin_pt"] = fac["pin_adm2_label"].map(a2[out])

fr["fac_stated_state"] = fac["address_stateOrRegion"].map(stated_state_label)
fr["fac_stated_state__fac_pt"], fr["fac_stated_state__pin_pt"] = fac_st, fac["pin_adm_state"]
fr["spatial_state"] = fac_st
fr["spatial_state__fac_pt"], fr["spatial_state__pin_pt"] = fac_st, fac["pin_adm_state"]
fr["spatial_district"] = fac_a2
fr["spatial_district__fac_pt"], fr["spatial_district__pin_pt"] = fac_a2, fac["pin_adm2_label"]
fr["zonal_council"] = fr["dir_state"].map(zone_of)
fr["zonal_council__fac_pt"] = fac_st.map(zone_of)
fr["zonal_council__pin_pt"] = fac["pin_adm_state"].map(zone_of)
fr["zonal_council_from_stated_state"] = fr["fac_stated_state"].map(zone_of)

# pincode footprint: is the facility within the radius spanned by its pincode's offices?
med_lat = fac["pin_int"].map(pin_index["lat_office_median"])
med_lon = fac["pin_int"].map(pin_index["lon_office_median"])
fr["pin_spread_max_km"] = fac["pin_int"].map(pin_index["spread_max_km"])
fr["pin_n_offices_geocoded_ok"] = fac["pin_int"].map(pin_index["n_offices_geocoded_ok"])
fr["dist_to_office_median_km"] = np.where(fac_ok & med_lat.notna(),
                                          haversine_km(fac["fac_lat"], fac["fac_lon"], med_lat, med_lon), np.nan)
fr["within_pin_footprint"] = np.where(fr["dist_to_office_median_km"].notna(),
                                      fr["dist_to_office_median_km"] <= fr["pin_spread_max_km"], None)

# H3 cells via Spark built-ins
h3_in = pd.DataFrame({"fac_row_id": fr["fac_row_id"],
                      "flat": fr["fac_lat"].where(fac_ok), "flon": fr["fac_lon"].where(fac_ok),
                      "plat": med_lat.where(fac["pin_adm_state"].notna()), "plon": med_lon.where(fac["pin_adm_state"].notna())})
h3 = (spark.createDataFrame(h3_in)
      .select("fac_row_id",
              F.expr(f"CASE WHEN flat IS NOT NULL AND NOT isnan(flat) THEN h3_longlatash3string(flon, flat, {H3_RES}) END").alias("h3_grid"),
              F.expr(f"CASE WHEN plat IS NOT NULL AND NOT isnan(plat) THEN h3_longlatash3string(plon, plat, {H3_RES}) END").alias("h3_grid__pin_pt"))
      .toPandas())
fr = fr.merge(h3, on="fac_row_id", how="left")
fr["h3_grid__fac_pt"] = fr["h3_grid"]
fr["h3_res"] = H3_RES

display(fr.head(20))

# COMMAND ----------

# MAGIC %md ## 7 · Region polygons for maps

# COMMAND ----------

shape_rows = []


def add_shapes(scheme, gdf, label_col, method):
    g = gdf.dropna(subset=[label_col]).dissolve(by=label_col).reset_index()
    g["geometry"] = g.geometry.simplify(0.005)
    for _, r in g.iterrows():
        shape_rows.append(dict(scheme=scheme, region=r[label_col], method=method, geometry_wkt=r.geometry.wkt))


for scheme in ["dir_state", "fac_stated_state", "spatial_state"]:
    add_shapes(scheme, adm1, "state", "ADM1")
a2g = adm2.merge(adm2_lab.drop(columns=["shapeName", "state"]), on=["shapeID", "adm2_label"])
for scheme in ["postal_circle", "postal_region", "postal_division", "dir_district"]:
    add_shapes(scheme, a2g, scheme, "ADM2 majority label (approximate)")
add_shapes("spatial_district", adm2, "adm2_label", "ADM2")
z = adm1.copy()
z["zone"] = z["state"].map(zone_of)
add_shapes("zonal_council", z, "zone", "ADM1 dissolved by zone")
cells = pd.unique(pd.concat([fr["h3_grid"], fr["h3_grid__pin_pt"]]).dropna())
h3s = (spark.createDataFrame(pd.DataFrame({"region": cells}))
       .select("region", F.expr("h3_boundaryaswkt(region)").alias("geometry_wkt")).toPandas())
for _, r in h3s.iterrows():
    shape_rows.append(dict(scheme="h3_grid", region=r["region"], method=f"H3 res {H3_RES}", geometry_wkt=r["geometry_wkt"]))
shapes = pd.DataFrame(shape_rows)
display(shapes.groupby(["scheme", "method"]).size().rename("regions").reset_index())

# COMMAND ----------

# MAGIC %md ## 8 · Write bronze tables

# COMMAND ----------

off_out = off.drop(columns=["latitude", "longitude"]).rename(columns={"loc_status": "office_loc_status"})
off_out["pincode"] = off_out["pincode"].astype("int64")
write_table(off_out, "offices", "Bronze: India Post directory offices with parsed coordinates, status "
            "(MISSING/WITHIN/SNAPPED/OUTSIDE_INDIA) and the ADM1/ADM2 polygon each office falls in.")
write_table(pins, "pincodes", "Bronze: one row per pincode. Candidate pincode points per strategy (office_median, "
            "office_mean, office_median_trimmed, main_office_mean), office spread, modal postal/admin labels + ambiguity.")
write_table(pairs, "pairs", "Bronze: facility row x pincode-point strategy. Both points, haversine distance, bearing "
            "(pincode point -> facility), N/E offset km, lat/lon swap check, pair_category.")
fr_out = fr.copy()
for c in ["within_pin_footprint"]:
    fr_out[c] = fr_out[c].astype("object")
write_table(fr_out, "facility_regions", "Bronze: one row per facility row. Linkage statuses and region label under "
            "every scheme: <scheme> (definition), <scheme>__fac_pt (at facility coords), <scheme>__pin_pt (at office_median pincode point).")
write_table(shapes, "region_shapes", "Bronze: region polygons (WKT) per scheme for mapping. Postal/district outlines are "
            "approximate (ADM2 polygons labelled by majority of offices inside).")
write_table(adm2_lab, "adm2_labels", "Bronze: geoBoundaries ADM2 polygons with the majority postal circle/region/division "
            "and directory district of the geocoded offices inside them.")

# COMMAND ----------

# MAGIC %md ## 9 · Quick national readout

# COMMAND ----------

ok = pairs[pairs["pair_category"] == "FAC_OK__PIN_OK"]
nat = ok.groupby("strategy").apply(dist_stats).T
display(nat.reset_index().rename(columns={"index": "metric"}))
