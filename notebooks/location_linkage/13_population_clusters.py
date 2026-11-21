# Databricks notebook source
# MAGIC %md
# MAGIC # 13 · Location linkage vs **population clusters** (GHSL urban centres)
# MAGIC
# MAGIC Overlays India's population clusters on the facility-to-pincode ordered pairs, and asks whether the
# MAGIC disagreement between the two locations depends on how urban a place is.
# MAGIC
# MAGIC **Population clusters:** [GHSL Urban Centre Database R2024A v1.2](https://human-settlement.emergency.copernicus.eu/ghs_ucdb_2024.php)
# MAGIC (European Commission JRC, CC BY 4.0). An *urban centre* is a contiguous cluster of 1 km² cells with at least
# MAGIC 1,500 people/km², together holding at least 50,000 people. Population is the 2025 estimate. These are
# MAGIC **density-defined clusters, not municipal boundaries**: a dense, contiguous settlement belt can merge into one
# MAGIC very large "centre" (e.g. parts of Kerala and Bihar), and a city's satellite towns can be included in it.
# MAGIC
# MAGIC **Tiers** (by 2025 cluster population): `1M+`, `100k-1M`, `50k-100k`. Everything else is
# MAGIC `(outside urban centres)`, which here stands in for rural and small-town India.
# MAGIC
# MAGIC **Membership is reported from both ends of the pair:** the cluster containing the **facility point**, and
# MAGIC the cluster containing the **pincode point**. The pincode end uses the `primary_strategy` point (the
# MAGIC distance-to-city tables in section 5 use it too); notebook 12 covers how much the pincode point
# MAGIC itself moves between strategies.
# MAGIC
# MAGIC Requires notebook `00_build_location_pairs`. Writes `bronze_loclink_urban_centres`,
# MAGIC `bronze_loclink_urban_pairs`, and rows for four schemes into `bronze_loclink_region_summary`
# MAGIC (`urban_tier_fac_end`, `urban_tier_pin_end`, `urban_centre_fac_end`, `urban_centre_pin_end`).
# MAGIC
# MAGIC **Reading guide:** distance and offset are measured *from the pincode point to the facility point*.
# MAGIC On maps, urban centres are grey (darker = bigger tier), pairs are blue by distance bucket, orange marks =
# MAGIC pincode side unusable (shown at the facility point), aqua marks = facility coordinates unusable (shown at the
# MAGIC pincode point).

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 --quiet

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

import shutil
import tempfile
import zipfile

dbutils.widgets.text("max_city_panels", "24", "Max per-city map panels (facility end; pincode end gets half)")
dbutils.widgets.text("min_city_pairs", "5", "Min usable pairs to list/draw a city")
MAX_CITY_PANELS = int(dbutils.widgets.get("max_city_panels"))
MIN_CITY_PAIRS = int(dbutils.widgets.get("min_city_pairs"))

GHSL_URL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_UCDB_GLOBE_R2024A/GHS_UCDB_REGION_R2024A/"
            "GHS_UCDB_REGION_CENTRAL_AND_SOUTHERN_ASIA_R2024A/V1-2/"
            "GHS_UCDB_REGION_CENTRAL_AND_SOUTHERN_ASIA_R2024A_V1_2.zip")
GHSL_ZIP = f"{VOLUME_DIR}/GHS_UCDB_REGION_CENTRAL_AND_SOUTHERN_ASIA_R2024A_V1_2.zip"
GHSL_GPKG = "GHS_UCDB_REGION_CENTRAL_AND_SOUTHERN_ASIA_R2024A.gpkg"
GHSL_LAYER = "GHSL_UCDB_THEME_GENERAL_CHARACTERISTICS_GLOBE_R2024A"

TIERS = [(1_000_000, np.inf, "1M+"), (100_000, 1_000_000, "100k-1M"), (50_000, 100_000, "50k-100k")]
TIER_ORDER = [t[2] for t in TIERS]
OUTSIDE = "(outside urban centres)"
REGION_ORDER = TIER_ORDER + [OUTSIDE]
# ordinal ramps, validated with the dataviz validator (--ordinal): grey for cluster polygons on maps so they don't
# compete with the blue distance buckets and orange/aqua category marks; blue for tier series in non-map charts
TIER_FILL = {"1M+": "#4a4946", "100k-1M": "#7a7974", "50k-100k": "#a9a8a2"}
TIER_SERIES = {"1M+": "#0d366b", "100k-1M": "#1c5cab", "50k-100k": "#3987e5", OUTSIDE: "#86b6ef"}
END_COLORS = {"facility point": SERIES[0], "pincode point": SERIES[1]}

# COMMAND ----------

# MAGIC %md ## 1 · Load the GHSL urban centres for India
# MAGIC The regional zip (~67 MB) is downloaded once into the `loclink_geo` volume; later runs reuse it.

# COMMAND ----------

def ensure_ghsl():
    ensure_boundaries()  # also creates the volume
    if not os.path.exists(GHSL_ZIP):
        local = os.path.join(tempfile.mkdtemp(), "ucdb.zip")
        with urllib.request.urlopen(GHSL_URL, timeout=600) as r, open(local, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        shutil.copyfile(local, GHSL_ZIP)
        print(f"downloaded GHSL UCDB: {os.path.getsize(GHSL_ZIP)/1e6:.1f} MB -> {GHSL_ZIP}")
    work = tempfile.mkdtemp()
    with zipfile.ZipFile(GHSL_ZIP) as z:
        z.extract(GHSL_GPKG, work)
    return os.path.join(work, GHSL_GPKG)


def tier_of(pop):
    for lo, hi, lab in TIERS:
        if lo <= pop < hi:
            return lab
    return None  # below the 50k GHSL floor (should not happen)


raw = gpd.read_file(ensure_ghsl(), layer=GHSL_LAYER)
raw = raw[raw["GC_CNT_GAD_2025"] == "India"].copy()
uc = gpd.GeoDataFrame({
    "uc_id": raw["ID_UC_G0"].astype("int64"),
    "uc_name": raw["GC_UCN_MAI_2025"].astype(str),
    "uc_names_all": raw["GC_UCN_LIS_2025"].astype(str),
    "pop_2025": raw["GC_POP_TOT_2025"].astype(float),
    "area_km2": raw["GC_UCA_KM2_2025"].astype(float),
    "ghsl_capital_flag": raw["GC_UCM_CAP"],
}, geometry=raw.geometry.make_valid(), crs=raw.crs).to_crs(4326).reset_index(drop=True)
uc["tier"] = uc["pop_2025"].map(tier_of)
uc["uc_label"] = uc["uc_name"] + " [" + uc["uc_id"].astype(str) + "]"  # names repeat (e.g. two Aurangabads)
cent = uc.to_crs(INDIA_EPSG).geometry.centroid.to_crs(4326)
uc["centroid_lat"], uc["centroid_lon"] = cent.y, cent.x
uc = uc.sort_values("pop_2025", ascending=False).reset_index(drop=True)
assert uc["tier"].notna().all()

tier_tab = (uc.groupby("tier").agg(urban_centres=("uc_id", "size"), population_2025=("pop_2025", "sum"),
                                   area_km2=("area_km2", "sum"), largest=("uc_name", "first"))
            .reindex(TIER_ORDER).reset_index())
tier_tab["population_2025_millions"] = (tier_tab.pop("population_2025") / 1e6).round(1)
display(tier_tab)
display(uc[["uc_label", "uc_names_all", "tier", "pop_2025", "area_km2"]].head(25))

# COMMAND ----------

# MAGIC %md ## 2 · Place every pair end in (or near) a cluster
# MAGIC For each usable facility point and pincode point: the urban centre containing it, the nearest urban centre and
# MAGIC the distance to its **edge** (0 when inside), and the distance to the edge of the nearest `1M+` centre.
# MAGIC Distances are measured in EPSG:7755 (metres).

# COMMAND ----------

uc_proj = uc[["uc_id", "geometry"]].to_crs(INDIA_EPSG)
big_proj = uc[uc["tier"] == "1M+"][["uc_id", "geometry"]].to_crs(INDIA_EPSG)


def urban_lookup(pts):
    """pts: frame with lat, lon (unique). Returns it with uc_id_in, near_uc_id, dist_uc_km, near_1m_id, dist_1m_km."""
    g = gpd.GeoDataFrame(pts.reset_index(drop=True), geometry=gpd.points_from_xy(pts["lon"], pts["lat"]),
                         crs=4326).to_crs(INDIA_EPSG)
    out = g.drop(columns="geometry").copy()
    for target, id_col, d_col in ((uc_proj, "near_uc_id", "dist_uc_km"), (big_proj, "near_1m_id", "dist_1m_km")):
        n = gpd.sjoin_nearest(g[["geometry"]], target, how="left", distance_col="_d")
        n = n[~n.index.duplicated()]
        out[id_col] = n["uc_id"]
        out[d_col] = n["_d"] / 1000.0
    out["uc_id_in"] = out["near_uc_id"].where(out["dist_uc_km"] <= 0)
    return out


pairs_all = read_pdf("pairs")
fac_ok = pairs_all["pair_category"].str.startswith("FAC_OK__")
pin_ok = pairs_all["pair_category"].str.endswith("__PIN_OK") & pairs_all["pin_lat"].notna()
coords = pd.concat([pairs_all.loc[fac_ok, ["fac_lat", "fac_lon"]].set_axis(["lat", "lon"], axis=1),
                    pairs_all.loc[pin_ok, ["pin_lat", "pin_lon"]].set_axis(["lat", "lon"], axis=1)]).drop_duplicates()
look = urban_lookup(coords)
print(f"looked up {len(look):,} distinct points")

uc_tier = uc.set_index("uc_id")["tier"]
uc_lab = uc.set_index("uc_id")["uc_label"]
up = pairs_all[["fac_row_id", "strategy", "pair_category", "dist_km", "bucket", "fac_lat", "fac_lon",
                "pin_lat", "pin_lon"]].copy()
for end, ok, latc, lonc in (("fac", fac_ok, "fac_lat", "fac_lon"), ("pin", pin_ok, "pin_lat", "pin_lon")):
    m = up[[latc, lonc]].rename(columns={latc: "lat", lonc: "lon"}).merge(look, on=["lat", "lon"], how="left")
    m.index = up.index
    for c in ("uc_id_in", "near_uc_id", "dist_uc_km", "near_1m_id", "dist_1m_km"):
        up[f"{end}_{c}"] = m[c].where(ok)
    for c in ("uc_id_in", "near_uc_id", "near_1m_id"):
        up[f"{end}_{c}"] = up[f"{end}_{c}"].astype("Int64")
    up[f"{end}_tier"] = np.where(ok, up[f"{end}_uc_id_in"].map(uc_tier).fillna(OUTSIDE), None)
    up[f"{end}_city"] = np.where(ok, up[f"{end}_uc_id_in"].map(uc_lab).fillna(OUTSIDE), None)
    up[f"{end}_near_uc"] = up[f"{end}_near_uc_id"].map(uc_lab)
    up[f"{end}_near_1m"] = up[f"{end}_near_1m_id"].map(uc_lab)
up["same_cluster"] = np.where(up["fac_tier"].notna() & up["pin_tier"].notna(),
                              (up["fac_city"] == up["pin_city"]) & (up["fac_city"] != OUTSIDE), None)

prim_up = up[up["strategy"] == PRIMARY_STRATEGY].copy()
display(prim_up.groupby(["fac_tier", "pin_tier"], dropna=False).size().rename("facility_rows").reset_index())

tier_labels = prim_up[["fac_row_id", "fac_tier", "pin_tier"]]
city_labels = prim_up[["fac_row_id", "fac_city", "pin_city"]]


def labels_for(scheme, frame, def_col, fac_col, pin_col):
    out = frame[["fac_row_id"]].copy()
    out[scheme], out[f"{scheme}__fac_pt"], out[f"{scheme}__pin_pt"] = frame[def_col], frame[fac_col], frame[pin_col]
    return out


tier_shapes = uc.dissolve(by="tier").reset_index().rename(columns={"tier": "region"})[["region", "geometry"]]
city_shapes = uc[["uc_label", "geometry"]].rename(columns={"uc_label": "region"})

# COMMAND ----------

# MAGIC %md ### Persist

# COMMAND ----------

uc_out = pd.DataFrame(uc.drop(columns="geometry"))
uc_out["ghsl_capital_flag"] = uc_out["ghsl_capital_flag"].astype("float64")
uc_out["geometry_wkt"] = uc.geometry.simplify(0.001).to_wkt()
write_table(uc_out, "urban_centres",
            "Bronze: GHSL Urban Centre Database R2024A v1.2 (EC JRC, CC BY 4.0), India only. One row per urban centre "
            "(>= 50k people at >= 1,500/km2), 2025 population, tier (1M+ / 100k-1M / 50k-100k), WKT simplified 0.001 deg.")
up_out = up.copy()
up_out["same_cluster"] = up_out["same_cluster"].astype("object")
for c in ("fac_tier", "pin_tier", "fac_city", "pin_city"):
    up_out[c] = up_out[c].astype("object")
write_table(up_out, "urban_pairs",
            "Bronze: facility row x pincode-point strategy, with the GHSL urban centre containing each end (fac_/pin_), "
            "nearest urban centre and distance to its edge (km, 0 inside), and distance to the nearest 1M+ centre.")

# COMMAND ----------

# MAGIC %md ## 3 · Overlay map: population clusters under every ordered pair
# MAGIC Grey outlined polygons are GHSL urban centres (darker = larger tier), drawn above the pairs so they stay
# MAGIC visible; labels mark the 20 largest. Hover a cluster for its name and population, hover a dot for the facility.
# MAGIC Zoom in (scroll or box-zoom) to separate the clusters from the pair lines.

# COMMAND ----------

def uc_traces(g, simplify=0.01, n_labels=20):
    traces = []
    for tier in TIER_ORDER[::-1]:  # small tiers first so big clusters draw on top
        t = g[g["tier"] == tier].copy()
        t["geometry"] = shapely.set_precision(t.geometry.simplify(simplify).values, 0.001)  # keeps the embedded geojson small
        gj = json.loads(t[["uc_label", "geometry"]].to_json())
        traces.append(go.Choropleth(
            geojson=gj, locations=t["uc_label"], featureidkey="properties.uc_label", z=np.ones(len(t)),
            colorscale=[[0, TIER_FILL[tier]], [1, TIER_FILL[tier]]], showscale=False,
            marker_line_color="#3d3c39", marker_line_width=0.6, marker_opacity=0.5,
            name=f"urban centre {tier} (n={len(t)})", legendgroup=f"uc_{tier}", showlegend=False,
            customdata=np.stack([t["pop_2025"] / 1e6, t["area_km2"], t["uc_names_all"].str.slice(0, 90)], axis=1),
            hovertemplate="%{location}<br>%{customdata[0]:.2f} M people (2025), %{customdata[1]:.0f} km²"
                          "<br>%{customdata[2]}<extra>" + tier + "</extra>"))
        # legend swatch (choropleth traces do not draw legend items in plotly 5.9)
        traces.append(go.Scattergeo(lon=[None], lat=[None], mode="markers", legendgroup=f"uc_{tier}",
                                    name=f"urban centre {tier} (n={len(t)})",
                                    marker=dict(size=12, symbol="square", color=TIER_FILL[tier], opacity=0.55)))
    top = g.head(n_labels)
    labels = go.Scattergeo(lon=top["centroid_lon"], lat=top["centroid_lat"], mode="text", text=top["uc_name"],
                           textfont=dict(size=10, color="#3d3c39"), textposition="top center",
                           name=f"labels: {n_labels} largest", hoverinfo="skip")
    return traces, labels


ra_city_fac = RegionAnalysis("urban_centre_fac_end", max_region_panels=MAX_CITY_PANELS, min_n_panels=MIN_CITY_PAIRS,
                             extra_shapes=city_shapes,
                             extra_labels=labels_for("urban_centre_fac_end", city_labels, "fac_city", "fac_city", "pin_city"))
uc_layer, labels = uc_traces(uc)
ra_city_fac.pairs_map(overlay_traces=uc_layer + [labels],
                      title="Population clusters (GHSL urban centres, grey, drawn on top) and every pincode point -> "
                            "facility point pair (lines drawn for pairs >= 5 km)")

# COMMAND ----------

# MAGIC %md ### Same overlay, static, with every pair line (no 5 km cut-off)
# MAGIC Long lines that start or end inside a grey cluster are the cases where one source puts the facility in a city
# MAGIC and the other puts it far away. The second figure zooms into four dense corridors.

# COMMAND ----------

def static_overlay(d, title, bounds=None, figsize=(14, 15)):
    fig, ax = plt.subplots(figsize=figsize)
    basemap = ra_city_fac.basemap
    basemap.boundary.plot(ax=ax, color=BASEMAP_EDGE, linewidth=0.4)
    for lab in BUCKET_LABELS:
        b = d[d["bucket"] == lab]
        if b.empty:
            continue
        segs = np.stack([b[["pin_lon", "pin_lat"]].to_numpy(), b[["fac_lon", "fac_lat"]].to_numpy()], axis=1)
        ax.add_collection(LineCollection(segs, colors=BUCKET_COLORS[lab], linewidths=0.5, alpha=0.45, zorder=2))
        ax.scatter(b["fac_lon"], b["fac_lat"], s=3, color=BUCKET_COLORS[lab], zorder=4)
    # clusters above the lines (below the facility dots) so they stay visible where lines are dense
    for tier in TIER_ORDER[::-1]:
        uc[uc["tier"] == tier].plot(ax=ax, color=TIER_FILL[tier], alpha=0.55, edgecolor="#3d3c39", linewidth=0.5,
                                    zorder=3)
    x0, y0, x1, y1 = bounds or (67.5, 6, 98, 37.5)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
    ax.set_aspect(1 / math.cos(math.radians((y0 + y1) / 2)))
    ax.set_xticks([]); ax.set_yticks([])
    handles = [plt.Line2D([], [], color=TIER_FILL[t], marker="s", ls="", ms=10, alpha=0.6, label=f"urban centre {t}")
               for t in TIER_ORDER]
    handles += [plt.Line2D([], [], color=BUCKET_COLORS[l], lw=2, label=f"pair {l}") for l in BUCKET_LABELS]
    if bounds is None:  # zoomed maps reuse the national legend so it does not cover data
        ax.legend(handles=handles, loc="lower left", fontsize=9, frameon=False)
    ax.set_title(title, fontsize=12)
    plt.show()


static_overlay(ra_city_fac.prim, f"Urban centres and all {len(ra_city_fac.prim):,} usable pairs "
                                 f"(pincode point -> facility point, {PRIMARY_STRATEGY})")

# COMMAND ----------

ZOOMS = {"Delhi NCR": (76.3, 27.9, 78.1, 29.3), "Mumbai-Pune": (72.5, 18.0, 74.4, 19.7),
         "Kerala": (74.8, 8.1, 77.5, 12.6), "Bihar & Kolkata": (83.5, 22.0, 89.0, 27.0)}
for name, bnd in ZOOMS.items():
    static_overlay(ra_city_fac.prim, f"{name}: urban centres and pairs (lines cut at the frame edge)", bounds=bnd,
                   figsize=(7.5, 6.5))

# COMMAND ----------

# MAGIC %md ## 4 · Do both ends agree on the cluster?
# MAGIC Rows = tier at the facility point, columns = tier at the pincode point (facility rows where both points are
# MAGIC usable). Off-diagonal cells are facilities that one source calls urban and the other calls rural, or that the
# MAGIC two sources put in different-sized clusters.

# COMMAND ----------

both = prim_up[prim_up["fac_tier"].notna() & prim_up["pin_tier"].notna()]
ct = pd.crosstab(both["fac_tier"], both["pin_tier"]).reindex(index=REGION_ORDER, columns=REGION_ORDER, fill_value=0)
row_pct = 100 * ct.div(ct.sum(axis=1).replace(0, np.nan), axis=0)
display(ct.assign(total=ct.sum(axis=1)).rename_axis("facility point \\ pincode point").reset_index())
fig = px.imshow(row_pct.to_numpy(), x=[f"pin: {c}" for c in ct.columns], y=[f"facility: {i}" for i in ct.index],
                color_continuous_scale=SEQ_BLUE, zmin=0, zmax=100, aspect="auto", labels=dict(color="% of row"),
                title="Tier at the pincode point, given the tier at the facility point (row %, counts in cells)")
fig.update_traces(text=np.array([[f"{p:.0f}%<br>n={n:,}" for p, n in zip(pr, nr)]
                                 for pr, nr in zip(np.nan_to_num(row_pct.to_numpy()), ct.to_numpy())]),
                  texttemplate="%{text}")
show(fig, height=460)

in_city = both[both["fac_tier"] != OUTSIDE]
same = pd.DataFrame({
    "facility point tier": TIER_ORDER,
    "facility rows": [int((in_city["fac_tier"] == t).sum()) for t in TIER_ORDER],
    "pin in same cluster %": [100 * in_city.loc[in_city["fac_tier"] == t, "same_cluster"].astype(bool).mean() for t in TIER_ORDER],
    "pin in a different cluster %": [100 * ((in_city["fac_tier"] == t) & ~in_city["same_cluster"].astype(bool)
                                            & (in_city["pin_tier"] != OUTSIDE)).sum() / max((in_city["fac_tier"] == t).sum(), 1)
                                     for t in TIER_ORDER],
    "pin outside clusters %": [100 * ((in_city["fac_tier"] == t) & (in_city["pin_tier"] == OUTSIDE)).sum()
                               / max((in_city["fac_tier"] == t).sum(), 1) for t in TIER_ORDER],
}).round(1)
display(same)

# COMMAND ----------

# MAGIC %md ## 5 · Error vs distance to the nearest city
# MAGIC Pairs are binned by how far one end sits from the **edge** of the nearest urban centre (`inside` = within a
# MAGIC cluster). If linkage error is a rural problem, the median and the share of pairs beyond 25 km should rise with
# MAGIC distance from a city. Both ends are shown, because "far from a city" can be true of one source and not the other.

# COMMAND ----------

UC_BANDS = [(-np.inf, 0, "inside"), (0, 2, "0-2 km"), (2, 5, "2-5 km"), (5, 10, "5-10 km"), (10, 25, "10-25 km"),
            (25, 50, "25-50 km"), (50, np.inf, ">50 km")]
BIG_BANDS = [(-np.inf, 0, "inside"), (0, 10, "0-10 km"), (10, 25, "10-25 km"), (25, 50, "25-50 km"),
             (50, 100, "50-100 km"), (100, 250, "100-250 km"), (250, np.inf, ">250 km")]


def band_of(x, bands):
    x = pd.to_numeric(x, errors="coerce").to_numpy(dtype=float)
    out = np.full(x.shape, None, dtype=object)
    for lo, hi, lab in bands:
        out[(x > lo) & (x <= hi)] = lab
    return out


ok_prim = prim_up[prim_up["pair_category"] == "FAC_OK__PIN_OK"].copy()


def band_table(col_suffix, bands, what):
    rows = []
    for end, label in (("fac", "facility point"), ("pin", "pincode point")):
        b = band_of(ok_prim[f"{end}_{col_suffix}"], bands)
        for lo, hi, lab in bands:
            x = ok_prim.loc[b == lab, "dist_km"]
            rows.append(dict(end=label, band=lab, n_pairs=len(x), median_km=x.median(), mean_km=x.mean(),
                             p25_km=x.quantile(.25), p75_km=x.quantile(.75), p90_km=x.quantile(.9),
                             pct_gt_5km=100 * (x > 5).mean() if len(x) else np.nan,
                             pct_gt_25km=100 * (x > 25).mean() if len(x) else np.nan,
                             pct_gt_100km=100 * (x > 100).mean() if len(x) else np.nan))
        rho = ok_prim[f"{end}_{col_suffix}"].rank().corr(ok_prim["dist_km"].rank())
        print(f"Spearman rank correlation, {label} distance to {what} vs pair distance: {rho:.3f}")
    t = pd.DataFrame(rows)
    display(t.round(2))
    order = [b[2] for b in bands]
    for metric, ttl, log in (("median_km", "Median pair distance", True), ("pct_gt_25km", "% of pairs more than 25 km apart", False)):
        fig = go.Figure()
        for label, color in END_COLORS.items():
            s = t[t["end"] == label].set_index("band").reindex(order)
            kw = {}
            if metric == "median_km":
                kw = dict(error_y=dict(type="data", symmetric=False, array=s["p75_km"] - s["median_km"],
                                       arrayminus=s["median_km"] - s["p25_km"], color="#52514e", thickness=1))
            fig.add_bar(x=order, y=s[metric], name=f"binned by {label}", marker_color=color,
                        customdata=s[["n_pairs"]], **kw,
                        hovertemplate="%{x}<br>%{y:.1f}<br>n=%{customdata[0]:,}<extra>" + label + "</extra>")
        fig.update_traces(marker_line_color="#fcfcfb", marker_line_width=2)
        fig.update_layout(barmode="group", xaxis_title=f"distance from that end to the edge of the nearest {what}",
                          yaxis_title="km (log scale)" if log else "% of pairs", yaxis_type="log" if log else "linear",
                          title=f"{ttl}, by distance to the nearest {what}"
                                + (" (whiskers = IQR)" if metric == "median_km" else ""))
        show(fig, height=440)
    return t


band_any = band_table("dist_uc_km", UC_BANDS, "urban centre (any tier)")

# COMMAND ----------

band_big = band_table("dist_1m_km", BIG_BANDS, "1M+ urban centre")

# COMMAND ----------

# MAGIC %md ## 6 · Urban vs rural split by tier, **facility end**
# MAGIC Same tables as the region notebooks, with the facility point's tier as the "region". Rows are persisted to
# MAGIC `bronze_loclink_region_summary` as scheme `urban_tier_fac_end`.

# COMMAND ----------

ra_tier_fac = RegionAnalysis("urban_tier_fac_end", extra_shapes=tier_shapes,
                             extra_labels=labels_for("urban_tier_fac_end", tier_labels, "fac_tier", "fac_tier", "pin_tier"))
ra_tier_fac.overview()
ra_tier_fac.coverage()
ra_tier_fac.summary_stats()

# COMMAND ----------

ra_tier_fac.average_by_region()
ra_tier_fac.threshold_heatmap()  # per-tier distributions: see the cumulative chart below

# COMMAND ----------

def tier_ecdf(ra, label):
    d = ra.prim.copy()
    d["dist_plot"] = d["dist_km"].clip(lower=0.01)
    present = [r for r in REGION_ORDER if r in set(d["region"])]
    d = d[d["region"].isin(present)]
    fig = px.ecdf(d, x="dist_plot", color="region", log_x=True, category_orders={"region": present},
                  color_discrete_map=TIER_SERIES,
                  title=f"Cumulative distance distribution by tier at the {label} (share of pairs within X km)")
    fig.update_traces(line=dict(width=2))
    for t in [1, 5, 25, 100]:
        fig.add_vline(x=t, line_dash="dot", line_color="#9a9994", annotation_text=f"{t} km")
    fig.update_layout(xaxis_title="km (log scale)", yaxis_title="share of usable pairs")
    show(fig, height=440)


tier_ecdf(ra_tier_fac, "facility point")
ra_tier_fac.strategy_sensitivity()

# COMMAND ----------

# MAGIC %md ## 7 · Urban vs rural split by tier, **pincode end**
# MAGIC Persisted as scheme `urban_tier_pin_end`. Comparing with section 6 shows whether "urban" facilities look
# MAGIC better or worse depending on which source decides that they are urban.

# COMMAND ----------

ra_tier_pin = RegionAnalysis("urban_tier_pin_end", extra_shapes=tier_shapes,
                             extra_labels=labels_for("urban_tier_pin_end", tier_labels, "pin_tier", "fac_tier", "pin_tier"))
ra_tier_pin.coverage()
ra_tier_pin.summary_stats()
ra_tier_pin.average_by_region()

# COMMAND ----------

tier_ecdf(ra_tier_pin, "pincode point")
ra_tier_pin.threshold_heatmap()
ra_tier_pin.strategy_sensitivity()

# COMMAND ----------

both_ends = pd.concat([
    ra_tier_fac.summary.assign(membership="facility point"),
    ra_tier_pin.summary.assign(membership="pincode point")])
both_ends = both_ends[(both_ends["strategy"] == PRIMARY_STRATEGY) & both_ends["region"].isin(REGION_ORDER)]
piv = (both_ends.pivot_table(index="region", columns="membership",
                             values=["n_pairs", "median_km", "mean_km", "p90_km", "pct_gt_25km"])
       .reindex(REGION_ORDER).round(2))
piv.columns = [f"{m} | {e}" for m, e in piv.columns]
display(piv.rename_axis("tier").reset_index())

# COMMAND ----------

# MAGIC %md ## 8 · Per-city statistics, **facility end**
# MAGIC Each urban centre is its own region (scheme `urban_centre_fac_end`). Small clusters hold only a few facilities,
# MAGIC so the city tables list only those with at least `min_city_pairs` usable pairs.

# COMMAND ----------

ra_city_fac.summary_stats(write=True)  # instance built in section 3


def city_table(ra, same_col_end):
    s = ra.summary[(ra.summary["strategy"] == PRIMARY_STRATEGY)].copy()
    meta = uc.set_index("uc_label")[["uc_name", "tier", "pop_2025"]]
    s = s.join(meta, on="region")
    sc = (prim_up[prim_up[f"{same_col_end}_city"].notna() & (prim_up[f"{same_col_end}_city"] != OUTSIDE)]
          .groupby(f"{same_col_end}_city")["same_cluster"].apply(lambda x: 100 * x.dropna().astype(bool).mean()))
    s["pct_other_end_in_same_cluster"] = s["region"].map(sc)
    cols = ["region", "tier", "pop_2025", "facility_rows_in_region", "n_pairs", "median_km", "mean_km", "p90_km",
            "max_km", "pct_gt_5km", "pct_gt_25km", "pct_gt_100km", "pct_other_end_in_same_cluster"]
    cities = s[s["tier"].notna() & (s["n_pairs"] >= MIN_CITY_PAIRS)][cols]
    rest = s[~s["tier"].notna()][cols[:1] + cols[3:-1]]
    print(f"{len(cities)} urban centres with >= {MIN_CITY_PAIRS} usable pairs "
          f"(of {(s['tier'].notna()).sum()} centres with any usable pair)")
    display(rest.round(2))
    display(cities.sort_values("pop_2025", ascending=False).round(2))
    return cities


def city_bars(cities, label, n=40):
    top = cities.sort_values("median_km", ascending=False).head(n)
    fig = go.Figure()
    fig.add_bar(y=top["region"], x=top["mean_km"], name="Mean", orientation="h", marker_color=SERIES[0],
                customdata=top[["n_pairs", "tier"]],
                hovertemplate="%{y}<br>mean %{x:.1f} km<br>n=%{customdata[0]} (%{customdata[1]})<extra></extra>")
    fig.add_bar(y=top["region"], x=top["median_km"], name="Median", orientation="h", marker_color=SERIES[1],
                customdata=top[["n_pairs", "tier"]],
                hovertemplate="%{y}<br>median %{x:.1f} km<br>n=%{customdata[0]} (%{customdata[1]})<extra></extra>")
    fig.update_traces(marker_line_color="#fcfcfb", marker_line_width=1)
    fig.update_layout(barmode="group", xaxis_type="log", xaxis_title="km (log scale)",
                      yaxis=dict(categoryorder="array", categoryarray=list(top["region"])[::-1]),
                      title=f"Urban centres with the largest median distance, membership at the {label} "
                            f"(>= {MIN_CITY_PAIRS} pairs; top {len(top)})")
    show(fig, height=max(450, 22 * len(top) + 150))

    fig = px.scatter(cities, x="pop_2025", y="median_km", size="n_pairs", color="tier", log_x=True, log_y=True,
                     category_orders={"tier": TIER_ORDER}, color_discrete_map=TIER_SERIES,
                     hover_data=["region", "n_pairs", "mean_km", "pct_gt_25km"],
                     title=f"City size vs median pair distance, membership at the {label} (bubble = usable pairs)")
    fig.update_traces(marker=dict(line=dict(width=2, color="#fcfcfb")))
    fig.update_layout(xaxis_title="cluster population 2025 (log)", yaxis_title="median km (log)")
    show(fig, height=520)


cities_fac = city_table(ra_city_fac, "fac")
city_bars(cities_fac, "facility point")

# COMMAND ----------

# MAGIC %md ### Zoomed panels: the largest cities (facility end)
# MAGIC One panel per `1M+` urban centre, largest population first. The pale-blue outline is the GHSL cluster; lines are
# MAGIC pincode point -> facility point. Each panel is framed on the cluster itself, so long lines are cut at the edge;
# MAGIC "an end outside frame" counts those pairs.

# COMMAND ----------

big_regions = [r for r in uc.loc[uc["tier"] == "1M+", "uc_label"]
               if r in set(cities_fac["region"])][:MAX_CITY_PANELS]
ra_city_fac.region_panels(regions=big_regions, frame_mode="shape", pad_frac=0.3)

# COMMAND ----------

ra_city_fac.assignment_agreement(top_flows=30)
ra_city_fac.outliers(30)

# COMMAND ----------

# MAGIC %md ## 9 · Per-city statistics, **pincode end**
# MAGIC Scheme `urban_centre_pin_end`: the city is the one the pincode point falls in. Panels are drawn for half as
# MAGIC many cities as in section 8 to keep the notebook output under the export size limit.

# COMMAND ----------

ra_city_pin = RegionAnalysis("urban_centre_pin_end", max_region_panels=MAX_CITY_PANELS, min_n_panels=MIN_CITY_PAIRS,
                             extra_shapes=city_shapes,
                             extra_labels=labels_for("urban_centre_pin_end", city_labels, "pin_city", "fac_city", "pin_city"))
ra_city_pin.summary_stats(write=True)
cities_pin = city_table(ra_city_pin, "pin")
city_bars(cities_pin, "pincode point")

# COMMAND ----------

big_regions_pin = [r for r in uc.loc[uc["tier"] == "1M+", "uc_label"]
                   if r in set(cities_pin["region"])][:max(MAX_CITY_PANELS // 2, 1)]
ra_city_pin.region_panels(regions=big_regions_pin, frame_mode="shape", pad_frac=0.3)

# COMMAND ----------

ra_city_pin.assignment_agreement(top_flows=30)

# COMMAND ----------

# MAGIC %md ## 10 · Facility end vs pincode end, city by city
# MAGIC Points off the diagonal are cities whose apparent quality depends on which source decides membership.

# COMMAND ----------

cmp = cities_fac[["region", "tier", "pop_2025", "n_pairs", "median_km"]].merge(
    cities_pin[["region", "n_pairs", "median_km"]], on="region", suffixes=("_fac_end", "_pin_end"))
fig = px.scatter(cmp, x="median_km_fac_end", y="median_km_pin_end", color="tier", log_x=True, log_y=True,
                 category_orders={"tier": TIER_ORDER}, color_discrete_map=TIER_SERIES,
                 hover_data=["region", "n_pairs_fac_end", "n_pairs_pin_end"],
                 title="Median pair distance per city: membership by facility point vs by pincode point")
lo_, hi_ = max(cmp[["median_km_fac_end", "median_km_pin_end"]].min().min(), 0.01), cmp[["median_km_fac_end", "median_km_pin_end"]].max().max()
fig.add_trace(go.Scatter(x=[lo_, hi_], y=[lo_, hi_], mode="lines", line=dict(dash="dot", color="#9a9994", width=1),
                         name="equal", hoverinfo="skip"))
fig.update_traces(marker=dict(size=9, line=dict(width=2, color="#fcfcfb")), selector=dict(mode="markers"))
fig.update_layout(xaxis_title="median km, facility point in city (log)", yaxis_title="median km, pincode point in city (log)")
show(fig, height=560)
cmp["ratio_pin_over_fac"] = cmp["median_km_pin_end"] / cmp["median_km_fac_end"]
display(cmp.sort_values("ratio_pin_over_fac", ascending=False).round(2))
