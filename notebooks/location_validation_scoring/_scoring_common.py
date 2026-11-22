# Databricks notebook source
# MAGIC %md
# MAGIC # `_scoring_common`: shared config and helpers for the location-validation scoring pipeline
# MAGIC
# MAGIC Loaded by every notebook in this folder with `%run ./_scoring_common`. The calling notebook must first
# MAGIC `%pip install geopandas==1.0.1 plotly==5.24.1 phonenumbers==9.0.44 rapidfuzz==3.13.0` (the serverless job environment, Python 3.12 + numpy 2, has no plotly, which `location_linkage/_common` imports; 5.24.1 works with numpy 2).
# MAGIC
# MAGIC It reuses `../location_linkage/_common` (state canonicalisation, `norm_text`, haversine, output widgets),
# MAGIC so both pipelines spell states and normalise text the same way. Scoring rules live in
# MAGIC `SCORING_CRITERIA.md`; every decision behind them is in `DECISIONS.md`.

# COMMAND ----------

# MAGIC %run ../location_linkage/_common

# COMMAND ----------

import datetime as _dt
import functools

import phonenumbers
from phonenumbers import PhoneNumberType, geocoder
from rapidfuzz import fuzz

SCORING_VERSION = "1.0.0"
REF_VOLUME = "locval_ref"
REF_DIR = f"/Volumes/{OUT_CATALOG}/{OUT_SCHEMA}/{REF_VOLUME}"

FUZZY_THRESHOLD = 0.85  # similarity (0-1) for any text-vs-text comparison
COORD_MATCH_KM = 10.0   # facility point must be within this distance of a reference post office
PASS_SCORE = 3          # scores 0, 1, 2 fail

# in-mob-prefix (CC BY 4.0, https://github.com/hstsethi/in-mob-prefix), pinned so reruns are reproducible
MOBPREFIX_COMMIT = "153ba809d514e74f62a1dc88fb10f0cb1a562e0e"
MOBPREFIX_LEVELS = ["6", "7", "8", "9"]


def mobprefix_url(level):
    return (f"https://raw.githubusercontent.com/hstsethi/in-mob-prefix/{MOBPREFIX_COMMIT}/"
            f"data/{level}xxx-in-mob-prefix.csv")


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

# MAGIC %md ## Phone numbers
# MAGIC
# MAGIC * **Classification and landline area**: Google libphonenumber (`phonenumbers`, Apache-2.0). It knows
# MAGIC   the DoT STD/SDCA plan, so a landline such as `+91 712 662 4444` resolves to "Nagpur, Maharashtra".
# MAGIC * **Mobile circle**: the 4-digit series (first four digits of the 10-digit number) is looked up in
# MAGIC   in-mob-prefix (`bronze_locval_mobile_prefix`). Series missing from its CSV, or listed with a blank circle,
# MAGIC   use the circle predicted by a model trained with in-mob-prefix's own recipe (see notebook 00).
# MAGIC * Telecom circles (licensed service areas) are not India Post circles. `TELECOM_CIRCLE_STATES` lists the
# MAGIC   states each one covers, so phone evidence is compared at **state** level.

# COMMAND ----------

TELECOM_CIRCLE_STATES = {
    "AP": {"ANDHRA PRADESH", "TELANGANA"},
    "AS": {"ASSAM"},
    "BR": {"BIHAR", "JHARKHAND"},
    # Delhi LSA also serves the NCR towns Gurugram, Faridabad (Haryana) and Noida, Ghaziabad (UP)
    "DL": {"DELHI", "HARYANA", "UTTAR PRADESH"},
    "GJ": {"GUJARAT", DNHDD},
    "HP": {"HIMACHAL PRADESH"},
    "HR": {"HARYANA"},
    "JK": {"JAMMU AND KASHMIR", "LADAKH"},
    "KA": {"KARNATAKA"},
    "KL": {"KERALA", "LAKSHADWEEP", "PUDUCHERRY"},  # Mahe (Puducherry) sits inside Kerala
    "MH": {"MAHARASHTRA", "GOA"},                    # Mumbai metro merged into MH upstream
    "MP": {"MADHYA PRADESH", "CHHATTISGARH"},
    "NE": {"ARUNACHAL PRADESH", "MANIPUR", "MEGHALAYA", "MIZORAM", "NAGALAND", "TRIPURA"},
    "OR": {"ODISHA"},
    "PB": {"PUNJAB", "CHANDIGARH"},
    "RJ": {"RAJASTHAN"},
    "TN": {"TAMIL NADU", "PUDUCHERRY"},              # Chennai metro merged into TN upstream
    "UE": {"UTTAR PRADESH"},
    "UW": {"UTTAR PRADESH", "UTTARAKHAND"},
    "UP": {"UTTAR PRADESH", "UTTARAKHAND"},
    "WB": {"WEST BENGAL", "SIKKIM", "ANDAMAN AND NICOBAR ISLANDS"},  # Kolkata metro merged into WB upstream
}
assert all(s in CANON_STATES for v in TELECOM_CIRCLE_STATES.values() for s in v)

# libphonenumber area descriptions that carry no ", State" suffix
AREA_STATE_OVERRIDES = {"NEW DELHI": "DELHI", "DELHI": "DELHI", "MUMBAI": "MAHARASHTRA",
                        "KOLKATA": "WEST BENGAL", "CHENNAI": "TAMIL NADU", "CHANDIGARH": "CHANDIGARH"}
LOCATABLE_TYPES = {PhoneNumberType.FIXED_LINE, PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE}
PHONE_TYPE_NAME = {v: k for k, v in vars(PhoneNumberType).items() if isinstance(v, int)}


def parse_phone_list(official, numbers_json):
    """All distinct phone strings of a facility: officialPhone plus the JSON array in phone_numbers."""
    raw = []
    for v in (official,):
        if v and str(v).strip().lower() not in ("null", "none", ""):
            raw.append(str(v))
    if numbers_json and str(numbers_json).strip().lower() not in ("null", "none", ""):
        try:
            arr = json.loads(numbers_json)
            raw.extend(str(x) for x in (arr if isinstance(arr, list) else [arr]) if x)
        except (ValueError, TypeError):
            raw.extend(re.findall(r"\+?\d[\d\s\-()]{7,}\d", str(numbers_json)))
    seen, out = set(), []
    for r in raw:
        digits = re.sub(r"[^\d+]", "", r)
        if digits and digits not in seen:
            seen.add(digits)
            out.append(digits)
    return out


def classify_phone(raw):
    """-> dict(e164, nsn, phone_type, area_desc, area_state). Pure libphonenumber; mobile circle added later."""
    out = dict(raw=raw, e164=None, nsn=None, phone_type="UNPARSEABLE", area_desc=None, area_state=None)
    try:
        p = phonenumbers.parse(raw, "IN")
    except phonenumbers.NumberParseException:
        return out
    if p.country_code != 91 or not phonenumbers.is_valid_number(p):
        out["phone_type"] = "INVALID_OR_FOREIGN"
        return out
    t = phonenumbers.number_type(p)
    out["e164"] = phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)
    out["nsn"] = str(p.national_number)
    out["phone_type"] = PHONE_TYPE_NAME.get(t, str(t))
    if t == PhoneNumberType.FIXED_LINE:
        desc = geocoder.description_for_number(p, "en") or None
        out["area_desc"] = desc
        if desc:
            parts = [x.strip() for x in desc.split(",")]
            st = resolve_state(parts[-1]) if len(parts) > 1 else None
            out["area_state"] = st or AREA_STATE_OVERRIDES.get(norm_text(parts[0])) or resolve_state(parts[0])
    return out

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
