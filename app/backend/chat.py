"""Chat / voice path: free text -> Query -> recommendations -> grounded spoken-style reply.

The LLM only (1) extracts the query and (2) words the answer from the returned rows.
It never ranks or adds facilities. If the endpoint fails, keyword parsing and a template reply take over.
"""
from __future__ import annotations

import json
import logging
import re

from . import config, sql, terms
from .adapters import get_adapter
from .schema import ChatRequest, ChatResponse, Query, RecommendResponse, Service, ServiceGroup

log = logging.getLogger(__name__)


def _llm(messages: list[dict], max_tokens: int = 400) -> str:
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": 0}
    resp = sql.client().api_client.do("POST", f"/serving-endpoints/{config.LLM_ENDPOINT}/invocations", body=body)
    return resp["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


# ---------- parsing ----------

def _catalog(services: list[Service], groups: list[ServiceGroup]) -> str:
    labels = {s.key: s for s in services}
    if not groups:
        return "Services:\n" + "\n".join(f"- {s.key}: {s.label} (also: {', '.join(s.aliases[:6])})" for s in services)
    lines = ["Care groups and their services:"]
    for g in groups:
        lines.append(f"- group {g.key}: {g.label} ({g.description})")
        for k in g.services:
            if k in labels:
                lines.append(f"    - service {k}: {labels[k].label} (also: {', '.join(labels[k].aliases[:5])})")
    return "\n".join(lines)


def parse_with_llm(req: ChatRequest, services: list[Service], groups: list[ServiceGroup]) -> dict:
    system = (
        "You turn a user's request for healthcare in India into a search query. Reply with JSON only:\n"
        '{"service": <service key from the list, or null>, "group": <group key from the list, or null>, '
        '"place": <PIN code, city, district or "lat,lon" or null>, '
        '"max_km": <number or null>, "public_only": <true if they want government / free / sarkari facilities, else false>, '
        '"ask": <short follow-up question if the care need or place is missing, else null>}\n'
        "People use everyday words, symptoms and Hindi/Hinglish. Map them to the closest group, and also to a service "
        "when the request clearly points at one (e.g. 'my wife is in labour' -> group maternity, service null; "
        "'she needs a caesarean' -> service emergency_csection; 'chest pain' -> service cath_lab; "
        "'premature baby' -> service nicu; 'kidney failure' -> service dialysis; 'a scan' -> group imaging, service null; "
        "an illness of a baby or child ('my son has fever') -> service paediatrics, not general medicine). "
        "Use earlier turns to fill anything the latest message leaves out; the latest message wins if they disagree.\n"
        + _catalog(services, groups)
    )
    msgs = [{"role": "system", "content": system}]
    msgs += [{"role": t.role, "content": t.content} for t in req.history[-6:] if t.role in ("user", "assistant")]
    msgs.append({"role": "user", "content": req.message})
    return _extract_json(_llm(msgs, 200))


ASK_SERVICE = "What kind of care do you need? For example childbirth, heart care, a child doctor, dialysis or physiotherapy."
ASK_PLACE = "Where are you? A PIN code, city or district works."


_PLACE = re.compile(r"\b(?:in|near|around|at|from)\s+(?=([a-z][a-z .'-]{2,40}?)"
                    r"(?:[,.?!]|\s+(?:for|within|please|in|near|around|at|from|and)\b|$))")


# Hinglish: "Patna mein", "Lucknow ke paas"
_PLACE_HI = re.compile(r"\b([a-z][a-z.'-]{2,30})\s+(?:mein|me|mai|ke paas|ke pass)\b")
_NOT_PLACE = {"a", "an", "the", "my", "pain", "need", "hospital", "urgent", "trouble", "ghar", "pet", "sir", "hai",
              "dard", "jaldi", "yahan", "wahan", "is", "it", "this", "that", "and", "or", "can", "please"}


def _place_words(text: str, services: list[Service], groups: list[ServiceGroup]) -> str | None:
    """The last "in / near / at X" phrase that is not a care word ("in labour near Patna" -> "patna")."""
    found = [(m.start(), m.group(1).strip()) for m in _PLACE.finditer(text)]
    found += [(m.start(), m.group(1).strip()) for m in _PLACE_HI.finditer(text)]
    cands = []
    for _, c in sorted(found):
        hit = terms.match(c, services, groups)
        if hit and c.startswith(hit.term):  # "in labour", "in pain": a care word, not a place
            continue
        if c.split()[0] in _NOT_PLACE:
            continue
        cands.append(c)
    return cands[-1] if cands else None


def parse_with_keywords(req: ChatRequest, services: list[Service], groups: list[ServiceGroup] | None = None) -> dict:
    users = [t.content for t in req.history if t.role == "user"][-3:]
    turns = [req.message, *reversed(users)]  # newest first
    text = ". ".join(users + [req.message]).lower()
    place = None
    if m := re.search(r"\b([1-9]\d{5})\b", text):
        place = m.group(1)
    elif m := re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{2,3}\.\d+)", text):
        place = f"{m.group(1)},{m.group(2)}"
    else:
        place = _place_words(text, services, groups or [])
    km = None
    if m := re.search(r"(\d{1,4})\s*(?:km|kilomet)", text):
        km = float(m.group(1))
    public_only = bool(re.search(r"\b(government|govt|sarkari|public hospital|free)\b", text))
    hit = terms.match_turns(turns, services, groups or [])
    service, group = (hit.service, hit.group) if hit else (None, None)
    ask = None
    if not service and not group:
        ask = ASK_SERVICE
    elif not place:
        ask = ASK_PLACE
    return {"service": service, "group": group, "place": place, "max_km": km, "public_only": public_only, "ask": ask}


# ---------- answering ----------

def _facts(rec: RecommendResponse) -> str:
    lines = []
    for r in rec.results:
        ev = "; ".join(f'{e.label}: "{e.text[:90]}"' for e in r.evidence[:2]) or "no direct evidence"
        lines.append(f"#{r.rank} {r.name}, {r.distance_km} km"
                     f"{f' (~{r.travel_min} min)' if r.travel_min is not None else ''}, "
                     f"confidence {r.confidence.label} (quality {r.score.match:g}). "
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
    if rec.safety_note:
        out = f"{rec.safety_note} {out}"
    return out


def grounded_reply(req: ChatRequest, rec: RecommendResponse) -> str:
    if not rec.results:
        return template_reply(rec)
    system = ("You are a careful assistant helping someone find healthcare in India. Answer in 2-4 short sentences "
              "that read well aloud. Use ONLY the facilities and facts given; never add facilities, numbers or claims. "
              "Name the top choice, say why using its evidence, give its confidence, and mention one important caveat if any. "
              "Do not use markdown, lists or URLs.")
    user = (f"User asked: {req.message}\nService: {rec.service_label}. Searched from: {rec.origin.label}.\n"
            f"Results (already ranked):\n{_facts(rec)}"
            + (f"\nSafety line (say this first, word for word): {rec.safety_note}" if rec.safety_note else ""))
    return _llm([{"role": "system", "content": system}, {"role": "user", "content": user}], 300).strip()


_NUM = re.compile(r"\d+(?:\.\d+)?")
_FACILITY = re.compile(r"((?:[A-Z][\w.'&-]*\s+){1,6}(?:Hospitals?|Clinic|Centre|Center|Institute|Nursing Home|Medical College|University))")


def grounding_problem(reply: str, rec: RecommendResponse) -> str | None:
    """Return why the LLM reply is not grounded in the results, or None if it is.

    Every number in the reply must appear somewhere in the facts the model was given (distances, minutes, scores,
    PIN codes, phone numbers, evidence quotes...), and every facility-like name must be one of the results
    (or the facility named in the safety line).
    """
    facts = " ".join([_facts(rec), rec.origin.label or "", rec.service_label or "", rec.safety_note or "",
                      rec.search_note or "", str(len(rec.results)), str(rec.query.max_km), str(int(rec.query.max_km))])
    allowed = set(_NUM.findall(facts)) | {"24", "7"}
    for n in _NUM.findall(reply):
        if n not in allowed and n.rstrip("0").rstrip(".") not in allowed:
            return f"number {n} is not in the results"
    names = [r.name.lower() for r in rec.results] + [(rec.safety_note or "").lower()]
    for m in _FACILITY.findall(reply):
        core = re.sub(r"^((the|a|an|at|to|is|and|or|go|try|visit|then)\s+)+", "", m.strip().lower())
        if not any(core in n or n in core for n in names):
            return f'"{m.strip()}" is not one of the results'
    return None


def handle(req: ChatRequest) -> ChatResponse:
    adapter = get_adapter()
    services = adapter.services()
    groups = adapter.service_groups()
    parsed_by = "llm"
    try:
        p = parse_with_llm(req, services, groups)
    except Exception as e:  # endpoint down / rate limited / bad JSON
        log.warning("LLM parse failed, using keywords: %s", e)
        p, parsed_by = parse_with_keywords(req, services, groups), "keywords"

    res = terms.resolve(p.get("service"), p.get("group"), services, groups)
    if not res.service and not res.ask and parsed_by == "llm":
        # the model found no care need: the local vocabulary may still know the words ("haddi toot gayi")
        kw = parse_with_keywords(req, services, groups)
        res = terms.resolve(kw.get("service"), kw.get("group"), services, groups)
    place = (p.get("place") or "").strip() or None
    if not res.service:
        return ChatResponse(reply=res.ask or ASK_SERVICE, parsed_by=parsed_by)
    if not place:
        ask = p.get("ask") if p.get("ask") and parsed_by == "llm" else ASK_PLACE
        return ChatResponse(reply=ask, parsed_by=parsed_by)

    max_km = req.max_km or p.get("max_km") or config.DEFAULT_MAX_KM
    q = Query(service=res.service, place=place, max_km=float(max_km), top_n=config.DEFAULT_TOP_N,
              public_only=bool(p.get("public_only")))
    rec = adapter.recommend(q)
    note = terms.default_note(res, services) if rec.results else None
    if note:
        rec.notes.insert(0, note)
    reply, source = template_reply(rec), "template"
    if parsed_by == "llm" and rec.results:
        try:
            llm_reply = grounded_reply(req, rec)
            problem = grounding_problem(llm_reply, rec)
            if problem:
                log.warning("LLM reply failed the grounding check (%s); using template", problem)
                source = f"template (the AI-worded reply was discarded: {problem})"
            else:
                reply, source = llm_reply, "llm"
        except Exception as e:
            log.warning("LLM reply failed, using template: %s", e)
            source = "template (the AI service did not answer)"
    if note:
        reply = f"{reply} {note}"
    return ChatResponse(reply=reply, query=q, recommendations=rec, parsed_by=parsed_by, reply_source=source)
