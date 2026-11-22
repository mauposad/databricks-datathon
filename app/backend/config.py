"""Runtime settings, read from environment variables (set in app.yaml on Databricks, or your shell locally)."""
import os

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "ce4eb527f62e5ff7")
CATALOG = os.getenv("CARE_CATALOG", "workspace")
SCHEMA = os.getenv("CARE_SCHEMA", "datathon")
# Optional prefix on every SQL object name (tables and functions); empty in production. Used to point a local
# backend at a sandbox copy of the pipeline, e.g. CARE_SCHEMA=default CARE_OBJECT_PREFIX=lvsbx_
OBJECT_PREFIX = os.getenv("CARE_OBJECT_PREFIX", "")
ADAPTER = os.getenv("ADAPTER", "find_care")
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")
DEFAULT_MAX_KM = float(os.getenv("DEFAULT_MAX_KM", "75"))
DEFAULT_TOP_N = int(os.getenv("DEFAULT_TOP_N", "5"))
# Seconds a search result is reused for an identical search (0 turns the cache off). Cleared on every verification.
RESULT_CACHE_TTL = float(os.getenv("RESULT_CACHE_TTL", "600"))
# Warm-up: start the SQL warehouse when the app boots and when the page loads, so it is running by the time the user
# searches. At most one warm-up per WARMUP_COOLDOWN seconds. There is no periodic keep-alive (it would burn the free
# compute quota). WARMUP=0 turns it off.
WARMUP = os.getenv("WARMUP", "1") != "0"
WARMUP_COOLDOWN = float(os.getenv("WARMUP_COOLDOWN", "120"))
# Reviewer name used for verifications when the app runs locally (Databricks Apps sends X-Forwarded-Email)
LOCAL_REVIEWER = os.getenv("LOCAL_REVIEWER", "local developer")
