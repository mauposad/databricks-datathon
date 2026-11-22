# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Location validation score
# MAGIC
# MAGIC Gives every facility a `location_validation_score` (0–5) and pass/fail flag, written to
# MAGIC `bronze_locval_scores`. The rules are in `SCORING_CRITERIA.md` and summarised here:
# MAGIC
# MAGIC **Main checks** (each pass/fail; a missing input fails):
# MAGIC
# MAGIC | check | passes when |
# MAGIC |---|---|
# MAGIC | `pincode` | pincode is in the India Post directory **and** one of its offices is in the stated state (no stated state: an office or district of the pincode fuzzy-matches the city) |
# MAGIC | `city_state` | stated state resolves **and** the city fuzzy-matches (≥ 0.85) a directory district (or, failing that, office) in that state |
# MAGIC | `district_region` | two independent sources share the same **district and India Post region** |
# MAGIC | `circle_division` | two independent sources share the same **India Post circle and division** |
# MAGIC
# MAGIC The independent sources for the two pair checks are offices of the pincode (**P**), offices matched by the
# MAGIC city text (**T**) and geocoded offices within 10 km of the facility point (**G**). Any two agreeing is
# MAGIC enough, so a bad pincode does not sink these checks.
# MAGIC
# MAGIC **Secondary checks**: `coordinates` (within 10 km of a geocoded office of the pincode, or of the city
# MAGIC match when the pincode is unusable; *missing coordinates are neutral*) and `phone` (telecom circle / STD
# MAGIC area state agrees with the stated or pincode state; one number → it must match, several → at least two
# MAGIC must match; *no locatable phone fails*).
# MAGIC
# MAGIC | score | rule | passes |
# MAGIC |---|---|---|
# MAGIC | 5 | 4 main + phone + coordinates (or coordinates missing) | yes |
# MAGIC | 4 | 4 main, secondaries not both satisfied; or 2–3 main + phone + coordinates (or missing) | yes |
# MAGIC | 3 | 2–3 main otherwise; or exactly 1 main | yes |
# MAGIC | 2 | 0 main (whatever the secondaries) | no |
# MAGIC | 1 | no location data at all (no city, state, pincode, coordinates or phone) | no |
# MAGIC | 0 | not a facility record (orphan CSV fragment) | no |
# MAGIC
# MAGIC Inputs: `bronze_locval_facilities_repaired` (notebook 01), `bronze_locval_mobile_prefix` (notebook 00),
# MAGIC `bronze_loclink_offices` (`../location_linkage/00_build_location_pairs`).

# COMMAND ----------

# MAGIC %pip install geopandas==1.0.1 plotly==5.24.1 phonenumbers==9.0.44 rapidfuzz==3.13.0 --quiet

# COMMAND ----------

# MAGIC %run ./_scoring_common

# COMMAND ----------

from collections import defaultdict

from rapidfuzz import process
from sklearn.neighbors import BallTree

for t in (vtbl("facilities_repaired"), vtbl("mobile_prefix"), tbl("offices")):
    assert spark.catalog.tableExists(t), (
        f"{t} is missing: run 00_ingest_phone_reference, 01_repair_facility_rows and "
        f"../location_linkage/00_build_location_pairs first (or the location_validation_scoring job)")

fac_all = spark.table(vtbl("facilities_repaired")).toPandas()
mob = spark.table(vtbl("mobile_prefix")).toPandas()
off = spark.table(tbl("offices")).toPandas()
print(f"facility rows {len(fac_all):,}; offices {len(off):,}; mobile series {len(mob):,}")

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
state_district_offices = {k: np.asarray(ix) for k, ix in off.groupby(["state", "district_n"]).groups.items()}
state_office_offices = {k: np.asarray(ix) for k, ix in off.groupby(["state", "office_n"]).groups.items()}
district_offices_national = {k: np.asarray(ix) for k, ix in off.groupby("district_n").groups.items()}
state_districts = off.groupby("state")["district_n"].apply(lambda s: sorted(set(s.dropna()))).to_dict()
state_officenames = off.groupby("state")["office_n"].apply(lambda s: sorted(set(s.dropna()))).to_dict()
all_districts = sorted(set(off["district_n"].dropna()))

geo_off = off[off.geo_ok]
geo_idx = geo_off.index.to_numpy()
tree = BallTree(np.radians(geo_off[["lat", "lon"]].to_numpy()), metric="haversine")
print(f"pincodes {len(pin_offices):,}; geocoded reference offices {len(geo_off):,}")

# COMMAND ----------

# MAGIC %md ## Facility inputs: state, city, pincode, point

# COMMAND ----------

FACILITY_STATUSES = ["clean", "repaired_head", "head_no_tail"]
fac = fac_all[fac_all.repair_status.isin(FACILITY_STATUSES + ["fragment_orphan"])].reset_index(drop=True)


def present(v):
    return v is not None and not (isinstance(v, float) and math.isnan(v)) and \
        str(v).strip().lower() not in ("", "null", "none", "nan", "na")


fac["state_resolved"] = fac["address_stateOrRegion"].map(resolve_state)
fac["city_n"] = fac["address_city"].map(norm_place)
# state text that is not a state (often a city typed in the wrong box) becomes a second city candidate
fac["state_text_as_city"] = np.where(fac["state_resolved"].isna(), fac["address_stateOrRegion"].map(norm_place), None)

pin_clean = fac["address_zipOrPostcode"].map(clean_pincode)
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
    else:
        pin_final.append(None)
        pin_source.append("not_in_directory" if (p is not None or present(r["address_zipOrPostcode"])) else "missing")
fac["pincode_used"] = pd.Series(pin_final, dtype="object")  # object dtype keeps None (not NaN)
fac["pincode_source"] = pin_source

lat = pd.to_numeric(fac["latitude"], errors="coerce")
lon = pd.to_numeric(fac["longitude"], errors="coerce")
in_bbox = lat.between(6.0, 37.6) & lon.between(68.0, 97.5)
zero = (lat.abs() < 1e-6) & (lon.abs() < 1e-6)
fac["point_status"] = np.select([lat.isna() | lon.isna() | zero, ~in_bbox], ["missing", "outside_india"], "ok")
fac["lat"], fac["lon"] = lat, lon
display(fac.groupby(["pincode_source"]).size().rename("facilities").reset_index())
display(fac.groupby(["point_status"]).size().rename("facilities").reset_index())

# COMMAND ----------

# MAGIC %md ## City text → directory offices (source **T**)
# MAGIC
# MAGIC Within the stated state, a city that fuzzy-matches a **district** name takes every office of the matched
# MAGIC district(s); only if no district matches are **office names** tried. With no resolvable state the city is
# MAGIC matched against district names nationwide (that still feeds T, but `city_state` fails).

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


T_off, T_kind, T_names = [], [], []
for st, c1, c2 in zip(fac.state_resolved, fac.city_n, fac.state_text_as_city):
    ix, kind, names = city_offices(st, c1)
    if kind is None and c2:  # fall back to the state box read as a city
        ix, kind, names = city_offices(None, c2)
        kind = f"{kind}_from_state_text" if kind else None
    T_off.append(ix); T_kind.append(kind); T_names.append("|".join(names[:10]))
fac["city_match_kind"] = T_kind
fac["city_matched_names"] = T_names
print(f"distinct (state, city) pairs matched: {len(city_cache):,}")
display(fac.city_match_kind.fillna("(none)").value_counts().rename_axis("city_match_kind").reset_index(name="n"))

# COMMAND ----------

# MAGIC %md ## Pincode offices (source **P**) and nearby geocoded offices (source **G**)

# COMMAND ----------

EMPTY = np.array([], dtype=int)


def has_pin(p):
    return p is not None and p == p


P_off = [pin_offices.get(int(p), EMPTY) if has_pin(p) else EMPTY for p in fac.pincode_used]

G_off = [EMPTY] * len(fac)
ok = fac.point_status.eq("ok").to_numpy()
if ok.any():
    q = np.radians(fac.loc[ok, ["lat", "lon"]].to_numpy())
    hits = tree.query_radius(q, r=COORD_MATCH_KM / EARTH_R_KM)
    for i, h in zip(np.flatnonzero(ok), hits):
        G_off[i] = geo_idx[h]

# COMMAND ----------

# MAGIC %md ## Main checks

# COMMAND ----------

def pairs(ix, a, b):
    if len(ix) == 0:
        return set()
    return {(x, y) for x, y in zip(A[a][ix], A[b][ix]) if x is not None and y is not None and x == x and y == y}


def agree(sources):
    """Pass if any two available sources share a pair. Returns (passed, which sources agreed, n sources)."""
    avail = {k: v for k, v in sources.items() if v}
    keys = sorted(avail)
    for x in range(len(keys)):
        for y in range(x + 1, len(keys)):
            if avail[keys[x]] & avail[keys[y]]:
                return True, f"{keys[x]}={keys[y]}", len(avail)
    return False, None, len(avail)


res = defaultdict(list)
for i, r in fac.iterrows():
    P, T, G = P_off[i], T_off[i], G_off[i]
    st, city = r.state_resolved, r.city_n

    # pincode
    if not has_pin(r.pincode_used):
        ok_p, why = False, f"pincode_{r.pincode_source}"
    elif st:
        ok_p = st in vals(P, "state")
        why = None if ok_p else "pincode_state_differs_from_stated_state"
    else:
        names = vals(P, "district_n") | vals(P, "office_n")
        ok_p = bool(city) and any(fuzzy_match(city, n) for n in names)
        why = None if ok_p else ("pincode_no_state_and_no_city" if not city else "pincode_no_state_city_not_in_pincode")
    res["chk_pincode"].append(ok_p); res["why_pincode"].append(why)

    # city / state
    if not st:
        ok_c, why = False, "state_missing_or_unresolved"
    elif not city:
        ok_c, why = False, "city_missing"
    else:
        ok_c = T_kind[i] in ("district", "office")
        why = None if ok_c else "city_not_found_in_stated_state"
    res["chk_city_state"].append(ok_c); res["why_city_state"].append(why)

    # district + region, circle + division
    for chk, a, b in (("district_region", "district_n", "region_n"), ("circle_division", "circle_n", "division_n")):
        passed, by, n_src = agree({"P": pairs(P, a, b), "T": pairs(T, a, b), "G": pairs(G, a, b)})
        res[f"chk_{chk}"].append(passed)
        res[f"{chk}_agreed_by"].append(by)
        res[f"why_{chk}"].append(None if passed else ("fewer_than_two_sources" if n_src < 2 else "sources_disagree"))

    # coordinates (secondary)
    if r.point_status == "missing":
        cs, why, dmin = "missing", None, np.nan
    elif r.point_status == "outside_india":
        cs, why, dmin = "fail", "point_outside_india", np.nan
    else:
        ref = P if has_pin(r.pincode_used) else T
        ref = ref[A_GEO_OK[ref]] if len(ref) else ref
        if len(ref) == 0:
            cs, why, dmin = "fail", "no_geocoded_reference_office", np.nan
        else:
            dmin = float(np.min(haversine_km(r.lat, r.lon, A_LAT[ref], A_LON[ref])))
            cs = "pass" if dmin <= COORD_MATCH_KM else "fail"
            why = None if cs == "pass" else f"nearest_reference_office_{dmin:.0f}_km"
    res["chk_coordinates"].append(cs); res["why_coordinates"].append(why); res["coord_nearest_ref_km"].append(dmin)

    res["reference_states"].append(sorted(({st} if st else set()) | vals(P, "state")))

for k, v in res.items():
    fac[k] = v

# COMMAND ----------

# MAGIC %md ## Phone check

# COMMAND ----------

mob_lookup = {int(s): (c, src_, float(p) if p == p else None, set(cs.split("|")) if cs else set())
              for s, c, src_, p, cs in mob[["series", "circle", "circle_source", "circle_probability", "circle_states"]]
              .itertuples(index=False)}

phone_cache = {}


def locate_phone(raw_num):
    if raw_num in phone_cache:
        return phone_cache[raw_num]
    c = classify_phone(raw_num)
    c.update(kind=None, mobile_series=None, mobile_circle=None, circle_source=None, circle_probability=None, states=set())
    if c["phone_type"] == "FIXED_LINE":
        c["kind"] = "landline"
        if c["area_state"]:
            c["states"] = {c["area_state"]}
    elif c["phone_type"] in ("MOBILE", "FIXED_LINE_OR_MOBILE") and c["nsn"] and len(c["nsn"]) == 10 and c["nsn"][0] in "6789":
        c["kind"] = "mobile"
        s = int(c["nsn"][:4])
        if s in mob_lookup:
            circ, srcc, prob, states = mob_lookup[s]
            c.update(mobile_series=s, mobile_circle=circ, circle_source=srcc, circle_probability=prob, states=states)
    phone_cache[raw_num] = c
    return c


phone_rows, ph = [], defaultdict(list)
for i, r in fac.iterrows():
    refs = set(r.reference_states)
    nums = parse_phone_list(r["officialPhone"], r["phone_numbers"])
    n_loc = n_match = n_land = n_mob = n_model = n_area = 0
    for n in nums:
        c = locate_phone(n)
        located = bool(c["states"])
        match = located and bool(c["states"] & refs)
        area_match = None
        if c["kind"] == "landline" and c["area_desc"]:
            area = norm_place(c["area_desc"].split(",")[0])
            cmp = {r.city_n} | vals(P_off[i], "district_n")
            area_match = any(fuzzy_match(area, x) for x in cmp if x)
            n_area += int(area_match)
        n_loc += located; n_match += match
        n_land += c["kind"] == "landline"; n_mob += c["kind"] == "mobile"
        n_model += c["circle_source"] == "model"
        phone_rows.append(dict(unique_id=r.unique_id, fac_row_id=r.fac_row_id, phone_raw=n, e164=c["e164"],
                               phone_type=c["phone_type"], phone_kind=c["kind"], landline_area=c["area_desc"],
                               mobile_series=c["mobile_series"], mobile_circle=c["mobile_circle"],
                               circle_source=c["circle_source"], circle_probability=c["circle_probability"],
                               phone_states="|".join(sorted(c["states"])) or None, located=located,
                               matches_reference_state=match, landline_area_matches_city=area_match))
    if not nums:
        ok_ph, why = False, "phone_missing"
    elif n_loc == 0:
        ok_ph, why = False, "phone_not_locatable"
    elif not refs:
        ok_ph, why = False, "no_reference_state"
    elif n_loc == 1:
        ok_ph, why = n_match == 1, (None if n_match == 1 else "single_phone_state_differs")
    else:
        ok_ph, why = n_match >= 2, (None if n_match >= 2 else "fewer_than_two_phones_match")
    for k, v in dict(chk_phone="pass" if ok_ph else "fail", why_phone=why, phone_n_numbers=len(nums),
                     phone_n_locatable=n_loc, phone_n_matching=n_match, phone_n_landline=n_land, phone_n_mobile=n_mob,
                     phone_n_model_circle=n_model, phone_n_landline_area_match=n_area).items():
        ph[k].append(v)
for k, v in ph.items():
    fac[k] = v
print(f"distinct phone numbers resolved: {len(phone_cache):,}")

# COMMAND ----------

# MAGIC %md ## Score

# COMMAND ----------

MAIN = ["chk_pincode", "chk_city_state", "chk_district_region", "chk_circle_division"]
fac["n_main_pass"] = fac[MAIN].astype(int).sum(axis=1)
coord_ok = fac.chk_coordinates.isin(["pass", "missing"])  # missing coordinates are neutral
phone_ok = fac.chk_phone.eq("pass")
both_secondary = coord_ok & phone_ok
no_data = ~(fac.address_city.map(present) | fac.address_stateOrRegion.map(present)
            | fac.address_zipOrPostcode.map(present) | fac.point_status.ne("missing") | fac.phone_n_numbers.gt(0))
m = fac.n_main_pass
fac["location_validation_score"] = np.select(
    [fac.repair_status.eq("fragment_orphan"), no_data,
     (m == 4) & both_secondary, m == 4,
     m.between(2, 3) & both_secondary, m.between(1, 3),
     m == 0],
    [0, 1, 5, 4, 4, 3, 2]).astype(int)
fac["location_validation_passed"] = fac.location_validation_score >= PASS_SCORE
LABELS = {5: "verified_all", 4: "verified_strong", 3: "verified_partial", 2: "unverified",
          1: "no_location_data", 0: "not_a_facility_record"}
fac["location_validation_label"] = fac.location_validation_score.map(LABELS)
fac["failed_checks"] = fac.apply(
    lambda r: "|".join([c.replace("chk_", "") for c in MAIN if not r[c]]
                       + (["coordinates"] if r.chk_coordinates == "fail" else [])
                       + (["phone"] if r.chk_phone == "fail" else [])) or None, axis=1)
fac["scoring_version"] = SCORING_VERSION
fac["scored_at"] = now_utc()

display(fac.groupby(["location_validation_score", "location_validation_label", "location_validation_passed"])
        .size().rename("facilities").reset_index())
rates = pd.DataFrame({
    "check": MAIN + ["chk_coordinates", "chk_phone"],
    "pass_pct": [100 * fac[c].mean() for c in MAIN] + [100 * fac.chk_coordinates.eq("pass").mean(),
                                                       100 * phone_ok.mean()],
    "missing_pct": [np.nan] * 4 + [100 * fac.chk_coordinates.eq("missing").mean(),
                                   100 * fac.why_phone.eq("phone_missing").mean()],
}).round(1)
display(rates)

# COMMAND ----------

KEEP = ["unique_id", "fac_row_id", "repair_status", "name", "address_city", "address_stateOrRegion",
        "address_zipOrPostcode", "latitude", "longitude",
        "state_resolved", "city_match_kind", "city_matched_names", "pincode_used", "pincode_source", "point_status",
        "chk_pincode", "why_pincode", "chk_city_state", "why_city_state",
        "chk_district_region", "district_region_agreed_by", "why_district_region",
        "chk_circle_division", "circle_division_agreed_by", "why_circle_division",
        "chk_coordinates", "why_coordinates", "coord_nearest_ref_km",
        "chk_phone", "why_phone", "phone_n_numbers", "phone_n_locatable", "phone_n_matching", "phone_n_landline",
        "phone_n_mobile", "phone_n_model_circle", "phone_n_landline_area_match",
        "n_main_pass", "location_validation_score", "location_validation_label", "location_validation_passed",
        "failed_checks", "scoring_version", "scored_at"]
scores = fac[KEEP].copy()
scores["reference_states"] = fac.reference_states.map(lambda s: "|".join(s) or None)
scores["pincode_used"] = scores.pincode_used.astype("Int64")
write_vtable(scores, "scores",
             f"Location validation score per facility (v{SCORING_VERSION}; 0-5, pass >= {PASS_SCORE}). One row per "
             "facility of bronze_locval_facilities_repaired (merged CSV fragments excluded). chk_* = each check, why_* "
             "= reason it failed. Rules: notebooks/location_validation_scoring/SCORING_CRITERIA.md")

phones = pd.DataFrame(phone_rows)
phones["mobile_series"] = phones.mobile_series.astype("Int64")
write_vtable(phones, "phone_numbers",
             "One row per facility x distinct phone number: libphonenumber type, landline STD area, mobile series -> "
             "telecom circle (csv or model), the states it implies and whether it matches the facility's stated/pincode state.")

summary = (fac.groupby(["location_validation_score", "location_validation_label", "location_validation_passed"])
           .size().rename("facilities").reset_index())
summary["pct"] = (100 * summary.facilities / summary.facilities.sum()).round(2)
summary["scoring_version"] = SCORING_VERSION
write_vtable(summary, "score_summary", "Facility count per location_validation_score for the latest scoring run.")
