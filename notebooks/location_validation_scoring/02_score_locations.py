# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Location validation score (v1.1)
# MAGIC
# MAGIC Gives every facility a `location_validation_score` (0–5) and pass/fail flag, written to
# MAGIC `bronze_locval_scores`. The rules are in `SCORING_CRITERIA.md` and summarised here:
# MAGIC
# MAGIC **Main checks** (each `pass` = 1, `partial` = 0.5 or `fail` = 0; a missing input fails):
# MAGIC
# MAGIC | check | passes when |
# MAGIC |---|---|
# MAGIC | `pincode` | pincode is in the India Post directory **and** one of its offices is in the stated state (no stated state: an office or district of the pincode fuzzy-matches the city). A pincode missing from the directory may be replaced by its nearest same-5-digit neighbour in the stated state: **partial**. |
# MAGIC | `city_state` | stated state resolves **and** the city fuzzy-matches (≥ 0.85) a directory district (or, failing that, office) in that state. No usable state but the city matches districts of exactly one state nationally: **partial** (state inferred). |
# MAGIC | `district_region` | the city-text offices (**T**) share the same **district and India Post region** with the pincode offices (**P**) or the geocoded offices near the point (**G**) |
# MAGIC | `circle_division` | the same, for **India Post circle and division** |
# MAGIC
# MAGIC **Secondary check**: `coordinates`. The point must lie within `clamp(spread_p90_km, 10, 25)` km of the
# MAGIC pincode's median office point (the city match's median when the pincode is unusable). A point shared by
# MAGIC ≥ 3 different facilities fails. Missing coordinates are neutral. Phone numbers are not scored (v1.1).
# MAGIC
# MAGIC **Score (MCDM, swing weights)**: `S = Σ wᵢ·vᵢ / Σ wᵢ` over the checks with input. Weights: pincode 0.25,
# MAGIC city/state 0.225, coordinates 0.20, district/region 0.175, circle/division 0.15.
# MAGIC
# MAGIC | score | rule | passes |
# MAGIC |---|---|---|
# MAGIC | 5 | gate passed and S ≥ 0.85 | yes |
# MAGIC | 4 | gate passed and S ≥ 0.70 | yes |
# MAGIC | 3 | gate passed and S ≥ 0.60 | yes |
# MAGIC | 2 | gate failed (main-check values sum < 2), or S < 0.60 | no |
# MAGIC | 1 | no location data at all (no city, state, pincode or coordinates) | no |
# MAGIC | 0 | not a facility record (orphan CSV fragment) | no |
# MAGIC
# MAGIC Inputs: `bronze_locval_facilities_repaired` (notebook 01), `bronze_loclink_offices` and
# MAGIC `bronze_loclink_pincodes` (`../location_linkage/00_build_location_pairs`).

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 plotly==5.24.1 rapidfuzz==3.13.0 --quiet

# COMMAND ----------

# MAGIC %run ./_scoring_common

# COMMAND ----------

from collections import defaultdict

from rapidfuzz import process
from sklearn.neighbors import BallTree

for t in (vtbl("facilities_repaired"), tbl("offices"), tbl("pincodes")):
    assert spark.catalog.tableExists(t), (
        f"{t} is missing: run 01_repair_facility_rows and ../location_linkage/00_build_location_pairs first "
        f"(or the location_validation_scoring job)")

fac_all = spark.table(vtbl("facilities_repaired")).toPandas()
off = spark.table(tbl("offices")).toPandas()
pins = spark.table(tbl("pincodes")).select("pincode", "lat_office_median", "lon_office_median", "spread_p90_km").toPandas()
print(f"facility rows {len(fac_all):,}; offices {len(off):,}; pincodes {len(pins):,}")
print("MCDM weights:", {k: round(v, 4) for k, v in MCDM_WEIGHTS.items()})

# COMMAND ----------

# MAGIC %md ## Directory: normalised names and lookup structures

# COMMAND ----------

off = off.reset_index(drop=True)
off["state"] = off["statename"].map(canon_state)
off["district_n"] = off["district"].map(norm_place)
off["office_n"] = off["officename"].map(norm_place)
off["region_n"] = off["regionname"].map(norm_text)
off["circle_n"] = off["circlename"].map(norm_text)
off["division_n"] = off["divisionname"].map(norm_text)
# offices usable as a *location* reference: coordinates inside India and inside the office's own state
off["geo_ok"] = off["point_status"].eq("OK") & off["spatial_state_matches_statename"].fillna(False).astype(bool)
# plain numpy columns: the per-facility loops index these instead of pandas .loc (much faster)
A = {c: off[c].to_numpy(dtype=object) for c in ("state", "district_n", "office_n", "region_n", "circle_n", "division_n")}
A_LAT, A_LON, A_GEO_OK = off["lat"].to_numpy(dtype=float), off["lon"].to_numpy(dtype=float), off["geo_ok"].to_numpy(dtype=bool)


def vals(ix, col):
    return {v for v in A[col][ix] if v is not None and v == v}

pin_offices = {p: np.asarray(ix) for p, ix in off.groupby("pincode").groups.items()}
pin_states = off.groupby("pincode")["state"].apply(lambda s: set(s.dropna())).to_dict()
pins_by_prefix5 = defaultdict(list)
for p in pin_offices:
    pins_by_prefix5[int(p) // 10].append(int(p))
state_district_offices = {k: np.asarray(ix) for k, ix in off.groupby(["state", "district_n"]).groups.items()}
state_office_offices = {k: np.asarray(ix) for k, ix in off.groupby(["state", "office_n"]).groups.items()}
district_offices_national = {k: np.asarray(ix) for k, ix in off.groupby("district_n").groups.items()}
district_states = off.groupby("district_n")["state"].apply(lambda s: set(s.dropna())).to_dict()
state_districts = off.groupby("state")["district_n"].apply(lambda s: sorted(set(s.dropna()))).to_dict()
state_officenames = off.groupby("state")["office_n"].apply(lambda s: sorted(set(s.dropna()))).to_dict()
all_districts = sorted(set(off["district_n"].dropna()))

pin_ref = {int(r.pincode): (r.lat_office_median, r.lon_office_median, r.spread_p90_km)
           for r in pins.itertuples(index=False) if r.lat_office_median == r.lat_office_median}

geo_off = off[off.geo_ok]
geo_idx = geo_off.index.to_numpy()
tree = BallTree(np.radians(geo_off[["lat", "lon"]].to_numpy()), metric="haversine")
print(f"pincodes {len(pin_offices):,}; with a median point {len(pin_ref):,}; geocoded reference offices {len(geo_off):,}")

# COMMAND ----------

# MAGIC %md ## Facility inputs: state, point, shared points

# COMMAND ----------

FACILITY_STATUSES = ["clean", "repaired_head", "head_no_tail"]
fac = fac_all[fac_all.repair_status.isin(FACILITY_STATUSES + ["fragment_orphan"])].reset_index(drop=True)


def present(v):
    return v is not None and not (isinstance(v, float) and math.isnan(v)) and \
        str(v).strip().lower() not in ("", "null", "none", "nan", "na")


fac["state_stated"] = fac["address_stateOrRegion"].map(resolve_state)
fac["city_n"] = fac["address_city"].map(norm_place)
# state text that is not a state (often a city typed in the wrong box) becomes a second city candidate
fac["state_text_as_city"] = np.where(fac["state_stated"].isna(), fac["address_stateOrRegion"].map(norm_place), None)

lat = pd.to_numeric(fac["latitude"], errors="coerce")
lon = pd.to_numeric(fac["longitude"], errors="coerce")
in_bbox = lat.between(6.0, 37.6) & lon.between(68.0, 97.5)
zero = (lat.abs() < 1e-6) & (lon.abs() < 1e-6)
fac["point_status"] = np.select([lat.isna() | lon.isna() | zero, ~in_bbox], ["missing", "outside_india"], "ok")
fac["lat"], fac["lon"] = lat, lon

# L7: a point used by several *different* facilities (distinct cluster_id) is a shared/default point
is_fac = fac.repair_status.isin(FACILITY_STATUSES) & fac.point_status.eq("ok")
pt_key = fac.lat.round(SHARED_POINT_DECIMALS).astype(str) + "," + fac.lon.round(SHARED_POINT_DECIMALS).astype(str)
ident = fac.cluster_id.where(fac.cluster_id.notna() & fac.cluster_id.ne(""), "row:" + fac.fac_row_id.astype(str))
n_at_point = ident[is_fac].groupby(pt_key[is_fac]).nunique()
fac["point_n_facilities"] = pt_key.map(n_at_point).where(is_fac).astype("Int64")
fac["point_shared"] = fac.point_n_facilities.fillna(0).ge(SHARED_POINT_MIN_FACILITIES)
display(fac.groupby(["point_status", "point_shared"]).size().rename("facilities").reset_index())

# COMMAND ----------

# MAGIC %md ## City text → directory offices (source **T**), with the state inferred from the city (H6)
# MAGIC
# MAGIC Within the stated state, a city that fuzzy-matches a **district** name takes every office of the matched
# MAGIC district(s); only if no district matches are **office names** tried. With no resolvable state, the city
# MAGIC (or the state box read as a city) is matched against district names nationwide: if every matched district
# MAGIC lies in **one** state, that state is taken as `inferred_from_city`; otherwise T still uses the national
# MAGIC match, but the city/state check fails.

# COMMAND ----------


def fuzzy_candidates(q, choices):
    """All choices with similarity >= threshold (rapidfuzz prefilter, then the exact `similarity` rule)."""
    if not q or not choices:
        return []
    hits = set()
    for scorer in (fuzz.ratio, fuzz.token_set_ratio):
        for name, _, _ in process.extract(q, choices, scorer=scorer, score_cutoff=FUZZY_THRESHOLD * 100, limit=None):
            hits.add(name)
    return [h for h in hits if similarity(q, h) >= FUZZY_THRESHOLD]


city_cache = {}


def city_offices(state, city):
    key = (state, city)
    if key in city_cache:
        return city_cache[key]
    res = (np.array([], dtype=int), None, [])
    if city:
        if state:
            d = fuzzy_candidates(city, state_districts.get(state, []))
            if d:
                res = (np.unique(np.concatenate([state_district_offices[(state, x)] for x in d])), "district", d)
            else:
                o = fuzzy_candidates(city, state_officenames.get(state, []))
                if o:
                    res = (np.unique(np.concatenate([state_office_offices[(state, x)] for x in o])), "office", o)
        else:
            d = fuzzy_candidates(city, all_districts)
            if d:
                res = (np.unique(np.concatenate([district_offices_national[x] for x in d])), "district_national", d)
    city_cache[key] = res
    return res


def infer_state(city):
    """The single state whose districts the city matches nationally, else None."""
    d = fuzzy_candidates(city, all_districts) if city else []
    states = set().union(*(district_states.get(x, set()) for x in d)) if d else set()
    return next(iter(states)) if len(states) == 1 else None


T_off, T_kind, T_names, st_used, st_source, city_used = [], [], [], [], [], []
for st, c1, c2 in zip(fac.state_stated, fac.city_n, fac.state_text_as_city):
    if st:
        ix, kind, names = city_offices(st, c1)
        T_off.append(ix); T_kind.append(kind); T_names.append("|".join(names[:10]))
        st_used.append(st); st_source.append("stated"); city_used.append(c1)
        continue
    done = False
    for c in (c1, c2):  # no usable state: try the city, then the state box read as a city
        inf = infer_state(c)
        if inf:
            ix, kind, names = city_offices(inf, c)
            if kind == "district":
                T_off.append(ix); T_kind.append("district_inferred_state"); T_names.append("|".join(names[:10]))
                st_used.append(inf); st_source.append("inferred_from_city"); city_used.append(c)
                done = True
                break
    if done:
        continue
    ix, kind, names, cu = np.array([], dtype=int), None, [], c1
    for c, suffix in ((c1, ""), (c2, "_from_state_text")):
        ix, kind, names = city_offices(None, c)
        if kind:
            kind, cu = kind + suffix, c
            break
    T_off.append(ix); T_kind.append(kind); T_names.append("|".join(names[:10]))
    st_used.append(None); st_source.append(None); city_used.append(cu)
fac["state_resolved"] = st_used
fac["state_source"] = st_source
fac["city_used"] = city_used
fac["city_match_kind"] = T_kind
fac["city_matched_names"] = T_names
print(f"distinct (state, city) pairs matched: {len(city_cache):,}")
display(fac.groupby([fac.state_source.fillna("(none)"), fac.city_match_kind.fillna("(none)")]).size()
        .rename("facilities").reset_index())

# COMMAND ----------

# MAGIC %md ## Pincode used, with the neighbour fallback (H5)
# MAGIC
# MAGIC 1. the 6 digits of the zip field, if in the directory (`zip_field`);
# MAGIC 2. else the first directory pincode written in the address lines (`address_text`);
# MAGIC 3. else, when a **stated** state exists, the directory pincode with the **same first 5 digits** that has an
# MAGIC    office in that state, nearest by number (`neighbour`, weaker evidence: the pincode check scores partial).

# COMMAND ----------


def neighbour_pincode(p, state):
    if p is None or not state:
        return None
    cand = [q for q in pins_by_prefix5.get(p // 10, []) if q != p and state in pin_states.get(q, set())]
    return min(cand, key=lambda q: (abs(q - p), q)) if cand else None


# a plain list keeps None (Series.map would turn it into a float NaN, which `is not None` lets through)
pin_clean = [clean_pincode(v) for v in fac["address_zipOrPostcode"]]
pin_source, pin_final = [], []
for i, r in fac.iterrows():
    p = pin_clean[i]
    if p is not None and p in pin_offices:
        pin_final.append(p); pin_source.append("zip_field")
        continue
    alt = [q for q in pincodes_in_text(r["address_line1"], r["address_line2"], r["address_line3"],
                                       r["address_zipOrPostcode"]) if q in pin_offices]
    if alt:
        pin_final.append(alt[0]); pin_source.append("address_text")
        continue
    nb = neighbour_pincode(p, r.state_stated)
    if nb is not None:
        pin_final.append(nb); pin_source.append("neighbour")
    else:
        pin_final.append(None)
        pin_source.append("not_in_directory" if (p is not None or present(r["address_zipOrPostcode"])) else "missing")
fac["pincode_written"] = pd.Series([int(p) if p is not None else None for p in pin_clean], dtype="object")
fac["pincode_used"] = pd.Series(pin_final, dtype="object")  # object dtype keeps None (not NaN)
fac["pincode_source"] = pin_source
display(fac.groupby(["pincode_source"]).size().rename("facilities").reset_index())

# COMMAND ----------

# MAGIC %md ## Pincode offices (source **P**) and nearby geocoded offices (source **G**)
# MAGIC
# MAGIC A shared/default point (L7) gives no G source: it says nothing about where this facility is.

# COMMAND ----------

EMPTY = np.array([], dtype=int)


def has_pin(p):
    return p is not None and p == p


P_off = [pin_offices.get(int(p), EMPTY) if has_pin(p) else EMPTY for p in fac.pincode_used]

G_off = [EMPTY] * len(fac)
use_g = (fac.point_status.eq("ok") & ~fac.point_shared).to_numpy()
if use_g.any():
    q = np.radians(fac.loc[use_g, ["lat", "lon"]].to_numpy())
    hits = tree.query_radius(q, r=G_SEARCH_KM / EARTH_R_KM)
    for i, h in zip(np.flatnonzero(use_g), hits):
        G_off[i] = geo_idx[h]

# COMMAND ----------

# MAGIC %md ## Checks

# COMMAND ----------

def pairs(ix, a, b):
    if len(ix) == 0:
        return set()
    return {(x, y) for x, y in zip(A[a][ix], A[b][ix]) if x is not None and y is not None and x == x and y == y}


def agree_with_t(P, T, G):
    """L2: pass only if the city-text source T shares a pair with P or G. Returns (passed, agreed_by, why)."""
    if not T:
        return False, None, "city_text_not_placed"
    by = [k for k, s in (("P", P), ("G", G)) if s and (s & T)]
    if by:
        return True, "=".join(by + ["T"]), None
    if not P and not G:
        return False, None, "no_second_source"
    return False, None, "sources_disagree_with_city_text"


def city_ref(T):
    """Median point and p90 spread of the geocoded city-matched offices (fallback reference)."""
    t = T[A_GEO_OK[T]] if len(T) else T
    if len(t) == 0:
        return None
    mlat, mlon = float(np.median(A_LAT[t])), float(np.median(A_LON[t]))
    return mlat, mlon, float(np.quantile(haversine_km(mlat, mlon, A_LAT[t], A_LON[t]), 0.9))


res = defaultdict(list)
for i, r in fac.iterrows():
    P, T, G = P_off[i], T_off[i], G_off[i]
    stated, city = r.state_stated, r.city_used
    weak_pin = r.pincode_source == "neighbour"

    # pincode (compared with the *stated* state; with none, with the city text)
    if not has_pin(r.pincode_used):
        cp, why = "fail", f"pincode_{r.pincode_source}"
    elif stated:
        ok = stated in vals(P, "state")
        cp, why = ("partial" if weak_pin else "pass", "pincode_neighbour_used" if weak_pin else None) if ok \
            else ("fail", "pincode_state_differs_from_stated_state")
    else:
        names = vals(P, "district_n") | vals(P, "office_n")
        ok = bool(city) and any(fuzzy_match(city, n) for n in names)
        cp, why = ("pass", None) if ok else \
            ("fail", "pincode_no_state_and_no_city" if not city else "pincode_no_state_city_not_in_pincode")
    res["chk_pincode"].append(cp); res["why_pincode"].append(why)

    # city / state
    if r.state_source == "inferred_from_city":
        cc, why = "partial", "state_inferred_from_city"
    elif not stated:
        cc, why = "fail", "state_missing_or_unresolved"
    elif not r.city_n:
        cc, why = "fail", "city_missing"
    elif T_kind[i] in ("district", "office"):
        cc, why = "pass", None
    else:
        cc, why = "fail", "city_not_found_in_stated_state"
    res["chk_city_state"].append(cc); res["why_city_state"].append(why)

    # district + region, circle + division (L2: T must be one of the agreeing sources)
    for chk, a, b in (("district_region", "district_n", "region_n"), ("circle_division", "circle_n", "division_n")):
        passed, by, why = agree_with_t(pairs(P, a, b), pairs(T, a, b), pairs(G, a, b))
        res[f"chk_{chk}"].append("pass" if passed else "fail")
        res[f"{chk}_agreed_by"].append(by)
        res[f"why_{chk}"].append(why)

    # coordinates (secondary): pincode median point, radius scaled by the pincode's spread (H4, L4, L7)
    d = rad = np.nan
    ref_src = None
    if r.point_status == "missing":
        cs, why = "missing", None
    elif r.point_status == "outside_india":
        cs, why = "fail", "point_outside_india"
    elif r.point_shared:
        cs, why = "fail", f"shared_point_{int(r.point_n_facilities)}_facilities"
    else:
        ref = pin_ref.get(int(r.pincode_used)) if has_pin(r.pincode_used) else None
        ref_src = "pincode" if ref else None
        if ref is None:
            ref = city_ref(T)
            ref_src = "city_text" if ref else None
        if ref is None:
            cs, why = "fail", "no_geocoded_reference_office"
        else:
            mlat, mlon, spread = ref
            rad = float(np.clip(spread if spread == spread else 0.0, COORD_RADIUS_MIN_KM, COORD_RADIUS_MAX_KM))
            d = float(haversine_km(r.lat, r.lon, mlat, mlon))
            cs = "pass" if d <= rad else "fail"
            why = None if cs == "pass" else f"median_point_{d:.0f}_km_radius_{rad:.0f}_km"
    res["chk_coordinates"].append(cs); res["why_coordinates"].append(why)
    res["coord_ref_source"].append(ref_src); res["coord_median_km"].append(d); res["coord_radius_km"].append(rad)

for k, v in res.items():
    fac[k] = v

# COMMAND ----------

# MAGIC %md ## Score: MCDM weighted sum (swing weights) + two-main-check gate

# COMMAND ----------

CHECK_COLS = {k: f"chk_{k}" for k in MAIN_CHECKS + SECONDARY_CHECKS}
for k, c in CHECK_COLS.items():
    fac[f"val_{k}"] = fac[c].map(CHECK_VALUE)  # missing coordinates -> NaN (left out of S)

num = sum(MCDM_WEIGHTS[k] * fac[f"val_{k}"].fillna(0) for k in CHECK_COLS)
den = sum(MCDM_WEIGHTS[k] * fac[f"val_{k}"].notna() for k in CHECK_COLS)
fac["location_validation_s"] = (num / den).round(4)
fac["main_value"] = sum(fac[f"val_{k}"] for k in MAIN_CHECKS)
fac["n_main_pass"] = sum(fac[f"val_{k}"].eq(1.0).astype(int) for k in MAIN_CHECKS)
fac["gate_passed"] = fac.main_value >= MIN_MAIN_VALUE

no_data = ~(fac.address_city.map(present) | fac.address_stateOrRegion.map(present)
            | fac.address_zipOrPostcode.map(present) | fac.point_status.ne("missing"))
S, gate = fac.location_validation_s, fac.gate_passed
fac["location_validation_score"] = np.select(
    [fac.repair_status.eq("fragment_orphan"), no_data, ~gate]
    + [S >= t for _, t in SCORE_BANDS],
    [0, 1, 2] + [s for s, _ in SCORE_BANDS], default=2).astype(int)
fac["location_validation_passed"] = fac.location_validation_score >= PASS_SCORE
fac["location_validation_fail_reason"] = np.select(
    [fac.location_validation_score.eq(0), fac.location_validation_score.eq(1), ~gate,
     fac.location_validation_score.eq(2)],
    ["not_a_facility_record", "no_location_data", "fewer_than_two_main_checks",
     f"weighted_score_below_{SCORE_BANDS[-1][1]:.2f}"], default=None)
fac.loc[fac.location_validation_passed, "location_validation_fail_reason"] = None
LABELS = {5: "verified_all", 4: "verified_strong", 3: "verified_partial", 2: "unverified",
          1: "no_location_data", 0: "not_a_facility_record"}
fac["location_validation_label"] = fac.location_validation_score.map(LABELS)
fac["failed_checks"] = fac.apply(
    lambda r: "|".join(k for k, c in CHECK_COLS.items() if r[c] == "fail") or None, axis=1)
fac["partial_checks"] = fac.apply(
    lambda r: "|".join(k for k, c in CHECK_COLS.items() if r[c] == "partial") or None, axis=1)
fac["scoring_version"] = SCORING_VERSION
fac["scored_at"] = now_utc()

display(fac.groupby(["location_validation_score", "location_validation_label", "location_validation_passed"])
        .size().rename("facilities").reset_index())
display(fac.groupby(["location_validation_fail_reason"]).size().rename("facilities").reset_index())
display(pd.DataFrame([{"check": k, "weight": round(MCDM_WEIGHTS[k], 4),
                       **{s: round(100 * fac[c].eq(s).mean(), 1) for s in ("pass", "partial", "fail", "missing")}}
                      for k, c in CHECK_COLS.items()]))

# COMMAND ----------

# MAGIC %md ## Compare with the previous scoring version
# MAGIC
# MAGIC Before overwriting, the previous `bronze_locval_scores` is kept as `bronze_locval_scores_v<old version>`
# MAGIC (once per version), and the old → new score transition is shown. The comparison is for reporting only:
# MAGIC weights and bands are fixed in `_scoring_common` and are not tuned on it.

# COMMAND ----------

prev = None
if spark.catalog.tableExists(vtbl("scores")):
    old_ver = spark.table(vtbl("scores")).selectExpr("max(scoring_version) AS v").first().v
    if old_ver and old_ver != SCORING_VERSION:
        snap = vtbl(f"scores_v{old_ver.replace('.', '_')}")
        if not spark.catalog.tableExists(snap):
            spark.sql(f"CREATE TABLE {snap} AS SELECT * FROM {vtbl('scores')}")
            print(f"kept previous scores as {snap}")
        prev = spark.table(snap).select("fac_row_id", "location_validation_score").toPandas()
if prev is not None:
    cmp = fac[["fac_row_id", "location_validation_score"]].merge(prev, on="fac_row_id", suffixes=("_new", "_old"))
    xt = pd.crosstab(cmp.location_validation_score_old.astype(str), cmp.location_validation_score_new.astype(str),
                     margins=True, margins_name="total")
    xt.columns = [f"v{SCORING_VERSION} = {c}" for c in xt.columns]
    display(xt.rename_axis(f"v{old_ver} score").reset_index())

# COMMAND ----------

KEEP = ["unique_id", "cluster_id", "fac_row_id", "repair_status", "name", "address_city", "address_stateOrRegion",
        "address_zipOrPostcode", "latitude", "longitude",
        "state_resolved", "state_source", "city_match_kind", "city_matched_names",
        "pincode_written", "pincode_used", "pincode_source", "point_status", "point_n_facilities", "point_shared",
        "chk_pincode", "why_pincode", "chk_city_state", "why_city_state",
        "chk_district_region", "district_region_agreed_by", "why_district_region",
        "chk_circle_division", "circle_division_agreed_by", "why_circle_division",
        "chk_coordinates", "why_coordinates", "coord_ref_source", "coord_median_km", "coord_radius_km",
        "val_pincode", "val_city_state", "val_district_region", "val_circle_division", "val_coordinates",
        "main_value", "n_main_pass", "gate_passed", "location_validation_s",
        "location_validation_score", "location_validation_label", "location_validation_passed",
        "location_validation_fail_reason", "failed_checks", "partial_checks", "scoring_version", "scored_at"]
scores = fac[KEEP].copy()
for c in ("pincode_written", "pincode_used"):
    scores[c] = scores[c].astype("Int64")
write_vtable(scores, "scores",
             f"Location validation score per facility (v{SCORING_VERSION}; 0-5, pass >= {PASS_SCORE}). One row per "
             "facility of bronze_locval_facilities_repaired (merged CSV fragments excluded). chk_* = each check "
             "(pass/partial/fail/missing), val_* = its MCDM value, why_* = reason, location_validation_s = weighted "
             "sum. Rules: notebooks/location_validation_scoring/SCORING_CRITERIA.md")

summary = (fac.groupby(["location_validation_score", "location_validation_label", "location_validation_passed"])
           .size().rename("facilities").reset_index())
summary["pct"] = (100 * summary.facilities / summary.facilities.sum()).round(2)
summary["scoring_version"] = SCORING_VERSION
write_vtable(summary, "score_summary", "Facility count per location_validation_score for the latest scoring run.")
