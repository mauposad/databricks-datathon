# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Phone reference: mobile series → telecom circle
# MAGIC
# MAGIC Builds `bronze_locval_mobile_prefix`: one row for **every** 4-digit mobile series 6000–9999, with its telecom
# MAGIC circle and where that circle came from.
# MAGIC
# MAGIC 1. **CSV lookup**: download the in-mob-prefix CSVs (pinned commit, CC BY 4.0) into the `locval_ref` volume
# MAGIC    (skipped when the file is already there). A series listed with a circle → `circle_source = 'csv'`.
# MAGIC 2. **Model prediction** for series that are absent from the CSV or listed with a blank circle. in-mob-prefix
# MAGIC    does **not** publish its trained models (`models/` is git-ignored) and its recipe predicts the *operator*,
# MAGIC    not the circle. So we retrain its exact recipe (`GradientBoostingClassifier(n_estimators=75, max_depth=2,
# MAGIC    random_state=42)` on the series number, one model per leading digit) with **circle** as the target, save
# MAGIC    the models to the volume and use their prediction → `circle_source = 'model'`, with the class probability
# MAGIC    and the model's hold-out accuracy recorded next to it.
# MAGIC
# MAGIC Attribution: hstsethi/in-mob-prefix, CC BY 4.0, commit `153ba80`.

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 plotly==5.24.1 phonenumbers==9.0.44 rapidfuzz==3.13.0 --quiet

# COMMAND ----------

# MAGIC %run ./_scoring_common

# COMMAND ----------

import io

import joblib
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

spark.sql(f"CREATE VOLUME IF NOT EXISTS {OUT_CATALOG}.{OUT_SCHEMA}.{REF_VOLUME}")
csv_dir = f"{REF_DIR}/in-mob-prefix/{MOBPREFIX_COMMIT[:7]}"
model_dir = f"{REF_DIR}/models/{MOBPREFIX_COMMIT[:7]}"
os.makedirs(csv_dir, exist_ok=True)
os.makedirs(model_dir, exist_ok=True)

frames = []
for lvl in MOBPREFIX_LEVELS:
    path = f"{csv_dir}/{lvl}xxx-in-mob-prefix.csv"
    if os.path.exists(path):
        print(f"{lvl}xxx: using existing {path}")
    else:
        with urllib.request.urlopen(mobprefix_url(lvl), timeout=60) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
        print(f"{lvl}xxx: downloaded {len(data):,} bytes -> {path}")
    df = pd.read_csv(path, dtype=str)
    df["level"] = lvl
    frames.append(df)

csv = pd.concat(frames, ignore_index=True)
csv["series"] = pd.to_numeric(csv["series"], errors="coerce")
csv = csv.dropna(subset=["series"])
csv["series"] = csv["series"].astype(int)
csv["circle"] = csv["circle"].str.strip().str.upper().replace({"": None})
csv["operator"] = csv["operator"].str.strip().str.upper().replace({"": None})
dupes = csv[csv.duplicated("series", keep=False)]
print(f"CSV rows: {len(csv):,}; duplicate series: {dupes.series.nunique()} (first listing kept)")
csv = csv.drop_duplicates("series", keep="first")
unknown = sorted(set(csv.circle.dropna()) - set(TELECOM_CIRCLE_STATES))
assert not unknown, f"circle codes missing from TELECOM_CIRCLE_STATES: {unknown}"
display(csv.groupby("level").agg(rows=("series", "size"), blank_circle=("circle", lambda s: s.isna().sum())))

# COMMAND ----------

# MAGIC %md ## Train the circle models (in-mob-prefix recipe, circle as target)

# COMMAND ----------

models, accuracy = {}, {}
for lvl in MOBPREFIX_LEVELS:
    d = csv[(csv.level == lvl) & csv.circle.notna()]
    path = f"{model_dir}/{lvl}xxx-circle-gbc.joblib"
    X, y = d[["series"]].to_numpy(), d["circle"].to_numpy()
    # in-mob-prefix's train_test_split call has no random_state; we fix it so reruns give the same models
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, random_state=42)
    gbc = GradientBoostingClassifier(n_estimators=75, max_depth=2, random_state=42).fit(X_tr, y_tr)
    accuracy[lvl] = float(accuracy_score(y_te, gbc.predict(X_te)))
    # the saved model is refit on every labelled series so no known series is wasted
    gbc = GradientBoostingClassifier(n_estimators=75, max_depth=2, random_state=42).fit(X, y)
    joblib.dump(gbc, path)
    models[lvl] = gbc
    print(f"{lvl}xxx: {len(d)} labelled series, hold-out accuracy {accuracy[lvl]:.2f} -> {path}")

# COMMAND ----------

# MAGIC %md ## Every series 6000–9999: CSV circle, else model prediction

# COMMAND ----------

allser = pd.DataFrame({"series": np.arange(6000, 10000)})
allser["level"] = (allser.series // 1000).astype(str)
ref = allser.merge(csv[["series", "operator", "circle"]], on="series", how="left")
ref["in_csv"] = ref.series.isin(csv.series)
ref["circle_source"] = np.where(ref.circle.notna(), "csv", "model")
ref["circle_probability"] = np.where(ref.circle.notna(), 1.0, np.nan)
ref["model_holdout_accuracy"] = np.nan
for lvl, gbc in models.items():
    m = (ref.level == lvl) & ref.circle.isna()
    if m.any():
        X = ref.loc[m, ["series"]].to_numpy()
        ref.loc[m, "circle"] = gbc.predict(X)
        ref.loc[m, "circle_probability"] = gbc.predict_proba(X).max(axis=1)
        ref.loc[m, "model_holdout_accuracy"] = accuracy[lvl]
ref["circle_states"] = ref.circle.map(lambda c: "|".join(sorted(TELECOM_CIRCLE_STATES.get(c, set()))))
ref["source_commit"] = MOBPREFIX_COMMIT
display(ref.groupby(["level", "circle_source"]).size().unstack(fill_value=0))

write_vtable(ref, "mobile_prefix",
             "Every 4-digit Indian mobile series 6000-9999 -> telecom circle. circle_source='csv': listed in "
             "hstsethi/in-mob-prefix (CC BY 4.0, commit 153ba80); 'model': predicted by a GradientBoosting model "
             "trained with in-mob-prefix's recipe on circle. circle_states = states the telecom circle covers.")
