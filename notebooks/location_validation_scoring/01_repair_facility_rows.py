# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Repair split facility rows
# MAGIC
# MAGIC About 90 rows of `facilities` have `address_countryCode` ≠ `IN`. They are **not** separate facilities: the
# MAGIC source CSV was parsed with newlines inside quoted text (mostly `description`), so one facility became a
# MAGIC **head** row (identity, phones, address, start of the description; coordinates empty) followed by
# MAGIC **fragment** rows holding the rest of the text, the last of which (the **tail**) carries the facility's
# MAGIC GeoJSON point shifted into an earlier column.
# MAGIC
# MAGIC The parquet file keeps the original row order, so `(_metadata.file_name, _metadata.row_index)` puts every
# MAGIC fragment directly after its head. The repair:
# MAGIC
# MAGIC 1. Order rows physically; every `IN` row starts a group, every following non-`IN` row joins that group.
# MAGIC 2. In each group the last fragment containing a GeoJSON `Point` is the tail. Its column offset is
# MAGIC    `position(GeoJSON) - position(coordinates)`; shifting the tail back by that offset realigns `coordinates`,
# MAGIC    `latitude`, `longitude`, `cluster_id` and `source_urls`.
# MAGIC 3. The head gets the tail's coordinates (from the GeoJSON, which is unambiguous) plus `cluster_id` and
# MAGIC    `source_urls`; fragment text is kept in `fragment_text` for reference. Other columns are not touched.
# MAGIC
# MAGIC Output `bronze_locval_facilities_repaired` keeps **every** source row, with `repair_status`:
# MAGIC
# MAGIC | repair_status | meaning |
# MAGIC |---|---|
# MAGIC | `clean` | normal row, unchanged |
# MAGIC | `repaired_head` | head row; coordinates etc. recovered from its tail |
# MAGIC | `head_no_tail` | head row whose fragments held no coordinates |
# MAGIC | `fragment_merged` | fragment absorbed into its head (not a facility; not scored) |
# MAGIC | `fragment_orphan` | non-`IN` row with no preceding head (not a facility; scored 0) |

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 plotly==5.24.1 phonenumbers==9.0.44 rapidfuzz==3.13.0 --quiet

# COMMAND ----------

# MAGIC %run ./_scoring_common

# COMMAND ----------

raw = (spark.table(src("facilities"))
       .select("*", F.col("_metadata.file_name").alias("_file"), F.col("_metadata.row_index").alias("_row_index"))
       .toPandas())
COLS = [c for c in raw.columns if c not in ("_file", "_row_index")]
CI = {c: i for i, c in enumerate(COLS)}
raw = raw.sort_values(["_file", "_row_index"]).reset_index(drop=True)
raw["fac_row_id"] = raw["_file"].str.slice(0, 40) + ":" + raw["_row_index"].astype(str)
print(f"{len(raw):,} source rows in {raw._file.nunique()} file(s)")


def is_blank(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or str(v).strip() in ("", "null", "None")


raw["is_head"] = raw["address_countryCode"].fillna("").str.strip().eq("IN")
raw["group_id"] = raw.groupby("_file")["is_head"].cumsum()
raw["_group_key"] = raw["_file"] + "#" + raw["group_id"].astype(str)
display(raw["is_head"].value_counts().rename_axis("is_head").reset_index(name="rows"))

# COMMAND ----------

GEO_RE = re.compile(r'\{\s*"coordinates"\s*:\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]\s*,\s*"type"\s*:\s*"Point"\s*\}')

rows = raw.to_dict("records")
repair = {}       # head index -> dict of recovered fields
status = ["clean" if r["is_head"] else None for r in rows]
parent = [None] * len(rows)
log = []

for key, idx in raw.groupby("_group_key").groups.items():
    idx = sorted(idx)
    head = idx[0] if rows[idx[0]]["is_head"] else None
    frags = idx[1:] if head is not None else idx
    if head is None:  # fragments before the first head of a file
        for i in frags:
            status[i] = "fragment_orphan"
        continue
    if not frags:
        continue
    tail, tail_pos, tail_geo = None, None, None
    for i in frags:
        for c in COLS:
            v = rows[i][c]
            if isinstance(v, str):
                m = GEO_RE.search(v)
                if m:
                    tail, tail_pos, tail_geo = i, CI[c], (float(m.group(1)), float(m.group(2)))
                    break
    texts = []
    for i in frags:
        status[i] = "fragment_merged"
        parent[i] = rows[head]["unique_id"]
        texts.extend(str(rows[i][c]).strip() for c in COLS
                     if isinstance(rows[i][c], str) and not is_blank(rows[i][c]) and not GEO_RE.search(rows[i][c]))
    rec = {"fragment_text": " | ".join(texts)[:20000], "n_fragments": len(frags)}
    if tail is not None:
        off = tail_pos - CI["coordinates"]
        vals = [rows[tail][c] for c in COLS]

        def realigned(c):
            j = CI[c] + off
            return vals[j] if 0 <= j < len(vals) else None

        lon, lat = tail_geo
        rec.update(coordinates=json.dumps({"coordinates": [lon, lat], "type": "Point"}), latitude=lat,
                   longitude=lon, cluster_id=realigned("cluster_id"), source_urls=realigned("source_urls"),
                   tail_offset=off, tail_row_id=rows[tail]["fac_row_id"])
        # sanity: the realigned latitude/longitude cells should repeat the GeoJSON point
        try:
            rec["realign_check"] = bool(abs(float(realigned("latitude")) - lat) < 1e-4
                                        and abs(float(realigned("longitude")) - lon) < 1e-4)
        except (TypeError, ValueError):
            rec["realign_check"] = None
        status[head] = "repaired_head"
    else:
        status[head] = "head_no_tail"
    repair[head] = rec
    log.append(dict(head_row=rows[head]["fac_row_id"], unique_id=rows[head]["unique_id"], name=rows[head]["name"],
                    address_city=rows[head]["address_city"], n_fragments=len(frags), status=status[head],
                    tail_offset=rec.get("tail_offset"), lat=rec.get("latitude"), lon=rec.get("longitude"),
                    realign_check=rec.get("realign_check")))

repair_log = pd.DataFrame(log)
display(repair_log)

# COMMAND ----------

out = raw[COLS + ["fac_row_id", "_file", "_row_index"]].copy()
out["repair_status"] = status
out["parent_unique_id"] = parent
for c in ("fragment_text", "tail_row_id"):
    out[c] = None
out["n_fragments"] = 0
out["tail_offset"] = np.nan
for i, rec in repair.items():
    for c in ("coordinates", "latitude", "longitude", "cluster_id", "source_urls", "fragment_text", "tail_row_id",
              "n_fragments", "tail_offset"):
        if c in rec:
            out.at[i, c] = rec[c]
out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")
out = out.rename(columns={"_file": "source_file", "_row_index": "source_row_index"})
# every column except the numeric ones stays a string, like the source table
for c in out.columns:
    if c not in ("latitude", "longitude", "source_row_index", "n_fragments", "tail_offset"):
        out[c] = out[c].map(lambda v: None if v is None or (isinstance(v, float) and math.isnan(v)) else str(v))

summary = out["repair_status"].value_counts().rename_axis("repair_status").reset_index(name="rows")
display(summary)
dup = out[out.repair_status.isin(["clean", "repaired_head", "head_no_tail"])].unique_id.duplicated(keep=False)
print(f"facility rows: {(~out.repair_status.str.startswith('fragment')).sum():,}; "
      f"duplicate unique_id among them: {dup.sum()}")

write_vtable(out, "facilities_repaired",
             "facilities with CSV-split rows repaired: heads get coordinates/cluster_id/source_urls from their "
             "shifted tail row (matched by physical parquet row order). repair_status: clean, repaired_head, "
             "head_no_tail, fragment_merged, fragment_orphan. Fragments are kept but are not facilities.")
write_vtable(repair_log, "repair_log", "One row per repaired head: fragments absorbed, tail column offset, recovered point.")
