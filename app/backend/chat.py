"""Chat / voice path: free text -> Query -> recommendations -> grounded spoken-style reply.

The LLM only (1) extracts the query and (2) words the answer from the returned rows.
It never ranks or adds facilities. If the endpoint fails, keyword parsing and a template reply take over.
"""
from __future__ import annotations

import json
import logging
import re

from . import config, sql
from .adapters import get_adapter
from .schema import ChatRequest, ChatResponse, Query, RecommendResponse, Service

log = logging.getLogger(__name__)


def _llm(messages: list[dict], max_tokens: int = 400) -> str:
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": 0}
    resp = sql.client().api_client.do("POST", f"/serving-endpoints/{config.LLM_ENDPOINT}/invocations", body=body)
    return resp["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


# ---------- parsing ----------

def parse_with_llm(req: ChatRequest, services: list[Service]) -> dict:
    catalog = "\n".join(f"- {s.key}: {s.label} (also: {', '.join(s.aliases[:6])})" for s in services)
    system = (
        "You turn a user's request for healthcare in India into a search query. Reply with JSON only:\n"
        '{"service": <one service key from the list or null>, "place": <PIN code, city, district or "lat,lon" or null>, '
        '"max_km": <number or null>, "ask": <short follow-up question if service or place is missing, else null>}\n'
        "Map symptoms or synonyms to the closest service (e.g. 'kidney failure' -> dialysis, 'premature baby' -> nicu). "
        "Use earlier turns to fill anything the latest message leaves out.\nServices:\n" + catalog
    )
    msgs = [{"role": "system", "content": system}]
    msgs += [{"role": t.role, "content": t.content} for t in req.history[-6:] if t.role in ("user", "assistant")]
    msgs.append({"role": "user", "content": req.message})
    return _extract_json(_llm(msgs, 200))


def parse_with_keywords(req: ChatRequest, services: list[Service]) -> dict:
    text = " ".join([t.content for t in req.history if t.role == "user"][-3:] + [req.message]).lower()
    service = None
    best = 0
    for s in services:
        for term in [s.key.replace("_", " "), s.label.lower(), *s.aliases]:
            if term and re.search(rf"\b{re.escape(term)}\b", text) and len(term) > best:
                service, best = s.key, len(term)
    place = None
    if m := re.search(r"\b([1-9]\d{5})\b", text):
        place = m.group(1)
    elif m := re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{2,3}\.\d+)", text):
        place = f"{m.group(1)},{m.group(2)}"
    elif m := re.search(r"\b(?:in|near|around|at|from)\s+([a-z][a-z .'-]{2,40}?)(?:[,.?!]|\s+(?:for|within|please)|$)", text):
        place = m.group(1).strip()
    km = None
    if m := re.search(r"(\d{1,4})\s*(?:km|kilomet)", text):
        km = float(m.group(1))
    ask = None
    if not service:
        ask = "Which service do you need? For example dialysis, NICU, emergency C-section or MRI."
    elif not place:
        ask = "Where are you? A PIN code, city or district works."
    return {"service": service, "place": place, "max_km": km, "ask": ask}


# ---------- answering ----------

def _facts(rec: RecommendResponse) -> str:
    lines = []
    for r in rec.results:
        ev = "; ".join(f'{e.label}: "{e.text[:90]}"' for e in r.evidence[:2]) or "no direct evidence"
        lines.append(f"#{r.rank} {r.name}, {r.distance_km} km, confidence {r.confidence.label} (trust {r.confidence.score:g}). "
                     f"Evidence: {ev}. Caveats: {'; '.join(r.caveats[:2]) or 'none'}. Phone: {r.phone or 'not listed'}.")
    return "\n".join(lines)


def template_reply(rec: RecommendResponse) -> str:
    if not rec.results:
        return rec.notes[0] if rec.notes else "I couldn't find a match."
    top = rec.results[0]
    reason = top.evidence[0].text if top.evidence else top.why
    out = (f"I found {len(rec.results)} options for {rec.service_label} near {rec.origin.label}. "
           f"The best match is {top.name}, {top.distance_km} km away, with {top.confidence.label.lower()} confidence, "
           f"because its record lists \"{reason[:120]}\".")
    if len(rec.results) > 1:
        nxt = rec.results[1]
        out += f" Next is {nxt.name} at {nxt.distance_km} km."
    return out


def grounded_reply(req: ChatRequest, rec: RecommendResponse) -> str:
    if not rec.results:
        return template_reply(rec)
    system = ("You are a careful assistant helping someone find healthcare in India. Answer in 2-4 short sentences "
              "that read well aloud. Use ONLY the facilities and facts given; never add facilities, numbers or claims. "
              "Name the top choice, say why using its evidence, give its confidence, and mention one important caveat if any. "
              "Do not use markdown, lists or URLs.")
    user = (f"User asked: {req.message}\nService: {rec.service_label}. Searched from: {rec.origin.label}.\n"
            f"Results (already ranked):\n{_facts(rec)}")
    return _llm([{"role": "system", "content": system}, {"role": "user", "content": user}], 300).strip()


def handle(req: ChatRequest) -> ChatResponse:
    adapter = get_adapter()
    services = adapter.services()
    parsed_by = "llm"
    try:
        p = parse_with_llm(req, services)
    except Exception as e:  # endpoint down / rate limited / bad JSON
        log.warning("LLM parse failed, using keywords: %s", e)
        p, parsed_by = parse_with_keywords(req, services), "keywords"

    keys = {s.key for s in services}
    service = p.get("service") if p.get("service") in keys else None
    place = (p.get("place") or "").strip() or None
    if not service or not place:
        ask = p.get("ask") or ("Which service do you need?" if not service else "Where are you? A PIN code, city or district works.")
        return ChatResponse(reply=ask, parsed_by=parsed_by)

    max_km = req.max_km or p.get("max_km") or config.DEFAULT_MAX_KM
    q = Query(service=service, place=place, max_km=float(max_km), top_n=config.DEFAULT_TOP_N)
    rec = adapter.recommend(q)
    try:
        reply = grounded_reply(req, rec) if parsed_by == "llm" else template_reply(rec)
    except Exception as e:
        log.warning("LLM reply failed, using template: %s", e)
        reply = template_reply(rec)
    return ChatResponse(reply=reply, query=q, recommendations=rec, parsed_by=parsed_by)
