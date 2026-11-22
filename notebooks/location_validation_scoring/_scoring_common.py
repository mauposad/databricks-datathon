# Databricks notebook source
# MAGIC %md
# MAGIC # `_scoring_common`: shared config and helpers for the location-validation scoring pipeline
# MAGIC
# MAGIC Loaded by every notebook in this folder with `%run ./_scoring_common`. The calling notebook must first
# MAGIC `%pip install geopandas==1.0.1 plotly==5.24.1 rapidfuzz==3.13.0` (the serverless job environment, Python 3.12 + numpy 2, has no plotly, which `location_linkage/_common` imports; 5.24.1 works with numpy 2).
# MAGIC
# MAGIC It reuses `../location_linkage/_common` (state canonicalisation, `norm_text`, haversine, output widgets),
# MAGIC so both pipelines spell states and normalise text the same way. Scoring rules live in
# MAGIC `SCORING_CRITERIA.md`; every decision behind them is in `DECISIONS.md`.

# COMMAND ----------

# MAGIC %run ../location_linkage/_common

# COMMAND ----------

import datetime as _dt
import functools

from rapidfuzz import fuzz

SCORING_VERSION = "1.1.0"

FUZZY_THRESHOLD = 0.85  # similarity (0-1) for any text-vs-text comparison
G_SEARCH_KM = 10.0      # source G: geocoded post offices within this distance of the facility point
# coordinate check (v1.1, H4/L4): distance to the pincode's median office point must be within
# clamp(spread_p90_km, COORD_RADIUS_MIN_KM, COORD_RADIUS_MAX_KM)
COORD_RADIUS_MIN_KM = 10.0  # team decision T6
COORD_RADIUS_MAX_KM = 25.0  # silver's "agree" band
SHARED_POINT_MIN_FACILITIES = 3  # a point used by >= this many distinct clusters is shared/default (L7)
SHARED_POINT_DECIMALS = 5        # points are compared after rounding to this many decimals (~1 m)

# MCDM (v1.1, L1): swing-weighting ratings. The check whose swing from fail to pass matters most is rated 100,
# the others relative to it; weights = rating / sum. Set from the v1.0 evidence, not tuned on v1.1 results.
SWING_RATINGS = {
    "pincode": 100,          # validated against the official directory; the most specific written claim
    "city_state": 90,        # written text; the only check that never depends on the pincode or the point
    "coordinates": 80,       # independent physical evidence, but scraped points are often geocoder guesses
    "district_region": 70,   # pair check; partly derived from the same pincode / city text (L2)
    "circle_division": 60,   # coarsest postal unit, so the weakest discriminator
}
MCDM_WEIGHTS = {k: v / sum(SWING_RATINGS.values()) for k, v in SWING_RATINGS.items()}
MAIN_CHECKS = ["pincode", "city_state", "district_region", "circle_division"]
SECONDARY_CHECKS = ["coordinates"]
CHECK_VALUE = {"pass": 1.0, "partial": 0.5, "fail": 0.0}  # partial = weaker evidence (H5 neighbour pincode, H6 inferred state)
MIN_MAIN_VALUE = 2.0  # gate (L3): main-check values must add up to >= 2 (a partial counts 0.5)
SCORE_BANDS = [(5, 0.85), (4, 0.70), (3, 0.60)]  # weighted sum S -> score; S < 0.60 fails (2)
PASS_SCORE = 3        # scores 0, 1, 2 fail

def vtbl(name):
    """Tables of this pipeline: bronze_locval_<name>."""
    return f"{OUT_CATALOG}.{OUT_SCHEMA}.bronze_locval_{name}"


def write_vtable(pdf, name, comment):
    sdf = spark.createDataFrame(pdf)
    full = vtbl(name)
    sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(full)
    spark.sql(f"COMMENT ON TABLE {full} IS {json.dumps(comment)}")
    print(f"wrote {full}: {len(pdf):,} rows")


def now_utc():
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)

# COMMAND ----------

# MAGIC %md ## Fuzzy text matching
# MAGIC
# MAGIC `similarity(a, b)` is the larger of
# MAGIC * `fuzz.ratio`: whole-string edit similarity ("GURGAON" vs "GURGAON CITY" fails, "VISHAKAPATNAM" vs
# MAGIC   "VISAKHAPATNAM" passes), and
# MAGIC * `fuzz.token_set_ratio` after dropping generic place words, only when the shorter side keeps at least
# MAGIC   one token of 4+ characters ("BENGALURU" vs "BENGALURU URBAN" passes; "NAGAR" alone never matches
# MAGIC   "AHMED NAGAR").
# MAGIC
# MAGIC Renamed cities are mapped to one spelling first (`CITY_ALIASES`), because edit distance cannot link
# MAGIC Bombay and Mumbai.

# COMMAND ----------

CITY_ALIASES = {
    "BOMBAY": "MUMBAI", "MADRAS": "CHENNAI", "CALCUTTA": "KOLKATA", "BANGALORE": "BENGALURU",
    "BANGLORE": "BENGALURU", "GURGAON": "GURUGRAM", "TRIVANDRUM": "THIRUVANANTHAPURAM",
    "POONA": "PUNE", "MYSORE": "MYSURU", "ALLAHABAD": "PRAYAGRAJ", "BARODA": "VADODARA",
    "BENARES": "VARANASI", "BANARAS": "VARANASI", "COCHIN": "KOCHI", "ERNAKULAM": "KOCHI",
    "CALICUT": "KOZHIKODE", "TRICHUR": "THRISSUR", "PONDICHERRY": "PUDUCHERRY", "MANGALORE": "MANGALURU",
    "BELGAUM": "BELAGAVI", "HUBLI": "HUBBALLI", "GULBARGA": "KALABURAGI", "SHIMOGA": "SHIVAMOGGA",
    "TUMKUR": "TUMAKURU", "BELLARY": "BALLARI", "BIJAPUR": "VIJAYAPURA", "VIZAG": "VISAKHAPATNAM",
    "NASIK": "NASHIK", "AURANGABAD": "CHHATRAPATI SAMBHAJINAGAR", "OSMANABAD": "DHARASHIV",
    "TUTICORIN": "THOOTHUKUDI", "TRICHY": "TIRUCHIRAPPALLI", "TIRUCHIRAPALLI": "TIRUCHIRAPPALLI",
    "CAWNPORE": "KANPUR", "SIMLA": "SHIMLA", "JUBBULPORE": "JABALPUR", "GAUHATI": "GUWAHATI",
    "NEW DELHI": "DELHI", "NCR": "DELHI",
}
GENERIC_PLACE_WORDS = {
    "NAGAR", "CITY", "TOWN", "PUR", "ROAD", "COLONY", "SECTOR", "NEW", "OLD", "EAST", "WEST", "NORTH",
    "SOUTH", "CENTRAL", "URBAN", "RURAL", "DISTRICT", "DIST", "TALUK", "TEHSIL", "BAZAR", "BAZAAR",
    "MAIN", "CAMP", "CANTONMENT", "CANTT", "HO", "SO", "BO", "PO", "GPO", "LAYOUT", "STATION",
}
# India Post office-name suffixes (B.O / S.O / H.O after norm_text, plus a few spelled-out variants)
OFFICE_SUFFIX_RE = re.compile(r"\s+(B ?O|S ?O|H ?O|G ?P ?O|M ?D ?G|BRANCH OFFICE|SUB OFFICE|HEAD OFFICE)$")


def norm_place(s):
    """norm_text + strip post-office suffixes + map renamed cities."""
    n = norm_text(s)
    if n is None or n in ("NULL", "NONE", "NA", "N A", "NAN"):
        return None
    n = OFFICE_SUFFIX_RE.sub("", n).strip()
    return CITY_ALIASES.get(n, n) or None


def _content_tokens(s):
    return [t for t in s.split() if t not in GENERIC_PLACE_WORDS]


@functools.lru_cache(maxsize=None)
def similarity(a, b):
    """0-1 similarity of two already-normalised place strings (see the markdown above)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    best = fuzz.ratio(a, b) / 100.0
    ta, tb = _content_tokens(a), _content_tokens(b)
    short = ta if len(" ".join(ta)) <= len(" ".join(tb)) else tb
    if ta and tb and any(len(t) >= 4 for t in short):
        best = max(best, fuzz.token_set_ratio(" ".join(ta), " ".join(tb)) / 100.0)
    return best


def fuzzy_match(a, b, threshold=FUZZY_THRESHOLD):
    return similarity(a, b) >= threshold


def resolve_state(s):
    """Canonical directory state for a typed state: exact/alias via `canon_state`, else fuzzy >= threshold."""
    c = canon_state(s)
    if c:
        return c
    n = norm_text(s)
    if not n or n in ("NULL", "NONE", "NA", "N A"):
        return None
    scored = [(similarity(n, st), st) for st in CANON_STATES]
    best = max(scored)
    return best[1] if best[0] >= FUZZY_THRESHOLD else None

# COMMAND ----------

# MAGIC %md ## Pincodes

# COMMAND ----------

PIN_RE = re.compile(r"(?<!\d)([1-9]\d{2})\s?(\d{3})(?!\d)")


def clean_pincode(s):
    """Digits of the zip field when they form exactly one 6-digit pincode ('201 301' -> 201301)."""
    if s is None:
        return None
    d = re.sub(r"\D", "", str(s))
    return int(d) if len(d) == 6 and d[0] != "0" else None


def pincodes_in_text(*texts):
    out = []
    for t in texts:
        if t:
            out.extend(int(a + b) for a, b in PIN_RE.findall(str(t)))
    return out
