# Databricks notebook source
# MAGIC %md
# MAGIC # `_common`: shared config and helpers for the location-linkage notebooks
# MAGIC
# MAGIC Loaded by every notebook in this folder with `%run ./_common`. The calling notebook must first
# MAGIC `%pip install geopandas==1.0.1`.
# MAGIC
# MAGIC Contents: output-table config, India boundary loading, state-name normalisation, distance/bearing math,
# MAGIC the region-scheme registry, and `RegionAnalysis`, the class that produces every table and visual
# MAGIC in the per-region notebooks.

# COMMAND ----------

import json
import math
import os
import re
import unicodedata
import urllib.request

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import shapely
from matplotlib.collections import LineCollection
from pyspark.sql import functions as F

pd.set_option("display.max_columns", 200)
pd.set_option("display.width", 250)

# COMMAND ----------

# MAGIC %md ## Configuration

# COMMAND ----------

STRATEGIES = ["office_median", "office_mean", "office_median_trimmed", "main_office_mean", "nearest_office"]
STRATEGY_HELP = {
    "office_median": "Per-coordinate median of all geocoded, in-India post offices sharing the pincode",
    "office_mean": "Mean of all geocoded, in-India post offices sharing the pincode",
    "office_median_trimmed": "Median after dropping offices more than `trim_km` from the first-pass median",
    "main_office_mean": "Mean of head/sub offices only (officetype HO or PO; branch offices BO excluded)",
    "nearest_office": "The single office of that pincode closest to the facility (best-case distance)",
}

dbutils.widgets.text("out_catalog", "workspace", "Output catalog")
dbutils.widgets.text("out_schema", "default", "Output schema")
dbutils.widgets.dropdown("primary_strategy", "office_median", STRATEGIES, "Pincode point strategy")

OUT_CATALOG = dbutils.widgets.get("out_catalog")
OUT_SCHEMA = dbutils.widgets.get("out_schema")
PRIMARY_STRATEGY = dbutils.widgets.get("primary_strategy")

SRC_CATALOG = "databricks_virtue_foundation_dataset_dais_2026"
SRC_SCHEMA = "virtue_foundation_dataset"
VOLUME_NAME = "loclink_geo"
VOLUME_DIR = f"/Volumes/{OUT_CATALOG}/{OUT_SCHEMA}/{VOLUME_NAME}"


def src(table):
    return f"{SRC_CATALOG}.{SRC_SCHEMA}.{table}"


def tbl(name):
    return f"{OUT_CATALOG}.{OUT_SCHEMA}.bronze_loclink_{name}"


def read_pdf(name):
    return spark.table(tbl(name)).toPandas()


def write_table(pdf, name, comment, replace_where=None):
    """Overwrite a bronze table from pandas (or replace only the rows matching `replace_where`)."""
    sdf = spark.createDataFrame(pdf)
    full = tbl(name)
    if replace_where and spark.catalog.tableExists(full):
        sdf.write.mode("overwrite").option("replaceWhere", replace_where).saveAsTable(full)
    else:
        sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(full)
    spark.sql(f"COMMENT ON TABLE {full} IS {json.dumps(comment)}")
    print(f"wrote {full}: {len(pdf):,} rows")


# COMMAND ----------

# MAGIC %md ## India boundaries (geoBoundaries gbOpen, pinned commit)
# MAGIC
# MAGIC * ADM1 (36 states/UTs): source DataMeet India / Election Commission of India, CC BY 2.5 IN
# MAGIC * ADM2 (735 districts, 2021): source Pathways Data / lgdirectory.gov.in, ODbL 1.0
# MAGIC
# MAGIC These are *simplified* polygons, good enough for assignment and maps but not survey-grade. Points just
# MAGIC offshore are snapped to the nearest polygon within `coastal_snap_km` (see `locate_points`).

# COMMAND ----------

GEO_COMMIT = "9469f09"
GEO_URLS = {
    lvl: f"https://github.com/wmgeolab/geoBoundaries/raw/{GEO_COMMIT}/releaseData/gbOpen/IND/{lvl}/geoBoundaries-IND-{lvl}_simplified.geojson"
    for lvl in ("ADM1", "ADM2")
}
INDIA_EPSG = 7755  # WGS 84 / India NSF LCC, metres, used for nearest-polygon snapping


def geo_path(lvl):
    return f"{VOLUME_DIR}/geoBoundaries-IND-{lvl}_simplified.geojson"


def ensure_boundaries():
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {OUT_CATALOG}.{OUT_SCHEMA}.{VOLUME_NAME}")
    for lvl, url in GEO_URLS.items():
        if not os.path.exists(geo_path(lvl)):
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
            with open(geo_path(lvl), "wb") as f:
                f.write(data)
            print(f"downloaded {lvl}: {len(data)/1e6:.1f} MB -> {geo_path(lvl)}")


def load_adm1():
    g = gpd.read_file(geo_path("ADM1"))[["shapeName", "geometry"]].to_crs(4326)
    g["state"] = g["shapeName"].map(canon_state)
    missing = g[g["state"].isna()]
    assert missing.empty, f"ADM1 names not mapped to directory states: {missing.shapeName.tolist()}"
    return g


def load_adm2(adm1):
    g = gpd.read_file(geo_path("ADM2"))[["shapeName", "shapeID", "geometry"]].to_crs(4326)
    rp = g.copy()
    rp["geometry"] = g.geometry.representative_point()
    j = gpd.sjoin(rp, adm1[["state", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    g["state"] = j["state"]
    g["adm2_label"] = g["state"].fillna("(no state)") + " | " + g["shapeName"].map(norm_text)
    return g


# COMMAND ----------

# MAGIC %md ## State names
# MAGIC
# MAGIC Canonical spelling = the India Post directory's `statename` (upper case). `STATE_ALIASES` holds only
# MAGIC **state-level** spelling variants and former/merged names. City or district names typed into
# MAGIC `address_stateOrRegion` are deliberately *not* mapped; they stay `(unresolved text)` so the team can see
# MAGIC them (notebook 06 lists them).

# COMMAND ----------

CANON_STATES = [
    "ANDAMAN AND NICOBAR ISLANDS", "ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM", "BIHAR", "CHANDIGARH",
    "CHHATTISGARH", "DELHI", "GOA", "GUJARAT", "HARYANA", "HIMACHAL PRADESH", "JAMMU AND KASHMIR", "JHARKHAND",
    "KARNATAKA", "KERALA", "LADAKH", "LAKSHADWEEP", "MADHYA PRADESH", "MAHARASHTRA", "MANIPUR", "MEGHALAYA",
    "MIZORAM", "NAGALAND", "ODISHA", "PUDUCHERRY", "PUNJAB", "RAJASTHAN", "SIKKIM", "TAMIL NADU", "TELANGANA",
    "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU", "TRIPURA", "UTTAR PRADESH", "UTTARAKHAND", "WEST BENGAL",
]
DNHDD = "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"
STATE_ALIASES = {
    "TAMILNADU": "TAMIL NADU",
    "ORISSA": "ODISHA",                      # renamed 2011
    "PONDICHERRY": "PUDUCHERRY",             # renamed 2006
    "UTTARANCHAL": "UTTARAKHAND",            # renamed 2007
    "CHATTISGARH": "CHHATTISGARH",
    "CHHATISGARH": "CHHATTISGARH",
    "UP": "UTTAR PRADESH",
    "NCT OF DELHI": "DELHI",
    "JAMMU KASHMIR": "JAMMU AND KASHMIR",
    "ANDAMAN AND NICOBAR": "ANDAMAN AND NICOBAR ISLANDS",
    "DADRA AND NAGAR HAVELI AND DAMAN AND DIU": DNHDD,
    "DADRA AND NAGAR HAVELI": DNHDD,         # merged into DNH&DD in 2020
    "DAMAN AND DIU": DNHDD,                  # merged into DNH&DD in 2020
}
UNRESOLVED_STATE = "(unresolved text)"
UNASSIGNED = "(unassigned)"

# Zonal Councils (States Reorganisation Act 1956 + North Eastern Council Act 1971).
# Andaman & Nicobar and Lakshadweep are special invitees, not members, so they get their own label.
ZONAL_COUNCIL = {
    **{s: "Northern" for s in ["HARYANA", "HIMACHAL PRADESH", "PUNJAB", "RAJASTHAN", "DELHI", "CHANDIGARH",
                                 "JAMMU AND KASHMIR", "LADAKH"]},
    **{s: "Central" for s in ["CHHATTISGARH", "UTTARAKHAND", "UTTAR PRADESH", "MADHYA PRADESH"]},
    **{s: "Eastern" for s in ["BIHAR", "JHARKHAND", "ODISHA", "WEST BENGAL"]},
    **{s: "Western" for s in ["GOA", "GUJARAT", "MAHARASHTRA", DNHDD]},
    **{s: "Southern" for s in ["ANDHRA PRADESH", "KARNATAKA", "KERALA", "TAMIL NADU", "TELANGANA", "PUDUCHERRY"]},
    **{s: "North Eastern" for s in ["ASSAM", "ARUNACHAL PRADESH", "MANIPUR", "MEGHALAYA", "MIZORAM", "NAGALAND",
                                      "TRIPURA", "SIKKIM"]},
    "ANDAMAN AND NICOBAR ISLANDS": "Islands (no zonal council)",
    "LAKSHADWEEP": "Islands (no zonal council)",
}
assert set(ZONAL_COUNCIL) == set(CANON_STATES)


def norm_text(s):
    """Upper-case, strip diacritics, '&'->AND, drop dots, collapse non-alphanumerics to single spaces."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return None
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = s.replace("&", " AND ").replace(".", "")
    s = re.sub(r"[^A-Z0-9]+", " ", s).strip()
    return s or None


def canon_state(s):
    n = norm_text(s)
    if n is None:
        return None
    if n in CANON_STATES:
        return n
    return STATE_ALIASES.get(n)


def stated_state_label(s):
    n = norm_text(s)
    if n is None or n in ("NULL", "NONE", "NA", "N A"):
        return None
    return canon_state(s) or UNRESOLVED_STATE


def zone_of(state):
    return ZONAL_COUNCIL.get(state) if isinstance(state, str) else None


# COMMAND ----------

# MAGIC %md ## Geometry and distance helpers

# COMMAND ----------

EARTH_R_KM = 6371.0088
KM_PER_DEG = math.pi * EARTH_R_KM / 180.0
THRESHOLDS_KM = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000]
BUCKETS = [(0, 1, "<1 km"), (1, 5, "1-5 km"), (5, 25, "5-25 km"), (25, 100, "25-100 km"),
           (100, 500, "100-500 km"), (500, np.inf, ">500 km")]
BUCKET_LABELS = [b[2] for b in BUCKETS]


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial compass bearing from point 1 to point 2 (0 = north, 90 = east)."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2))
    y = np.sin(lon2 - lon1) * np.cos(lat2)
    x = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(lon2 - lon1)
    return (np.degrees(np.arctan2(y, x)) + 360) % 360


def bucket_of(d):
    d = np.asarray(d, dtype=float)
    out = np.full(d.shape, None, dtype=object)
    for lo, hi, lab in BUCKETS:
        out[(d >= lo) & (d < hi)] = lab
    return out


def locate_points(lat, lon, adm2, snap_km):
    """Assign each point to an ADM2 polygon (and its state).

    status: MISSING (no numeric coords), WITHIN (inside a polygon), SNAPPED (outside all polygons but within
    snap_km of one, typically coast/simplification error), OUTSIDE_INDIA (farther than snap_km from India).
    """
    df = pd.DataFrame({"lat": pd.to_numeric(pd.Series(lat), errors="coerce").to_numpy(),
                       "lon": pd.to_numeric(pd.Series(lon), errors="coerce").to_numpy()})
    res = pd.DataFrame({"loc_status": "MISSING", "adm_state": None, "adm2_label": None}, index=df.index)
    valid = df.lat.between(-90, 90) & df.lon.between(-180, 180)
    if not valid.any():
        return res
    g = gpd.GeoDataFrame(df[valid], geometry=gpd.points_from_xy(df.lon[valid], df.lat[valid]), crs=4326)
    a2 = adm2[["adm2_label", "state", "geometry"]]
    j = gpd.sjoin(g, a2, how="left", predicate="within")
    j = j[~j.index.duplicated()]
    hit = j["adm2_label"].notna()
    res.loc[j.index[hit], "loc_status"] = "WITHIN"
    res.loc[j.index[hit], "adm_state"] = j.loc[hit, "state"].to_numpy()
    res.loc[j.index[hit], "adm2_label"] = j.loc[hit, "adm2_label"].to_numpy()
    miss_idx = j.index[~hit]
    if len(miss_idx):
        gp = g.loc[miss_idx].to_crs(INDIA_EPSG)
        n = gpd.sjoin_nearest(gp, a2.to_crs(INDIA_EPSG), how="left", max_distance=snap_km * 1000)
        n = n[~n.index.duplicated()]
        snapped = n["adm2_label"].notna()
        res.loc[n.index[snapped], "loc_status"] = "SNAPPED"
        res.loc[n.index[snapped], "adm_state"] = n.loc[snapped, "state"].to_numpy()
        res.loc[n.index[snapped], "adm2_label"] = n.loc[snapped, "adm2_label"].to_numpy()
        res.loc[n.index[~snapped], "loc_status"] = "OUTSIDE_INDIA"
    # numeric but out of lat/lon range is also "outside India"
    res.loc[df.lat.notna() & df.lon.notna() & ~valid, "loc_status"] = "OUTSIDE_INDIA"
    return res


def point_status(loc_status):
    return np.where(pd.Series(loc_status).isin(["WITHIN", "SNAPPED"]), "OK", pd.Series(loc_status))


def gdf_from_wkt(pdf, col="geometry_wkt"):
    return gpd.GeoDataFrame(pdf.drop(columns=[col]), geometry=gpd.GeoSeries.from_wkt(pdf[col]), crs=4326)


# COMMAND ----------

# MAGIC %md ## Visual style
# MAGIC
# MAGIC * Distance buckets are ordered magnitude, so they use one sequential blue ramp (light = close, dark = far).
# MAGIC * Non-OK linkage categories use two categorical hues (orange = the pincode side is unusable, so the
# MAGIC   facility point is drawn; aqua = the facility coordinates are unusable, so the pincode point is drawn),
# MAGIC   with marker **shape** as the secondary encoding for the sub-category.
# MAGIC * Mean vs median: categorical slot 1 (blue) and slot 2 (orange).

# COMMAND ----------

BUCKET_COLORS = dict(zip(BUCKET_LABELS, ["#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"]))
SEQ_BLUE = [[0.0, "#cde2fb"], [0.17, "#9ec5f4"], [0.33, "#6da7ec"], [0.5, "#3987e5"],
            [0.67, "#256abf"], [0.83, "#184f95"], [1.0, "#0d366b"]]
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STRATEGY_COLORS = dict(zip(STRATEGIES, SERIES))
PIN_BAD_COLOR, FAC_BAD_COLOR = "#eb6834", "#1baf7a"
PIN_BAD_SYMBOLS = {"MISSING": "x", "MALFORMED": "triangle-up", "NOT_IN_DIRECTORY": "square",
                   "NO_GEOCODED_OFFICES": "diamond", "NO_POINT_FOR_STRATEGY": "star"}
FAC_BAD_SYMBOLS = {"MISSING": "circle-open", "OUTSIDE_INDIA": "cross"}
MPL_MARKERS = {"x": "x", "triangle-up": "^", "square": "s", "diamond": "D", "star": "*",
               "circle-open": "o", "cross": "P"}
GRID_COLOR = "#e4e3df"
BASEMAP_EDGE = "#b5b4ae"
PLOTLY_TEMPLATE = "plotly_white"


def show(fig, height=None):
    fig.update_layout(template=PLOTLY_TEMPLATE, font=dict(size=12), margin=dict(l=10, r=10, t=60, b=10))
    if height:
        fig.update_layout(height=height)
    fig.show()


def outline_lines(gdf, tolerance=0.01):
    """Flatten polygon boundaries into lon/lat lists separated by None (one Scattergeo trace)."""
    lons, lats = [], []
    for geom in gdf.geometry.simplify(tolerance):
        if geom is None or geom.is_empty:
            continue
        b = geom.boundary
        for line in getattr(b, "geoms", [b]):
            xs, ys = line.xy
            lons += list(xs) + [None]
            lats += list(ys) + [None]
    return lons, lats


def india_geo_layout(fig, title):
    fig.update_geos(projection_type="mercator", lataxis_range=[6, 37.5], lonaxis_range=[67.5, 98],
                    showcountries=False, showcoastlines=False, showland=True, landcolor="#f7f7f5",
                    showocean=True, oceancolor="#fcfcfb", bgcolor="#fcfcfb")
    fig.update_layout(title=title, legend=dict(itemsizing="constant"))


# COMMAND ----------

# MAGIC %md ## Region scheme registry
# MAGIC
# MAGIC Every scheme has three label columns in `bronze_loclink_facility_regions`:
# MAGIC
# MAGIC * `<scheme>`: the region by the scheme's own definition (what the notebook groups by)
# MAGIC * `<scheme>__fac_pt`: the region the **facility's own coordinates** fall in
# MAGIC * `<scheme>__pin_pt`: the region the **pincode's office_median point** falls in
# MAGIC
# MAGIC For postal schemes and directory districts, "falls in" uses approximate region polygons: each ADM2
# MAGIC district polygon takes the label held by most geocoded post offices inside it (`adm2_majority`).

# COMMAND ----------

SCHEMES = {
    "postal_circle": dict(
        title="India Post circle", n_hint="~24",
        definition="Modal `circlename` across all directory offices that share the facility's pincode.",
        shapes="adm2_majority (approximate)"),
    "postal_region": dict(
        title="India Post region", n_hint="~53",
        definition="Modal `regionname` across all directory offices that share the facility's pincode.",
        shapes="adm2_majority (approximate)"),
    "postal_division": dict(
        title="India Post division", n_hint="~450",
        definition="Modal `divisionname` across all directory offices that share the facility's pincode.",
        shapes="adm2_majority (approximate; divisions smaller than a district are merged)"),
    "dir_state": dict(
        title="State/UT per pincode directory", n_hint="36",
        definition="Modal `statename` across all directory offices that share the facility's pincode.",
        shapes="ADM1 polygons"),
    "dir_district": dict(
        title="District per pincode directory", n_hint="~750",
        definition="Modal `statename | district` across all directory offices that share the facility's pincode.",
        shapes="adm2_majority (approximate; directory district names are not joined to ADM2 names by text)"),
    "fac_stated_state": dict(
        title="State/UT as written on the facility record", n_hint="36 + unresolved",
        definition="`address_stateOrRegion` normalised to directory spelling; city/district text stays "
                   "`(unresolved text)`.",
        shapes="ADM1 polygons"),
    "spatial_state": dict(
        title="State/UT containing the facility coordinates", n_hint="36",
        definition="ADM1 polygon containing (or within `coastal_snap_km` of) the facility latitude/longitude.",
        shapes="ADM1 polygons"),
    "spatial_district": dict(
        title="District (ADM2) containing the facility coordinates", n_hint="~735",
        definition="ADM2 polygon containing (or within `coastal_snap_km` of) the facility latitude/longitude.",
        shapes="ADM2 polygons"),
    "zonal_council": dict(
        title="Zonal Council (broad zone)", n_hint="6 + islands",
        definition="Zonal Council of the pincode-directory state (`dir_state`). Notebook 09 also compares the "
                   "zone under the other state sources.",
        shapes="ADM1 polygons dissolved by zone"),
    "h3_grid": dict(
        title="H3 hexagon grid (administration-free)", n_hint="depends on resolution",
        definition="H3 cell (resolution `h3_res` from notebook 00) containing the facility coordinates. Equal-area "
                   "cells remove any dependence on administrative boundaries.",
        shapes="H3 cell boundaries"),
    # Urban-centre schemes: built by notebook 13 from GHSL (not by 00), passed to RegionAnalysis via extra_labels
    "urban_tier_fac_end": dict(
        title="Urban-centre population tier at the facility point", n_hint="3 tiers + outside",
        definition="Population band of the GHSL urban centre (2025) whose polygon contains the facility coordinates; "
                   "`(outside urban centres)` otherwise.",
        shapes="GHSL UCDB R2024A polygons dissolved by tier"),
    "urban_tier_pin_end": dict(
        title="Urban-centre population tier at the pincode point", n_hint="3 tiers + outside",
        definition="Population band of the GHSL urban centre (2025) whose polygon contains the pincode point "
                   "(primary strategy); `(outside urban centres)` otherwise.",
        shapes="GHSL UCDB R2024A polygons dissolved by tier"),
    "urban_centre_fac_end": dict(
        title="Urban centre containing the facility point", n_hint="~1,900 + outside",
        definition="GHSL urban centre (2025) whose polygon contains the facility coordinates; "
                   "`(outside urban centres)` otherwise.",
        shapes="GHSL UCDB R2024A polygons"),
    "urban_centre_pin_end": dict(
        title="Urban centre containing the pincode point", n_hint="~1,900 + outside",
        definition="GHSL urban centre (2025) whose polygon contains the pincode point (primary strategy); "
                   "`(outside urban centres)` otherwise.",
        shapes="GHSL UCDB R2024A polygons"),
}

# COMMAND ----------

# MAGIC %md ## `RegionAnalysis`

# COMMAND ----------

def circular_mean_deg(b):
    b = np.radians(np.asarray(b, dtype=float))
    if len(b) == 0:
        return np.nan, np.nan
    s, c = np.sin(b).mean(), np.cos(b).mean()
    return (np.degrees(np.arctan2(s, c)) + 360) % 360, float(np.hypot(s, c))


def dist_stats(g):
    x = g["dist_km"].to_numpy(dtype=float)
    out = {"n_pairs": len(x)}
    if len(x) == 0:
        return pd.Series(out)
    q = np.percentile(x, [5, 10, 25, 50, 75, 90, 95, 99])
    out.update(mean_km=x.mean(), std_km=x.std(ddof=1) if len(x) > 1 else np.nan, min_km=x.min(),
               p05_km=q[0], p10_km=q[1], p25_km=q[2], median_km=q[3], p75_km=q[4], p90_km=q[5],
               p95_km=q[6], p99_km=q[7], max_km=x.max(), iqr_km=q[4] - q[2])
    for t in THRESHOLDS_KM:
        out[f"n_gt_{t}km"] = int((x > t).sum())
        out[f"pct_gt_{t}km"] = 100.0 * (x > t).mean()
    out["mean_d_north_km"] = g["d_north_km"].mean()
    out["mean_d_east_km"] = g["d_east_km"].mean()
    out["median_d_north_km"] = g["d_north_km"].median()
    out["median_d_east_km"] = g["d_east_km"].median()
    far = g[g["dist_km"] >= 1]
    mb, r = circular_mean_deg(far["bearing_deg"])
    out["mean_bearing_deg_ge1km"] = mb
    out["bearing_resultant_R_ge1km"] = r  # 0 = directions random, 1 = all offsets point the same way
    for col in ("swap_suspect", "within_pin_footprint"):
        out[f"pct_{col}"] = 100.0 * g[col].fillna(False).astype(bool).mean() if col in g else np.nan
    return pd.Series(out)


class RegionAnalysis:
    """All tables/visuals for one region scheme. Call the methods cell by cell from a region notebook."""

    def __init__(self, scheme, strategy=None, max_region_panels=36, min_n_panels=5, max_bars=60,
                 extra_labels=None, extra_shapes=None):
        """extra_labels: optional pandas frame (fac_row_id + `<scheme>`, `<scheme>__fac_pt`, `<scheme>__pin_pt`)
        for a scheme computed outside notebook 00. extra_shapes: optional GeoDataFrame (region, geometry)."""
        self.scheme = scheme
        self.cfg = SCHEMES[scheme]
        self.strategy = strategy or PRIMARY_STRATEGY
        self.max_region_panels = max_region_panels
        self.min_n_panels = min_n_panels
        self.max_bars = max_bars

        fr = read_pdf("facility_regions")
        if extra_labels is not None:
            fr = fr.drop(columns=[c for c in extra_labels.columns if c != "fac_row_id" and c in fr.columns])
            fr = fr.merge(extra_labels, on="fac_row_id", how="left")
        fr["region"] = fr[scheme].fillna(UNASSIGNED)
        self.fr = fr
        pairs = read_pdf("pairs")
        keep = ["fac_row_id", "region", "unique_id", "name", "address_city", "address_stateOrRegion",
                "pin_clean", "fac_point_status", "pin_status", "within_pin_footprint", "pin_spread_max_km",
                f"{scheme}__fac_pt", f"{scheme}__pin_pt"]
        self.pairs = pairs.merge(fr[[c for c in keep if c in fr.columns]], on="fac_row_id", how="left")
        self.prim_all = self.pairs[self.pairs["strategy"] == self.strategy].copy()
        self.ok_all = self.pairs[self.pairs["pair_category"] == "FAC_OK__PIN_OK"].copy()
        self.prim = self.prim_all[self.prim_all["pair_category"] == "FAC_OK__PIN_OK"].copy()
        self.prim["bucket"] = pd.Categorical(self.prim["bucket"], BUCKET_LABELS, ordered=True)

        shapes = read_pdf("region_shapes")
        if extra_shapes is not None:
            self.shapes = extra_shapes
        else:
            self.shapes = gdf_from_wkt(shapes[shapes["scheme"] == scheme]) if (shapes["scheme"] == scheme).any() else None
        st = shapes[shapes["scheme"] == "dir_state"]
        self.basemap = gdf_from_wkt(st)
        self.summary = None

    # ------------------------------------------------------------------ overview
    def overview(self):
        n_rows, n_regions = len(self.fr), self.fr["region"].nunique()
        cat = self.prim_all["pair_category"].value_counts().rename_axis("pair_category").reset_index(name="facility_rows")
        cat["pct"] = (100 * cat["facility_rows"] / n_rows).round(2)
        displayHTML(f"""
        <h3>{self.cfg['title']}</h3>
        <p><b>Region definition:</b> {self.cfg['definition']}<br>
        <b>Region outlines:</b> {self.cfg['shapes']}<br>
        <b>Pincode point strategy (maps & primary tables):</b> <code>{self.strategy}</code>, {STRATEGY_HELP[self.strategy]}<br>
        <b>Facility rows:</b> {n_rows:,} &nbsp; <b>Distinct regions (incl. {UNASSIGNED}):</b> {n_regions:,}
        &nbsp; <b>Usable pairs (FAC_OK__PIN_OK):</b> {len(self.prim):,}</p>
        <p>Pair category = <code>FAC_&lt;facility-coordinate status&gt;__PIN_&lt;pincode status&gt;</code>.
        Offsets are measured <b>from the pincode point to the facility point</b>: bearing 0 means the facility
        sits north of its pincode point.</p>""")
        display(cat)

    # ------------------------------------------------------------------ coverage
    def coverage(self):
        """Linkage category counts per region (primary strategy), including every non-OK category."""
        cov = (self.prim_all.groupby(["region", "pair_category"]).size().unstack(fill_value=0))
        cov["total"] = cov.sum(axis=1)
        ok = cov["FAC_OK__PIN_OK"] if "FAC_OK__PIN_OK" in cov else 0
        cov["pct_usable_pairs"] = (100 * ok / cov["total"]).round(1)
        cov = cov.sort_values("total", ascending=False)
        display(cov.reset_index())

        top = cov.head(self.max_bars).drop(columns=["total", "pct_usable_pairs"])
        long = top.reset_index().melt(id_vars="region", var_name="pair_category", value_name="n")
        order = ["FAC_OK__PIN_OK"] + sorted(c for c in long["pair_category"].unique() if c != "FAC_OK__PIN_OK")
        palette = dict(zip(order, ["#2a78d6"] + SERIES[1:] + ["#9a9994"] * 20))
        fig = px.bar(long, y="region", x="n", color="pair_category", orientation="h",
                     category_orders={"region": list(top.index), "pair_category": order},
                     color_discrete_map=palette,
                     title=f"Linkage category per region, {self.cfg['title']} (top {len(top)} by facility count)")
        fig.update_traces(marker_line_color="#fcfcfb", marker_line_width=1)
        show(fig, height=max(400, 18 * len(top) + 150))
        return cov

    # ------------------------------------------------------------------ stats
    def summary_stats(self, write=True):
        """Full distance breakdown per region x strategy (+ an ALL row), persisted to region_summary."""
        rows = []
        for strat, g in self.ok_all.groupby("strategy"):
            per = g.groupby("region").apply(dist_stats)
            per.loc["ALL (national)"] = dist_stats(g)
            per = per.reset_index().rename(columns={"index": "region"})
            per.insert(0, "strategy", strat)
            rows.append(per)
        s = pd.concat(rows, ignore_index=True)
        cov = self.prim_all.groupby("region").size()
        s["facility_rows_in_region"] = s["region"].map(cov).fillna(len(self.prim_all)).astype(int)
        s.insert(0, "scheme", self.scheme)
        for c in s.columns:  # stable types so every scheme's rows fit one Delta schema
            if c in ("scheme", "strategy", "region"):
                s[c] = s[c].astype(str)
            elif c.startswith("n_") or c == "facility_rows_in_region":
                s[c] = s[c].fillna(0).astype("int64")
            else:
                s[c] = s[c].astype("float64")
        self.summary = s
        if write:
            write_table(s, "region_summary",
                        "Distance between facility coordinates and pincode point: per region scheme x region x "
                        "pincode-point strategy. One block of rows per scheme, replaced on each notebook run.",
                        replace_where=f"scheme = '{self.scheme}'")
        prim = s[s["strategy"] == self.strategy].sort_values("median_km", ascending=False)
        display(prim)
        return s

    def average_by_region(self):
        """Headline table + chart: average (mean) and median difference per region."""
        if self.summary is None:
            self.summary_stats(write=False)
        p = self.summary[(self.summary["strategy"] == self.strategy) & (self.summary["region"] != "ALL (national)")]
        p = p.sort_values("median_km", ascending=False)
        cols = ["region", "n_pairs", "mean_km", "median_km", "p25_km", "p75_km", "p90_km", "max_km",
                "pct_gt_5km", "pct_gt_25km", "pct_gt_100km"]
        display(p[cols].round(2))
        nat = self.summary[(self.summary["strategy"] == self.strategy) & (self.summary["region"] == "ALL (national)")]
        top = p.head(self.max_bars)
        fig = go.Figure()
        fig.add_bar(y=top["region"], x=top["mean_km"], name="Mean", orientation="h", marker_color=SERIES[0],
                    customdata=top[["n_pairs"]], hovertemplate="%{y}<br>mean %{x:.1f} km<br>n=%{customdata[0]}<extra></extra>")
        fig.add_bar(y=top["region"], x=top["median_km"], name="Median", orientation="h", marker_color=SERIES[1],
                    error_x=dict(type="data", symmetric=False, array=top["p75_km"] - top["median_km"],
                                 arrayminus=top["median_km"] - top["p25_km"], color="#52514e", thickness=1),
                    customdata=top[["p25_km", "p75_km", "n_pairs"]],
                    hovertemplate="%{y}<br>median %{x:.1f} km (IQR %{customdata[0]:.1f}-%{customdata[1]:.1f})<br>n=%{customdata[2]}<extra></extra>")
        if not nat.empty:
            fig.add_vline(x=float(nat["median_km"].iloc[0]), line_dash="dot", line_color="#52514e",
                          annotation_text=f"national median {float(nat['median_km'].iloc[0]):.1f} km")
        fig.update_layout(barmode="group", xaxis_type="log", xaxis_title="km (log scale)",
                          yaxis=dict(categoryorder="array", categoryarray=list(top["region"])[::-1]),
                          title=f"Mean vs median facility-to-pincode distance, {self.cfg['title']} "
                                f"(sorted by median; whiskers = IQR; top {len(top)})")
        show(fig, height=max(450, 22 * len(top) + 150))

    def distribution(self):
        """Box plot of distances per region (log scale), ordered by median."""
        d = self.prim.copy()
        d["dist_plot"] = d["dist_km"].clip(lower=0.01)
        n = d.groupby("region").size()
        regions = n[n >= 1].index
        if len(regions) > self.max_bars:
            regions = n.sort_values(ascending=False).head(self.max_bars).index
        d = d[d["region"].isin(regions)]
        order = d.groupby("region")["dist_km"].median().sort_values(ascending=False).index.tolist()
        fig = px.box(d, y="region", x="dist_plot", orientation="h", log_x=True, points="outliers",
                     category_orders={"region": order}, hover_data=["name", "pin_clean", "dist_km"],
                     color_discrete_sequence=[SERIES[0]],
                     title=f"Distance distribution per region, {self.cfg['title']} (distances <0.01 km shown at 0.01)")
        fig.update_layout(xaxis_title="km (log scale)")
        show(fig, height=max(450, 22 * len(order) + 150))

        nat = self.prim["dist_km"].clip(lower=0.01)
        fig = px.ecdf(x=nat, log_x=True, color_discrete_sequence=[SERIES[0]],
                      title="National cumulative distribution of distance (what share of pairs fall within X km)")
        for t in [1, 5, 25, 100]:
            fig.add_vline(x=t, line_dash="dot", line_color="#9a9994", annotation_text=f"{t} km")
        fig.update_layout(xaxis_title="km (log scale)", yaxis_title="share of usable pairs")
        show(fig, height=420)

    def threshold_heatmap(self):
        """% of pairs exceeding each threshold, per region."""
        if self.summary is None:
            self.summary_stats(write=False)
        p = self.summary[self.summary["strategy"] == self.strategy].sort_values("median_km", ascending=False)
        p = p.head(self.max_bars + 1)
        cols = [f"pct_gt_{t}km" for t in THRESHOLDS_KM]
        z = p[cols].to_numpy()
        fig = px.imshow(z, x=[f">{t} km" for t in THRESHOLDS_KM], y=p["region"], color_continuous_scale=SEQ_BLUE,
                        zmin=0, zmax=100, aspect="auto", text_auto=".0f",
                        labels=dict(color="% of pairs"),
                        title=f"% of usable pairs beyond each distance, {self.cfg['title']}")
        show(fig, height=max(450, 20 * len(p) + 150))

    # ------------------------------------------------------------------ maps
    def choropleth(self):
        """Region polygons shaded by median distance (log colour)."""
        if self.shapes is None or self.shapes.empty:
            print("No polygons for this scheme.")
            return
        if self.summary is None:
            self.summary_stats(write=False)
        p = self.summary[self.summary["strategy"] == self.strategy].set_index("region")
        g = self.shapes.copy()
        g["geometry"] = g.geometry.simplify(0.01)
        g = g[g["region"].isin(p.index)]
        gj = json.loads(g[["region", "geometry"]].to_json())
        med = p.loc[g["region"], "median_km"].to_numpy()
        z = np.log10(np.clip(med, 0.01, None))
        cand = [0.1, 0.2, 0.5, 1, 1.5, 2, 3, 5, 10, 25, 50, 100, 250, 500, 1000]
        ticks = [t for t in cand if np.nanmin(med) * 0.9 <= t <= np.nanmax(med) * 1.1] or [round(float(np.nanmedian(med)), 1)]
        fig = go.Figure(go.Choropleth(
            geojson=gj, locations=g["region"], featureidkey="properties.region", z=z,
            colorscale=SEQ_BLUE, marker_line_color="#fcfcfb", marker_line_width=0.6,
            colorbar=dict(title="median km", tickvals=[float(np.log10(t)) for t in ticks], ticktext=[f"{t:g}" for t in ticks]),
            customdata=np.stack([med, p.loc[g["region"], "mean_km"], p.loc[g["region"], "n_pairs"]], axis=1),
            hovertemplate="%{location}<br>median %{customdata[0]:.1f} km<br>mean %{customdata[1]:.1f} km"
                          "<br>n=%{customdata[2]}<extra></extra>"))
        india_geo_layout(fig, f"Median facility-to-pincode distance by region, {self.cfg['title']}")
        unshaded = sorted(set(p.index) - set(g["region"]) - {"ALL (national)"})
        if unshaded:
            print(f"{len(unshaded)} regions have stats but no polygon: {unshaded[:20]}{' ...' if len(unshaded) > 20 else ''}")
        show(fig, height=750)

    def _category_points(self):
        """Non-OK facility rows with whichever single point exists, for plotting."""
        d = self.prim_all[self.prim_all["pair_category"] != "FAC_OK__PIN_OK"].copy()
        pin_bad = d[(d["fac_point_status"] == "OK")].copy()
        pin_bad["plot_lat"], pin_bad["plot_lon"] = pin_bad["fac_lat"], pin_bad["fac_lon"]
        pin_bad["kind"] = "pin unusable: facility point shown"
        pin_bad["sub"] = pin_bad["pin_point_status"]
        fac_bad = d[(d["fac_point_status"] != "OK") & d["pin_lat"].notna()].copy()
        fac_bad["plot_lat"], fac_bad["plot_lon"] = fac_bad["pin_lat"], fac_bad["pin_lon"]
        fac_bad["kind"] = "facility coords unusable: pincode point shown"
        fac_bad["sub"] = fac_bad["fac_point_status"]
        neither = d[(d["fac_point_status"] != "OK") & d["pin_lat"].isna()]
        return pin_bad, fac_bad, neither

    def pairs_map(self, min_line_km=5, underlay_traces=None, overlay_traces=None, title=None):
        """National interactive map: every usable pair as a line (pincode point -> facility point) coloured by
        distance bucket, a dot at the facility end, plus all non-OK categories at whichever point exists.
        underlay_traces / overlay_traces: extra plotly geo traces drawn below / above the pairs."""
        fig = go.Figure()
        for t in underlay_traces or []:
            fig.add_trace(t)
        if self.shapes is not None and not self.shapes.empty and len(self.shapes) <= 800:
            lo, la = outline_lines(self.shapes, 0.02)
            fig.add_trace(go.Scattergeo(lon=lo, lat=la, mode="lines", line=dict(width=0.5, color=BASEMAP_EDGE),
                                        name="region outlines", hoverinfo="skip"))
        for lab in BUCKET_LABELS:
            b = self.prim[self.prim["bucket"] == lab]
            if b.empty:
                continue
            lines = b[b["dist_km"] >= min_line_km]
            if len(lines):
                lon = np.column_stack([lines["pin_lon"], lines["fac_lon"], np.full(len(lines), np.nan)]).ravel()
                lat = np.column_stack([lines["pin_lat"], lines["fac_lat"], np.full(len(lines), np.nan)]).ravel()
                fig.add_trace(go.Scattergeo(lon=lon, lat=lat, mode="lines", legendgroup=lab, showlegend=False,
                                            line=dict(width=1, color=BUCKET_COLORS[lab]), opacity=0.7,
                                            hoverinfo="skip"))
            fig.add_trace(go.Scattergeo(
                lon=b["fac_lon"], lat=b["fac_lat"], mode="markers", legendgroup=lab, name=f"pair {lab} (n={len(b)})",
                marker=dict(size=4, color=BUCKET_COLORS[lab], line=dict(width=0)),
                customdata=np.stack([b["name"].fillna(""), b["pin_clean"].fillna(""), b["dist_km"], b["region"]], axis=1),
                hovertemplate="%{customdata[0]}<br>pin %{customdata[1]} - %{customdata[3]}<br>%{customdata[2]:.1f} km<extra></extra>"))
        pin_bad, fac_bad, neither = self._category_points()
        for frame, color, symbols in ((pin_bad, PIN_BAD_COLOR, PIN_BAD_SYMBOLS), (fac_bad, FAC_BAD_COLOR, FAC_BAD_SYMBOLS)):
            for sub, g in frame.groupby("sub"):
                g = g[g["plot_lat"].between(-90, 90) & g["plot_lon"].between(-180, 180)]
                fig.add_trace(go.Scattergeo(
                    lon=g["plot_lon"], lat=g["plot_lat"], mode="markers",
                    name=f"{g['kind'].iloc[0] if len(g) else ''} [{sub}] (n={len(g)})",
                    marker=dict(size=7, color=color, symbol=symbols.get(sub, "circle"), line=dict(width=1, color=color)),
                    customdata=np.stack([g["name"].fillna(""), g["pin_clean"].fillna(""), g["region"]], axis=1) if len(g) else None,
                    hovertemplate="%{customdata[0]}<br>pin %{customdata[1]} - %{customdata[2]}<extra></extra>"))
        for t in overlay_traces or []:
            fig.add_trace(t)
        india_geo_layout(fig, title or f"Pincode point -> facility point, {self.cfg['title']} "
                                       f"(lines drawn for pairs >= {min_line_km} km; {len(neither)} rows have neither point)")
        show(fig, height=850)

    def region_panels(self, regions=None, cols=4, frame_mode="shape+points", pad_frac=0.15):
        """Small multiples: one zoomed map per region with its outline, its pairs and its non-OK points.
        frame_mode="shape+points": largest polygon part extended to the central 90% of pincode points (default).
        frame_mode="shape": the region's own polygon bounds only (for small regions like cities); the title then counts
        pairs with either end outside the frame."""
        if self.summary is None:
            self.summary_stats(write=False)
        p = self.summary[(self.summary["strategy"] == self.strategy) & (self.summary["region"] != "ALL (national)")]
        if regions is None:
            p = p[p["n_pairs"] >= self.min_n_panels].sort_values("median_km", ascending=False)
            regions = p["region"].head(self.max_region_panels).tolist()
            note = (f"{len(regions)} regions with >= {self.min_n_panels} usable pairs, worst median first"
                    f"{' (capped at ' + str(self.max_region_panels) + ')' if len(p) > self.max_region_panels else ''}")
        else:
            note = f"{len(regions)} selected regions"
        if not regions:
            print("No regions to draw.")
            return
        pin_bad, fac_bad, _ = self._category_points()
        rows = math.ceil(len(regions) / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 4.2 * rows), squeeze=False)
        for ax in axes.ravel()[len(regions):]:
            ax.axis("off")
        for ax, reg in zip(axes.ravel(), regions):
            d = self.prim[self.prim["region"] == reg]
            shape = self.shapes[self.shapes["region"] == reg] if self.shapes is not None else None
            # frame = largest polygon part of the region (stray mislabelled districts are ignored) extended to
            # cover the central 90% of its pincode points
            pts = d[["pin_lon", "pin_lat"]].dropna().to_numpy()
            boxes = []
            if frame_mode == "shape" and shape is not None and not shape.empty:
                boxes.append(tuple(shape.total_bounds))
            elif shape is not None and not shape.empty:
                parts = [p for geom in shape.geometry for p in getattr(geom, "geoms", [geom])]
                boxes.append(max(parts, key=lambda p: p.area).bounds)
            if len(pts) and (frame_mode != "shape" or not boxes):
                lo_, hi_ = np.nanpercentile(pts, 5, axis=0), np.nanpercentile(pts, 95, axis=0)
                boxes.append((lo_[0], lo_[1], hi_[0], hi_[1]))
            if not boxes:
                ax.axis("off")
                continue
            b_ = np.array(boxes)
            x0, y0, x1, y1 = b_[:, 0].min(), b_[:, 1].min(), b_[:, 2].max(), b_[:, 3].max()
            pad = max(x1 - x0, y1 - y0, 0.2) * pad_frac
            self.basemap.boundary.plot(ax=ax, color=BASEMAP_EDGE, linewidth=0.4)
            if shape is not None and not shape.empty:
                shape.plot(ax=ax, color="#eef4fc", edgecolor="#52514e", linewidth=1)
            for lab in BUCKET_LABELS:
                b = d[d["bucket"] == lab]
                if b.empty:
                    continue
                segs = np.stack([b[["pin_lon", "pin_lat"]].to_numpy(), b[["fac_lon", "fac_lat"]].to_numpy()], axis=1)
                ax.add_collection(LineCollection(segs, colors=BUCKET_COLORS[lab], linewidths=0.9, alpha=0.8))
                ax.scatter(b["fac_lon"], b["fac_lat"], s=6, color=BUCKET_COLORS[lab], zorder=3)
            for frame, color, symbols in ((pin_bad, PIN_BAD_COLOR, PIN_BAD_SYMBOLS), (fac_bad, FAC_BAD_COLOR, FAC_BAD_SYMBOLS)):
                f = frame[frame["region"] == reg]
                for sub, g in f.groupby("sub"):
                    sym = symbols.get(sub, "circle")
                    style = dict(facecolors="none", edgecolors=color) if sym == "circle-open" else dict(c=color)
                    ax.scatter(g["plot_lon"], g["plot_lat"], s=22, marker=MPL_MARKERS.get(sym, "o"), zorder=4, **style)
            def _outside(lon, lat):
                return (lon < x0 - pad) | (lon > x1 + pad) | (lat < y0 - pad) | (lat > y1 + pad)
            out_frame = _outside(d["fac_lon"], d["fac_lat"])
            if frame_mode == "shape":
                out_frame |= _outside(d["pin_lon"], d["pin_lat"])
            out_frame = int(out_frame.sum())
            ax.set_xlim(x0 - pad, x1 + pad)
            ax.set_ylim(y0 - pad, y1 + pad)
            ax.set_aspect(1 / max(math.cos(math.radians((y0 + y1) / 2)), 0.2))
            ax.set_xticks([]); ax.set_yticks([])
            med = d["dist_km"].median() if len(d) else float("nan")
            frame_lab = "an end outside frame" if frame_mode == "shape" else "leaving frame"
            ax.set_title(f"{reg[:38]}\nn={len(d)}  median={med:.1f} km  {frame_lab}={out_frame}", fontsize=9)
        handles = [plt.Line2D([], [], color=BUCKET_COLORS[l], lw=2, label=l) for l in BUCKET_LABELS]
        handles += [plt.Line2D([], [], color=PIN_BAD_COLOR, marker=MPL_MARKERS[v], ls="", label=f"pin {k}")
                    for k, v in PIN_BAD_SYMBOLS.items()]
        handles += [plt.Line2D([], [], color=FAC_BAD_COLOR, marker=MPL_MARKERS[v], ls="", label=f"facility {k}",
                               markerfacecolor="none" if v == "circle-open" else FAC_BAD_COLOR)
                    for k, v in FAC_BAD_SYMBOLS.items()]
        top_frac = 1 - 0.9 / (4.2 * rows)  # reserve ~0.9 inch for title + legend
        fig.tight_layout(rect=(0, 0, 1, top_frac))
        fig.legend(handles=handles, loc="lower center", ncol=7, fontsize=8, frameon=False,
                   bbox_to_anchor=(0.5, top_frac))
        fig.suptitle(f"{self.cfg['title']}: pairs per region ({note}). Line = pincode point -> facility point.",
                     y=0.995, fontsize=12)
        plt.show()

    # ------------------------------------------------------------------ direction
    def direction(self, min_km=1, panels=12):
        """Is the error directional? National + per-region bearing roses and the north/east offset scatter."""
        d = self.prim[self.prim["dist_km"] >= min_km].copy()
        d["bucket"] = d["bucket"].astype(str)  # plotly 5.9 fails on unused categorical levels
        present = [b for b in BUCKET_LABELS if b in set(d["bucket"])]
        fig = px.scatter(d, x="d_east_km", y="d_north_km", color="bucket", color_discrete_map=BUCKET_COLORS,
                         category_orders={"bucket": present}, hover_data=["name", "region", "pin_clean", "dist_km"],
                         title=f"Offset of facility from pincode point (km east / km north), pairs >= {min_km} km. "
                               "Clusters away from 0 = systematic shift; points near the diagonal y=x after a swap "
                               "suggest lat/lon swaps")
        fig.update_traces(marker=dict(size=5))
        lim = 2000
        fig.update_xaxes(type="linear", range=[-lim, lim]); fig.update_yaxes(range=[-lim, lim], scaleanchor="x")
        show(fig, height=700)

        top = (d.groupby("region").size().sort_values(ascending=False).head(panels).index.tolist())
        names = ["ALL (national)"] + top
        cols = 4
        rows = math.ceil(len(names) / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(3.6 * cols, 3.6 * rows), subplot_kw=dict(projection="polar"),
                                 squeeze=False)
        bins = np.linspace(0, 2 * np.pi, 17)
        for ax in axes.ravel()[len(names):]:
            ax.axis("off")
        for ax, reg in zip(axes.ravel(), names):
            g = d if reg == "ALL (national)" else d[d["region"] == reg]
            h, _ = np.histogram(np.radians(g["bearing_deg"]), bins=bins)
            ax.bar(bins[:-1], h / max(h.sum(), 1), width=np.diff(bins), align="edge", color=SERIES[0],
                   edgecolor="#fcfcfb", linewidth=1)
            ax.set_theta_zero_location("N"); ax.set_theta_direction(-1)
            ax.set_yticklabels([]); ax.tick_params(labelsize=7)
            mb, r = circular_mean_deg(g["bearing_deg"])
            ax.set_title(f"{reg[:30]}\nn={len(g)} R={r:.2f}", fontsize=9)
        fig.suptitle(f"Direction from pincode point to facility (pairs >= {min_km} km; R near 0 = no preferred "
                     "direction, near 1 = consistent shift)", fontsize=11)
        fig.tight_layout()
        plt.show()

    # ------------------------------------------------------------------ strategy sensitivity
    def strategy_sensitivity(self):
        """Median distance per region under every pincode-point strategy. Big spread = the conclusion depends on
        how we turn a pincode into a point (a team decision, see notebook 12)."""
        if self.summary is None:
            self.summary_stats(write=False)
        piv = self.summary.pivot_table(index="region", columns="strategy", values="median_km")
        piv = piv[[s for s in STRATEGIES if s in piv.columns]]
        piv["range_km"] = piv.max(axis=1) - piv.min(axis=1)
        piv = piv.sort_values(self.strategy if self.strategy in piv else piv.columns[0], ascending=False)
        display(piv.reset_index().round(2))
        z = piv.drop(columns="range_km").head(self.max_bars + 1)
        fig = px.imshow(np.log10(np.clip(z.to_numpy(), 0.01, None)), x=z.columns, y=z.index,
                        color_continuous_scale=SEQ_BLUE, aspect="auto",
                        title=f"Median km by pincode-point strategy, {self.cfg['title']} (colour = log10 km)")
        fig.update_traces(text=np.round(z.to_numpy(), 1), texttemplate="%{text}")
        show(fig, height=max(450, 20 * len(z) + 150))

    # ------------------------------------------------------------------ assignment agreement
    def assignment_agreement(self, top_flows=40):
        """Does the region by definition match the region the facility point / pincode point falls in?"""
        fr = self.fr
        comps = []
        for col, label in ((f"{self.scheme}__fac_pt", "facility point"), (f"{self.scheme}__pin_pt", "pincode point")):
            if col not in fr or fr[col].equals(fr[self.scheme]):
                continue
            both = fr[fr[self.scheme].notna() & fr[col].notna()]
            agree = (both[self.scheme] == both[col])
            comps.append(dict(comparison=f"definition vs region at {label}", rows_comparable=len(both),
                              agree=int(agree.sum()), disagree=int((~agree).sum()),
                              pct_agree=round(100 * agree.mean(), 2) if len(both) else np.nan))
            per = both.assign(agree=agree).groupby(self.scheme)["agree"].agg(["size", "mean"])
            per = per.rename(columns={"size": "rows", "mean": "share_agree"}).sort_values("share_agree")
            print(f"\nPer-region agreement: definition vs region at {label} (lowest first)")
            display(per.reset_index().round(3))
            flows = (both[~agree].groupby([self.scheme, col]).size().sort_values(ascending=False)
                     .head(top_flows).rename("rows").reset_index())
            flows.columns = [f"region by definition", f"region at {label}", "rows"]
            print(f"Most common disagreements ({label})")
            display(flows)
        if comps:
            display(pd.DataFrame(comps))
        else:
            print("Definition is itself spatial for this scheme; only the pincode-point comparison applies.")

    # ------------------------------------------------------------------ outliers
    def outliers(self, n=30):
        cols = ["region", "name", "address_city", "address_stateOrRegion", "pin_clean", "fac_lat", "fac_lon",
                "pin_lat", "pin_lon", "dist_km", "bearing_deg", "swap_suspect", "swapped_dist_km",
                "within_pin_footprint", "pin_spread_max_km", f"{self.scheme}__fac_pt"]
        cols = [c for c in cols if c in self.prim.columns]
        display(self.prim.sort_values("dist_km", ascending=False)[cols].head(n))

    def run_all(self):
        self.overview(); self.coverage(); self.summary_stats(); self.average_by_region(); self.distribution()
        self.threshold_heatmap(); self.choropleth(); self.pairs_map(); self.region_panels(); self.direction()
        self.strategy_sensitivity(); self.assignment_agreement(); self.outliers()
