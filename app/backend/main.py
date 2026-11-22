"""FastAPI entry point: JSON API under /api, and the built React app at /."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import chat, config, sql, warmup
from .adapters import get_adapter
from .schema import ChatRequest, ChatResponse, Query, RecommendResponse, Service, VerifyRequest

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    warmup.trigger("app start")  # background thread; startup does not wait for the warehouse
    yield


app = FastAPI(title="Care Finder", lifespan=lifespan)
STATIC = Path(__file__).resolve().parent.parent / "static"


@app.get("/api/health")
def health():
    return {"ok": True, "adapter": config.ADAPTER, "llm": config.LLM_ENDPOINT}


@app.post("/api/warmup")
def warmup_endpoint():
    """Called by the page on load: starts the warehouse in the background (rate limited), returns at once."""
    return {"started": warmup.trigger("page load")}


@app.get("/api/services", response_model=list[Service])
def services():
    return get_adapter().services()


@app.get("/api/places", response_model=list[str])
def places():
    return get_adapter().places()


@app.post("/api/recommend", response_model=RecommendResponse)
def recommend(q: Query):
    if not q.service.strip() or not q.place.strip():
        raise HTTPException(400, "service and place are required")
    q.top_n = max(1, min(q.top_n, 20))
    q.max_km = max(1, min(q.max_km, 1000))
    return get_adapter().recommend(q)


@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "message is required")
    return chat.handle(req)


@app.post("/api/verify")
def verify(v: VerifyRequest, request: Request):
    """Record a reviewer's Confirm / Reject. Goes to the verifications overlay table only, never into silver/gold."""
    if v.status not in ("confirmed", "rejected"):
        raise HTTPException(400, "status must be 'confirmed' or 'rejected'")
    if not re.fullmatch(r"[a-z0-9_]{1,40}", v.check_key) or v.service_key not in {s.key for s in get_adapter().services()}:
        raise HTTPException(400, "unknown service or check")
    reviewer = request.headers.get("X-Forwarded-Email") or config.LOCAL_REVIEWER
    sql.query(f"""INSERT INTO {sql.fq('verifications')}
                  (facility_id, service_key, check_key, status, reviewer, ts, note, evidence_url)
                  VALUES (:facility_id, :service_key, :check_key, :status, :reviewer, current_timestamp(), :note, :evidence_url)""",
              {"facility_id": v.facility_id[:64], "service_key": v.service_key, "check_key": v.check_key, "status": v.status,
               "reviewer": reviewer[:200], "note": (v.note or "")[:500] or None, "evidence_url": (v.evidence_url or "")[:500] or None})
    get_adapter().invalidate_results()  # the overlay changes rankings; the page re-runs the search next
    return {"ok": True, "reviewer": reviewer}


PLANNER_COLUMNS = """district, state, service_label, nearest_facility, nearest_tier, nearest_quality, nearest_km, nearest_travel_min,
  quality_facility, quality_facility_quality, quality_km, quality_travel_min, travel_budget_min, quality_within_budget,
  n_reachable, nfhs_district, nfhs_match_rule, institutional_birth_pct, institutional_birth_public_pct, csection_rate_pct,
  health_insurance_pct, women_anaemic_pct, women_high_blood_sugar_pct, men_high_blood_sugar_pct, women_high_bp_pct"""


@app.get("/api/planner")
def planner(service: str, state: str | None = None):
    """District planner rows for one headline service, worst access first."""
    if not re.fullmatch(r"[a-z0-9_]{1,40}", service):
        raise HTTPException(400, "unknown service")
    return sql.query(f"""SELECT {PLANNER_COLUMNS} FROM {sql.fq('gold_district_access')}
                         WHERE service_key = :service AND (:state IS NULL OR state = :state)
                         ORDER BY quality_travel_min DESC NULLS FIRST, district""",
                     {"service": service, "state": state})


if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = (STATIC / path).resolve()
        ok = path and f.is_file() and f.is_relative_to(STATIC)
        return FileResponse(f if ok else STATIC / "index.html")
