"""FastAPI entry point: JSON API under /api, and the built React app at /."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import chat, config
from .adapters import get_adapter
from .schema import ChatRequest, ChatResponse, Query, RecommendResponse, Service

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Care Finder")
STATIC = Path(__file__).resolve().parent.parent / "static"


@app.get("/api/health")
def health():
    return {"ok": True, "adapter": config.ADAPTER, "llm": config.LLM_ENDPOINT}


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


if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = (STATIC / path).resolve()
        ok = path and f.is_file() and f.is_relative_to(STATIC)
        return FileResponse(f if ok else STATIC / "index.html")
