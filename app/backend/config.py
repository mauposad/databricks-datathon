"""Runtime settings, read from environment variables (set in app.yaml on Databricks, or your shell locally)."""
import os

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "ce4eb527f62e5ff7")
CATALOG = os.getenv("CARE_CATALOG", "workspace")
SCHEMA = os.getenv("CARE_SCHEMA", "datathon")
ADAPTER = os.getenv("ADAPTER", "find_care")
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")
DEFAULT_MAX_KM = float(os.getenv("DEFAULT_MAX_KM", "75"))
DEFAULT_TOP_N = int(os.getenv("DEFAULT_TOP_N", "5"))
