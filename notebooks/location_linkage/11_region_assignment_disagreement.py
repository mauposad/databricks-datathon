# Databricks notebook source
# MAGIC %md
# MAGIC # 11 · Where do the location sources disagree?
# MAGIC
# MAGIC Every facility has up to **four independent opinions** on which state it is in:
# MAGIC
# MAGIC | source | column | comes from |
# MAGIC |---|---|---|
# MAGIC | pincode directory | `dir_state` | the facility's pincode → India Post directory `statename` |
# MAGIC | written text | `fac_stated_state` | `address_stateOrRegion` on the facility record |
# MAGIC | facility coordinates | `spatial_state` | ADM1 polygon containing facility lat/lon |
# MAGIC | pincode coordinates | `dir_state__pin_pt` | ADM1 polygon containing the pincode's office_median point |
# MAGIC
# MAGIC None of them is known to be the truth. This notebook measures **how often each pair agrees**, groups facilities
# MAGIC into **agreement patterns**, and checks whether each pattern lines up with the measured distance. The patterns
# MAGIC are *consistent with* a given source being wrong; they don't prove it. They are meant to show where the
# MAGIC real source of each location could lie.
# MAGIC
# MAGIC Section 5 repeats the check at every region scheme: definition vs. region at the facility point vs. region
# MAGIC at the pincode point.

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 --quiet

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

fr = read_pdf("facility_regions")
pairs = read_pdf("pairs")
prim = pairs[pairs["strategy"] == PRIMARY_STRATEGY][["fac_row_id", "pin_lat", "pin_lon", "dist_km", "pair_category", "bucket"]]
fr = fr.merge(prim, on="fac_row_id", how="left")
shapes = read_pdf("region_shapes")
basemap = gdf_from_wkt(shapes[shapes["scheme"] == "dir_state"])
SOURCES = {"pincode directory": "dir_state", "written text": "fac_stated_state",
           "facility coords": "spatial_state", "pincode coords": "dir_state__pin_pt"}
st = pd.DataFrame({k: fr[v] for k, v in SOURCES.items()})
st["written text"] = st["written text"].where(st["written text"] != UNRESOLVED_STATE)  # unresolved = no opinion
print(f"facility rows: {len(fr):,}; primary strategy: {PRIMARY_STRATEGY}")
display(st.notna().sum().rename("rows with an opinion").reset_index())

# COMMAND ----------

# MAGIC %md ## 1 · Pairwise agreement between the four state sources

# COMMAND ----------

names = list(SOURCES)
agree = pd.DataFrame(index=names, columns=names, dtype=float)
comparable = pd.DataFrame(index=names, columns=names, dtype=float)
for a in names:
    for b in names:
        m = st[a].notna() & st[b].notna()
        comparable.loc[a, b] = m.sum()
        agree.loc[a, b] = 100 * (st.loc[m, a] == st.loc[m, b]).mean() if m.any() else np.nan
fig = px.imshow(agree.astype(float), text_auto=".1f", color_continuous_scale=SEQ_BLUE, zmin=80, zmax=100,
                title="% of facility rows where two state sources agree (among rows where both have a value)")
show(fig, height=480)
display(comparable.astype(int).reset_index().rename(columns={"index": "rows comparable"}))

# COMMAND ----------

# MAGIC %md ## 2 · Agreement patterns (pincode directory vs written text vs facility coordinates)

# COMMAND ----------

d, w, c = st["pincode directory"], st["written text"], st["facility coords"]


def pattern(row):
    dd, ww, cc = row
    have = [x is not None and x == x for x in (dd, ww, cc)]
    if not all(have):
        missing = [n for n, h in zip(("pincode state", "text state", "coords in India"), have) if not h]
        return "incomplete: no " + " / ".join(missing)
    if dd == ww == cc:
        return "all three agree"
    if dd == ww:
        return "coords disagree (pincode = text)"
    if ww == cc:
        return "pincode disagrees (text = coords)"
    if dd == cc:
        return "text disagrees (pincode = coords)"
    return "all three differ"


fr["state_pattern"] = [pattern(r) for r in zip(d, w, c)]
pat = fr.groupby("state_pattern").agg(rows=("fac_row_id", "size"), median_km=("dist_km", "median"),
                                      mean_km=("dist_km", "mean"), p90_km=("dist_km", lambda x: x.quantile(.9)),
                                      pct_within_footprint=("within_pin_footprint", lambda x: 100 * x.fillna(False).astype(bool).mean()))
pat["pct_rows"] = 100 * pat["rows"] / len(fr)
display(pat.sort_values("rows", ascending=False).reset_index().round(2))

# COMMAND ----------

order = pat.sort_values("rows", ascending=False).index.tolist()
dd_ = fr[fr["dist_km"].notna()].assign(dist_plot=lambda x: x["dist_km"].clip(lower=0.01))
fig = px.box(dd_, x="dist_plot", y="state_pattern", orientation="h", log_x=True, category_orders={"state_pattern": order},
             color_discrete_sequence=[SERIES[0]], hover_data=["name", "pin_clean", "address_stateOrRegion"],
             title=f"Facility-to-pincode distance by agreement pattern ({PRIMARY_STRATEGY})")
show(fig, height=450)

# COMMAND ----------

# MAGIC %md ### Which states each disagreement flows between

# COMMAND ----------

for p, a, b in [("coords disagree (pincode = text)", "pincode directory", "facility coords"),
                ("pincode disagrees (text = coords)", "pincode directory", "facility coords"),
                ("text disagrees (pincode = coords)", "written text", "pincode directory")]:
    sub = st[fr["state_pattern"] == p]
    flows = sub.groupby([a, b]).size().sort_values(ascending=False).head(25).rename("rows").reset_index()
    print(f"\n{p}: top flows ({a} → {b})")
    display(flows)

# COMMAND ----------

# MAGIC %md ## 3 · Maps: one panel per disagreement pattern
# MAGIC Line = pincode point → facility point. Facilities without a usable pincode point are drawn as dots only.

# COMMAND ----------

panels = [p for p in order if p != "all three agree"]
cols = 3
rows = math.ceil(len(panels) / cols)
fig, axes = plt.subplots(rows, cols, figsize=(6 * cols, 6.3 * rows), squeeze=False)
for ax in axes.ravel()[len(panels):]:
    ax.axis("off")
for ax, p in zip(axes.ravel(), panels):
    g = fr[fr["state_pattern"] == p]
    basemap.boundary.plot(ax=ax, color=BASEMAP_EDGE, linewidth=0.4)
    lines = g[g["dist_km"].notna() & (g["fac_point_status"] == "OK")]
    for lab in BUCKET_LABELS:
        b = lines[lines["bucket"] == lab]
        if len(b):
            segs = np.stack([b[["pin_lon", "pin_lat"]].to_numpy(), b[["fac_lon", "fac_lat"]].to_numpy()], axis=1)
            ax.add_collection(LineCollection(segs, colors=BUCKET_COLORS[lab], linewidths=0.8, alpha=0.8))
            ax.scatter(b["fac_lon"], b["fac_lat"], s=5, color=BUCKET_COLORS[lab], zorder=3)
    dots = g[g["dist_km"].isna() & (g["fac_point_status"] == "OK")]
    ax.scatter(dots["fac_lon"], dots["fac_lat"], s=10, color=PIN_BAD_COLOR, marker="x", zorder=4)
    ax.set_xlim(67.5, 98); ax.set_ylim(6, 37.5); ax.set_aspect(1.1); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"{p}\nrows={len(g)}  with both points={len(lines)}", fontsize=10)
handles = [plt.Line2D([], [], color=BUCKET_COLORS[l], lw=2, label=l) for l in BUCKET_LABELS]
handles.append(plt.Line2D([], [], color=PIN_BAD_COLOR, marker="x", ls="", label="no usable pincode point"))
fig.legend(handles=handles, loc="upper center", ncol=7, frameon=False)
fig.tight_layout(rect=(0, 0, 1, 0.97))
plt.show()

# COMMAND ----------

# MAGIC %md ## 4 · Does pincode ambiguity explain disagreement?
# MAGIC A pincode whose offices sit in more than one state or district gives an ambiguous "directory" answer.

# COMMAND ----------

fr["pin_multi_state"] = fr["pin_state_n_distinct"].fillna(0) > 1
fr["pin_multi_district"] = fr["pin_state_district_n_distinct"].fillna(0) > 1
amb = fr[fr["dir_state"].notna()].groupby(["pin_multi_state", "pin_multi_district"]).agg(
    rows=("fac_row_id", "size"),
    pct_dir_vs_coords_disagree=("state_pattern", lambda s: 100 * s.isin(["coords disagree (pincode = text)", "pincode disagrees (text = coords)", "all three differ"]).mean()),
    median_km=("dist_km", "median"), p90_km=("dist_km", lambda x: x.quantile(.9)))
display(amb.reset_index().round(2))

spread = fr[fr["dist_km"].notna() & fr["pin_spread_max_km"].notna()]
fig = px.scatter(spread, x=spread["pin_spread_max_km"].clip(lower=0.01), y=spread["dist_km"].clip(lower=0.01),
                 log_x=True, log_y=True, color="state_pattern", category_orders={"state_pattern": order},
                 color_discrete_sequence=SERIES, hover_data=["name", "pin_clean"], opacity=0.6,
                 labels={"x": "pincode office spread: max km of an office from the pincode median",
                         "y": "facility-to-pincode distance km"},
                 title="Facility distance vs how spread out its pincode's offices are (above the diagonal = outside the pincode footprint)")
fig.add_trace(go.Scatter(x=[0.01, 3000], y=[0.01, 3000], mode="lines", line=dict(dash="dot", color="#52514e"), name="y = x"))
fig.update_traces(marker=dict(size=5), selector=dict(mode="markers"))
show(fig, height=650)

# COMMAND ----------

# MAGIC %md ## 5 · Every scheme: definition vs region at facility point vs region at pincode point

# COMMAND ----------

rows = []
for scheme, cfg in SCHEMES.items():
    for a, b, label in [(scheme, f"{scheme}__fac_pt", "definition vs facility point"),
                        (scheme, f"{scheme}__pin_pt", "definition vs pincode point"),
                        (f"{scheme}__fac_pt", f"{scheme}__pin_pt", "facility point vs pincode point")]:
        if a not in fr or b not in fr or fr[a].equals(fr[b]):
            continue
        aa, bb = fr[a], fr[b]
        if scheme == "fac_stated_state":
            aa = aa.where(aa != UNRESOLVED_STATE)
        m = aa.notna() & bb.notna()
        rows.append(dict(scheme=scheme, title=cfg["title"], comparison=label, rows_comparable=int(m.sum()),
                         pct_agree=round(100 * (aa[m] == bb[m]).mean(), 2) if m.any() else np.nan))
agree_all = pd.DataFrame(rows)
display(agree_all)
fig = px.bar(agree_all, x="pct_agree", y="title", color="comparison", barmode="group", orientation="h",
             color_discrete_sequence=SERIES[:3], range_x=[min(50, agree_all["pct_agree"].min() - 5), 100],
             title="Region-assignment agreement by scheme (finer schemes disagree more for the same physical error)")
fig.update_traces(marker_line_color="#fcfcfb", marker_line_width=1)
show(fig, height=600)

# COMMAND ----------

# MAGIC %md ## 6 · Coordinates shared by many facilities (possible default / batch geocodes)
# MAGIC Facilities in different cities that share the *exact* same latitude/longitude suggest the coordinates came
# MAGIC from a fallback point (city centroid, state centroid, or a geocoder default) rather than the facility itself.

# COMMAND ----------

fc = fr[fr["fac_point_status"] == "OK"].copy()
fc["coord_key"] = fc["fac_lat"].round(5).astype(str) + "," + fc["fac_lon"].round(5).astype(str)
grp = fc.groupby("coord_key").agg(
    facilities=("fac_row_id", "size"), lat=("fac_lat", "first"), lon=("fac_lon", "first"),
    distinct_pins=("pin_clean", "nunique"), distinct_cities=("address_city", "nunique"),
    distinct_dir_states=("dir_state", "nunique"),
    spatial_state=("spatial_state", "first"),
    dir_states=("dir_state", lambda s: ", ".join(sorted(set(s.dropna()))[:6])),
    cities=("address_city", lambda s: ", ".join(sorted(set(s.dropna().astype(str)))[:6])),
    median_km=("dist_km", "median"))
shared = grp[grp["facilities"] >= 3].sort_values("facilities", ascending=False)
fr["coord_shared_n"] = fr.merge(fc[["fac_row_id", "coord_key"]], on="fac_row_id", how="left")["coord_key"].map(grp["facilities"]).fillna(0).astype(int).to_numpy()
print(f"coordinate points shared by >= 3 facility rows: {len(shared):,}, covering {shared['facilities'].sum():,} rows; "
      f"of these points, {(shared['distinct_pins'] > 1).sum():,} are shared across different pincodes")
display(shared.reset_index().round(2).head(60))
by_share = fr[fr["dist_km"].notna()].assign(shared=lambda x: np.select(
    [x["coord_shared_n"] >= 10, x["coord_shared_n"] >= 3, x["coord_shared_n"] == 2], ["10+", "3-9", "2"], "unique"))
display(by_share.groupby("shared").agg(rows=("fac_row_id", "size"), median_km=("dist_km", "median"),
                                       p90_km=("dist_km", lambda x: x.quantile(.9)),
                                       pct_gt_25km=("dist_km", lambda x: 100 * (x > 25).mean())).reset_index().round(2))

# COMMAND ----------

# MAGIC %md ## 7 · Persist the per-facility agreement pattern

# COMMAND ----------

out = fr[["fac_row_id", "unique_id", "name", "state_pattern", "dir_state", "fac_stated_state", "spatial_state",
          "dir_state__pin_pt", "pin_multi_state", "pin_multi_district", "coord_shared_n", "dist_km",
          "within_pin_footprint"]].copy()
out["within_pin_footprint"] = out["within_pin_footprint"].astype("object")
write_table(out, "state_agreement", "Bronze: per facility row, the state from each of four sources and the "
            f"agreement pattern; dist_km uses strategy {PRIMARY_STRATEGY}.")
