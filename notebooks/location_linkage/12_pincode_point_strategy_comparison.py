# Databricks notebook source
# MAGIC %md
# MAGIC # 12 · How should a pincode become a point? (strategy comparison for the team)
# MAGIC
# MAGIC The pincode directory has **one row per post office**, so every pincode is really a *cloud* of office
# MAGIC coordinates. Notebook 00 turns each cloud into a point five different ways. This notebook doesn't choose
# MAGIC one. It lays out the evidence the team needs to decide:
# MAGIC
# MAGIC 1. How big and how messy are pincode office clouds?
# MAGIC 2. How far apart are the strategies' points for the same pincode?
# MAGIC 3. How much does the facility-level distance (and its bucket) change with the strategy?
# MAGIC 4. Which pincodes are so spread out that *any* single point is misleading?

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 --quiet

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

pins = read_pdf("pincodes")
offices = read_pdf("offices")
pairs = read_pdf("pairs")
fr = read_pdf("facility_regions")
shapes = read_pdf("region_shapes")
basemap = gdf_from_wkt(shapes[shapes["scheme"] == "dir_state"])
used_pins = set(fr.loc[fr["pin_status"] == "OK", "pin_clean"].astype(float).astype("int64"))
pins["used_by_a_facility"] = pins["pincode"].isin(used_pins)
display(pd.DataFrame(STRATEGY_HELP.items(), columns=["strategy", "definition"]))

# COMMAND ----------

# MAGIC %md ## 1 · Office clouds: size, geocoding quality, spread

# COMMAND ----------

display(offices.groupby(["office_loc_status"]).size().rename("offices").reset_index())
display(offices.groupby(["officetype", "point_status"]).size().unstack(fill_value=0).reset_index())
desc = pins[["n_offices", "n_offices_geocoded_ok", "n_offices_no_coords", "n_offices_outside_india", "n_main_offices",
             "spread_median_km", "spread_p90_km", "spread_max_km", "state_n_distinct", "state_district_n_distinct"]]
display(desc.describe(percentiles=[.5, .75, .9, .95, .99]).T.round(2).reset_index())
print("Pincodes used by facilities only:")
display(desc[pins["used_by_a_facility"]].describe(percentiles=[.5, .75, .9, .95, .99]).T.round(2).reset_index())

# COMMAND ----------

sp = pins[pins["spread_max_km"].notna()].assign(spread_plot=lambda x: x["spread_max_km"].clip(lower=0.01))
fig = px.histogram(sp, x=np.log10(sp["spread_plot"]), nbins=80, color_discrete_sequence=[SERIES[0]],
                   title="Pincode office spread: max distance (km) of any office from the pincode median, log10 scale")
fig.update_layout(xaxis=dict(tickvals=np.log10([0.1, 1, 5, 25, 100, 500, 2000]),
                             ticktext=["0.1", "1", "5", "25", "100", "500", "2000"], title="km"),
                  bargap=0.05)
show(fig, height=420)
for t in [5, 25, 50, 100, 500]:
    print(f"pincodes with an office > {t:>3} km from their median: {(sp['spread_max_km'] > t).sum():>6,} "
          f"({100 * (sp['spread_max_km'] > t).mean():.1f}%), used by facilities: "
          f"{(sp.loc[sp['used_by_a_facility'], 'spread_max_km'] > t).sum():,}")

# COMMAND ----------

# MAGIC %md ### Where are the widely spread pincodes?

# COMMAND ----------

wide = pins[pins["spread_max_km"] > 25].copy()
wide["bucket"] = bucket_of(wide["spread_max_km"])
fig = go.Figure()
lo, la = outline_lines(basemap, 0.02)
fig.add_trace(go.Scattergeo(lon=lo, lat=la, mode="lines", line=dict(width=0.5, color=BASEMAP_EDGE), name="states", hoverinfo="skip"))
for lab in BUCKET_LABELS:
    b = wide[wide["bucket"] == lab]
    if len(b):
        fig.add_trace(go.Scattergeo(lon=b["lon_office_median"], lat=b["lat_office_median"], mode="markers",
                                    name=f"spread {lab} (n={len(b)})", marker=dict(size=6, color=BUCKET_COLORS[lab]),
                                    customdata=np.stack([b["pincode"], b["n_offices"], b["spread_max_km"], b["state"]], axis=1),
                                    hovertemplate="pin %{customdata[0]} (%{customdata[3]})<br>%{customdata[1]} offices<br>max spread %{customdata[2]:.0f} km<extra></extra>"))
india_geo_layout(fig, "Pincodes whose offices spread more than 25 km from their median point")
show(fig, height=800)

# COMMAND ----------

# MAGIC %md ### Look inside the worst office clouds
# MAGIC Each panel is one pincode: every office (dot), the five strategy points (labelled markers), and the facilities using it.

# COMMAND ----------

worst = pins[pins["used_by_a_facility"]].sort_values("spread_max_km", ascending=False).head(12)
ok_off = offices[offices["point_status"] == "OK"]
pp = pairs[pairs["pair_category"] == "FAC_OK__PIN_OK"]
cols = 4
rows = math.ceil(len(worst) / cols)
fig, axes = plt.subplots(rows, cols, figsize=(4.5 * cols, 4.5 * rows), squeeze=False)
markers = dict(zip(STRATEGIES[:4], ["o", "s", "D", "^"]))
for ax, (_, p) in zip(axes.ravel(), worst.iterrows()):
    o = ok_off[ok_off["pincode"] == p["pincode"]]
    ax.scatter(o["lon"], o["lat"], s=12, color="#9a9994", label="office")
    for s, m in markers.items():
        ax.scatter(p[f"lon_{s}"], p[f"lat_{s}"], s=70, marker=m, color=STRATEGY_COLORS[s], edgecolors="#fcfcfb", zorder=4, label=s)
    f = fr[(fr["pin_clean"] == str(p["pincode"])) & (fr["fac_point_status"] == "OK")]
    ax.scatter(f["fac_lon"], f["fac_lat"], s=60, marker="*", color="#0b0b0b", zorder=5, label="facility")
    ax.set_title(f"pin {p['pincode']} · {p['state']}\n{int(p['n_offices'])} offices · spread {p['spread_max_km']:.0f} km", fontsize=9)
    ax.set_xticks([]); ax.set_yticks([])
for ax in axes.ravel()[len(worst):]:
    ax.axis("off")
h, l = axes.ravel()[0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=6, frameon=False)
fig.tight_layout(rect=(0, 0, 1, 0.95))
plt.show()

# COMMAND ----------

# MAGIC %md ## 2 · How far apart are the strategy points for the same pincode?

# COMMAND ----------

ref = "office_median"
rows = []
for s in ["office_mean", "office_median_trimmed", "main_office_mean"]:
    m = pins[f"lat_{s}"].notna() & pins[f"lat_{ref}"].notna()
    dist = haversine_km(pins.loc[m, f"lat_{ref}"], pins.loc[m, f"lon_{ref}"], pins.loc[m, f"lat_{s}"], pins.loc[m, f"lon_{s}"])
    q = np.percentile(dist, [50, 75, 90, 95, 99])
    rows.append(dict(compared_to_office_median=s, pincodes=int(m.sum()), coverage_pct=round(100 * m.mean(), 2),
                     median_km=q[0], p75_km=q[1], p90_km=q[2], p95_km=q[3], p99_km=q[4], max_km=dist.max(),
                     n_gt_5km=int((dist > 5).sum()), n_gt_25km=int((dist > 25).sum())))
display(pd.DataFrame(rows).round(2))

# COMMAND ----------

# MAGIC %md ## 3 · Facility-level effect of the strategy

# COMMAND ----------

cov = pairs.groupby("strategy")["pair_category"].apply(lambda s: (s == "FAC_OK__PIN_OK").sum()).rename("usable_pairs")
stats = pp.groupby("strategy").apply(dist_stats)
display(stats.join(cov).reset_index().round(2))

fig = go.Figure()
for s in STRATEGIES:
    x = np.sort(pp.loc[pp["strategy"] == s, "dist_km"].clip(lower=0.01).to_numpy())
    fig.add_trace(go.Scatter(x=x, y=np.arange(1, len(x) + 1) / len(x), mode="lines", name=s,
                             line=dict(width=2, color=STRATEGY_COLORS[s])))
fig.update_layout(xaxis_type="log", xaxis_title="facility-to-pincode km (log)", yaxis_title="share of usable pairs",
                  title="Cumulative distance distribution per pincode-point strategy")
for t in [1, 5, 25, 100]:
    fig.add_vline(x=t, line_dash="dot", line_color="#9a9994")
show(fig, height=480)

# COMMAND ----------

# MAGIC %md ### Bucket changes: does the strategy move a facility from "fine" to "far"?

# COMMAND ----------

wide_b = pp.pivot_table(index="fac_row_id", columns="strategy", values="bucket", aggfunc="first")
for other in ["office_mean", "office_median_trimmed", "main_office_mean", "nearest_office"]:
    m = wide_b[ref].notna() & wide_b[other].notna()
    ct = pd.crosstab(pd.Categorical(wide_b.loc[m, ref], BUCKET_LABELS, ordered=True),
                     pd.Categorical(wide_b.loc[m, other], BUCKET_LABELS, ordered=True),
                     rownames=[ref], colnames=[other], dropna=False)
    changed = 100 * (wide_b.loc[m, ref] != wide_b.loc[m, other]).mean()
    fig = px.imshow(ct, text_auto=True, color_continuous_scale=SEQ_BLUE, aspect="auto",
                    title=f"Distance bucket: {ref} (rows) vs {other} (cols). {changed:.1f}% of facilities change bucket")
    show(fig, height=420)

# COMMAND ----------

# MAGIC %md ### "Inside the pincode, just not near its centre"
# MAGIC If `nearest_office` is small but `office_median` is large, the facility sits next to one of its pincode's
# MAGIC offices and the large distance is an artefact of the pincode being spread out, not an error.

# COMMAND ----------

wd = pp.pivot_table(index="fac_row_id", columns="strategy", values="dist_km")
wd = wd.join(fr.set_index("fac_row_id")[["name", "pin_clean", "pin_spread_max_km", "within_pin_footprint", "dir_state"]])
wd["class"] = np.select(
    [(wd[ref] <= 5), (wd["nearest_office"] <= 5) & (wd[ref] > 5), (wd["nearest_office"] > 5) & wd["within_pin_footprint"].fillna(False).astype(bool),
     (wd["nearest_office"] > 5)],
    ["close to pincode median (<=5 km)", "near one of its offices, far from median",
     "far from every office but inside footprint", "far from every office and outside footprint"], "n/a")
display(wd.groupby("class").agg(facilities=("pin_clean", "size"), median_km_median=(ref, "median"),
                                median_km_nearest=("nearest_office", "median")).reset_index().round(2))

# COMMAND ----------

# MAGIC %md ## 4 · Questions for the team
# MAGIC
# MAGIC * **Centre vs nearest:** should "the pincode location" be a centre (median/mean) or the facility's nearest
# MAGIC   office? The nearest office is a best-case bound and can only be computed when we trust the facility coordinates.
# MAGIC * **Branch offices:** branch offices (`BO`, ~84% of rows) are often rural and far-flung. Excluding them
# MAGIC   (`main_office_mean`) shifts the point toward towns but loses coverage for BO-only pincodes.
# MAGIC * **Outlier offices:** `office_median_trimmed` uses a 50 km radius (widget in notebook 00). Is that the right cut, and
# MAGIC   should the cut scale with the pincode's own spread?
# MAGIC * **Multi-state / multi-district pincodes:** keep them as ambiguous, or split per office?
# MAGIC * **Unusable pincodes:** pins that are malformed, missing from the directory, or have no geocoded offices. Should
# MAGIC   we fall back to the city or district text for these?
