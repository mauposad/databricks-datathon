# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Publish location scores for the app (one row per `cluster_id`)
# MAGIC
# MAGIC Publishes two tables into the app schema (`publish_catalog.publish_schema`, default `workspace.datathon`):
# MAGIC
# MAGIC | table | grain | read by |
# MAGIC |---|---|---|
# MAGIC | `bronze_locval_facilities_repaired` | one row per **source row**, CSV-split rows repaired (copy of the bronze table) | `src/02_silver_facilities.sql`, which reads it instead of the raw share |
# MAGIC | `silver_location_validation` | one row per **`facility_id` = `cluster_id`**, the app's facility id | silver → gold → `find_care` → app |
# MAGIC
# MAGIC **Which row's score a cluster gets.** Silver keeps one representative row per cluster: the longest
# MAGIC `capability` + `procedure` text, ties broken by `unique_id`. This notebook picks the **same row**, so the score
# MAGIC always describes the address, phones and coordinates the app shows. The range across the cluster's other rows is
# MAGIC kept in `min_score_in_cluster` / `max_score_in_cluster`.
# MAGIC
# MAGIC A facility in silver with **no** row here is flagged `location_not_validated` downstream (it stays in results).

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 plotly==5.24.1 phonenumbers==9.0.44 rapidfuzz==3.13.0 --quiet

# COMMAND ----------

# MAGIC %run ./_scoring_common

# COMMAND ----------

dbutils.widgets.text("publish_catalog", "workspace", "Publish catalog")
dbutils.widgets.text("publish_schema", "datathon", "Publish schema")
PUB = f"{dbutils.widgets.get('publish_catalog')}.{dbutils.widgets.get('publish_schema')}"

for t in (vtbl("scores"), vtbl("facilities_repaired")):
    assert spark.catalog.tableExists(t), f"{t} is missing: run notebooks 00-02 first"

# Plain-language labels and reasons, shown on the app's cards
CHECKS = [  # (key, column, label, kind)
    ("pincode", "chk_pincode", "Pincode is a real India Post pincode in the stated state", "main"),
    ("city_state", "chk_city_state", "City matches a district or post office in the stated state", "main"),
    ("district_region", "chk_district_region", "District and postal region agree across two sources", "main"),
    ("circle_division", "chk_circle_division", "Postal circle and division agree across two sources", "main"),
    ("coordinates", "chk_coordinates", f"Map point within {COORD_MATCH_KM:g} km of the pincode's post offices", "secondary"),
    ("phone", "chk_phone", "Phone numbers point to the stated or pincode state", "secondary"),
]
WHY_TEXT = {
    "pincode_missing": "No pincode in the record.",
    "pincode_not_in_directory": "The pincode is not in the India Post directory.",
    "pincode_state_differs_from_stated_state": "The pincode belongs to a different state than the address says.",
    "pincode_no_state_and_no_city": "No state or city to check the pincode against.",
    "pincode_no_state_city_not_in_pincode": "No state given, and the city is not among the pincode's post offices.",
    "state_missing_or_unresolved": "The state is missing or not a recognisable state name.",
    "city_missing": "No city in the record.",
    "city_not_found_in_stated_state": "The city was not found among the districts or post offices of the stated state.",
    "fewer_than_two_sources": "Fewer than two of pincode, city text and map point could be placed in the directory.",
    "sources_disagree": "Pincode, city text and map point name different areas.",
    "point_outside_india": "The map point is outside India.",
    "no_geocoded_reference_office": "No geocoded post office to compare the map point with.",
    "phone_missing": "No phone number in the record.",
    "phone_not_locatable": "None of the phone numbers could be placed (toll-free, invalid or unknown series).",
    "no_reference_state": "No state to compare the phone numbers with.",
    "single_phone_state_differs": "The only phone number belongs to a different state.",
    "fewer_than_two_phones_match": "Fewer than two of the phone numbers belong to the facility's state.",
}


def why_text(code):
    if not code:
        return None
    if code.startswith("nearest_reference_office_"):
        km = code.removeprefix("nearest_reference_office_").removesuffix("_km")
        return f"The map point is {km} km from the nearest post office of its pincode."
    return WHY_TEXT.get(code, code.replace("_", " "))

# COMMAND ----------

# MAGIC %md ## 1 · Repaired facility rows → app schema

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {PUB}.bronze_locval_facilities_repaired
COMMENT 'Copy of workspace.default.bronze_locval_facilities_repaired: every facilities row, CSV-split rows merged into their head (repair_status). src/02_silver_facilities.sql reads this instead of the raw share. Built by notebooks/location_validation_scoring.'
AS SELECT * FROM {vtbl('facilities_repaired')}
""")
print(f"wrote {PUB}.bronze_locval_facilities_repaired")

# COMMAND ----------

# MAGIC %md ## 2 · One score per cluster

# COMMAND ----------

rep = spark.sql(f"""
SELECT cluster_id, unique_id, fac_row_id,
       row_number() OVER (PARTITION BY cluster_id
                          ORDER BY length(coalesce(capability, '')) + length(coalesce(procedure, '')) DESC, unique_id, fac_row_id) AS rn,
       count(*) OVER (PARTITION BY cluster_id) AS n_rows_in_cluster
FROM {vtbl('facilities_repaired')}
WHERE repair_status IN ('clean', 'repaired_head', 'head_no_tail')
  AND organization_type = 'facility' AND cluster_id IS NOT NULL AND cluster_id <> ''
""").toPandas()
scores = spark.table(vtbl("scores")).toPandas()
rng = (scores[scores.cluster_id.notna()].groupby("cluster_id")["location_validation_score"]
       .agg(min_score_in_cluster="min", max_score_in_cluster="max", n_rows_scored="size").reset_index())
# join on the exact source row: 11 unique_ids appear on two source rows each, so unique_id alone is not a key
pick = (rep[rep.rn == 1].drop(columns="rn")
        .merge(scores.drop(columns=["cluster_id", "unique_id"]), on="fac_row_id", how="left"))
assert not pick.cluster_id.duplicated().any(), "more than one row per cluster_id"
pick = pick.merge(rng, on="cluster_id", how="left")


def checks_of(r):
    out = []
    for key, col, label, kind in CHECKS:
        v = r[col]
        status = ("pass" if v else "fail") if isinstance(v, (bool, np.bool_)) else (v if isinstance(v, str) else None)
        out.append({"check_key": key, "check_label": label, "kind": kind, "status": status,
                    "why": why_text(r[f"why_{key}"]) if status == "fail" else None})
    return out


scored = pick["location_validation_score"].notna()
pub = pd.DataFrame({
    "facility_id": pick["cluster_id"],
    "unique_id": pick["unique_id"],
    "n_rows_in_cluster": pick["n_rows_in_cluster"].astype(int),
    "n_rows_scored": pick["n_rows_scored"].fillna(0).astype(int),
    "location_validation_status": np.where(scored, "scored", "not_scored"),
    "location_validation_score": pick["location_validation_score"].astype("Int64"),
    "location_validation_label": pick["location_validation_label"],
    "location_validation_passed": pick["location_validation_passed"].astype("boolean"),
    "n_main_pass": pick["n_main_pass"].astype("Int64"),
    "failed_checks": pick["failed_checks"],
    "min_score_in_cluster": pick["min_score_in_cluster"].astype("Int64"),
    "max_score_in_cluster": pick["max_score_in_cluster"].astype("Int64"),
    "repair_status": pick["repair_status"],
    "scoring_version": pick["scoring_version"],
    "scored_at": pick["scored_at"],
})
pub["location_checks"] = [checks_of(r) if s else None for (_, r), s in zip(pick.iterrows(), scored)]
pub["published_at"] = now_utc()

schema = """facility_id STRING, unique_id STRING, n_rows_in_cluster INT, n_rows_scored INT,
  location_validation_status STRING, location_validation_score INT, location_validation_label STRING,
  location_validation_passed BOOLEAN, n_main_pass INT, failed_checks STRING,
  min_score_in_cluster INT, max_score_in_cluster INT, repair_status STRING, scoring_version STRING, scored_at TIMESTAMP,
  location_checks ARRAY<STRUCT<check_key: STRING, check_label: STRING, kind: STRING, status: STRING, why: STRING>>,
  published_at TIMESTAMP"""
def to_py(v):
    """numpy / pandas scalars -> plain Python, so createDataFrame accepts them against the explicit schema."""
    if v is None or v is pd.NA or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        return v.item()
    return v


records = [{k: to_py(v) for k, v in r.items()} for r in pub.astype(object).to_dict("records")]
sdf = spark.createDataFrame(records, schema=schema)
full = f"{PUB}.silver_location_validation"
sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(full)
spark.sql(f"""COMMENT ON TABLE {full} IS {json.dumps(
    f'Location validation score per facility_id (= cluster_id), v{SCORING_VERSION}: 0-5, pass >= {PASS_SCORE}. The score '
    'is that of the row silver keeps for the cluster (longest capability+procedure). location_checks = the six checks '
    'with plain-language reasons. Rules: notebooks/location_validation_scoring/SCORING_CRITERIA.md')}""")
print(f"wrote {full}: {len(pub):,} facilities")

display(pub.groupby(["location_validation_status", "location_validation_score"], dropna=False).size()
        .rename("facilities").reset_index())
