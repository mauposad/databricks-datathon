"""Adapter for workspace.datathon.find_care(service, place, max_km, top_n).

Maps the SQL function's columns onto the universal contract and builds the interpretability
fields (score parts, evidence by column, tags, confidence rule).
"""
from __future__ import annotations

import time
from typing import Any

from .. import sql
from ..schema import (Confidence, Evidence, Origin, Query, RecommendResponse, Recommendation, Score,
                      ScorePart, Service)
from .base import Adapter

CONFIDENCE_RULE = ("High: trust ≥ 70 with strong/moderate evidence · Medium: trust 45–69 · Low: trust < 45 · "
                   "Unconfirmed: only weak evidence (a related specialty or a passing mention in the description)")

METHOD = ("Rank = 0.6 × trust + 0.4 × distance, where distance = 100 × (1 − km / radius). "
          "Trust (0–100) = evidence in the record (up to 60) + independent source websites (up to 15) "
          "+ reported size (up to 10) + location certainty (up to 15), minus penalties for possible merged records, "
          "non-hospital facilities for hospital services, negative/referral-only mentions, and implausible numbers. "
          "Facilities with only weak evidence are never ranked above strong or moderate ones.")

EVIDENCE_FIELDS = [  # (column in find_care, source column in the raw data, label)
    ("procedures_cited", "procedure", "Listed procedure"),
    ("capabilities_cited", "capability", "Listed capability"),
    ("equipment_cited", "equipment", "Listed equipment"),
    ("specialties_cited", "specialties", "Listed specialty"),
]

_CACHE: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (time.time(), val)
    return val


def confidence_for(trust: float, tier: str | None) -> str:
    if tier == "weak":
        return "Unconfirmed"
    if trust >= 70:
        return "High"
    if trust >= 45:
        return "Medium"
    return "Low"


def _tags(r: dict) -> list[str]:
    tags: list[str] = []
    if r.get("evidence_tier"):
        tags.append(f"{r['evidence_tier'].capitalize()} evidence")
    if r.get("facility_type"):
        tags.append(r["facility_type"].capitalize())
    if r.get("operator_type"):
        tags.append(r["operator_type"].capitalize())
    if r.get("capacity_beds"):
        tags.append(f"{r['capacity_beds']} beds")
    if r.get("number_doctors"):
        tags.append(f"{r['number_doctors']} doctor{'s' if r['number_doctors'] != 1 else ''}")
    n = r.get("n_source_domains")
    if n is not None:
        tags.append("Single source" if n <= 1 else f"{n} sources")
    if (r.get("pen_merged") or 0) < 0:
        tags.append("Possible merged record")
    if (r.get("pen_facility_type") or 0) < 0:
        tags.append("Not a hospital")
    if (r.get("pen_negated") or 0) < 0:
        tags.append("Has referral mentions")
    if r.get("location_confidence") in ("low", "none"):
        tags.append("Location uncertain")
    return tags


def _score(r: dict) -> Score:
    parts = []
    for key, label, mx in [("pts_evidence", "Evidence in record", 60), ("pts_sources", "Independent sources", 15),
                           ("pts_scale", "Reported size", 10), ("pts_location", "Location certainty", 15)]:
        if r.get(key) is not None:
            parts.append(ScorePart(key=key, label=label, points=r[key], max=mx))
    for key, label in [("pen_merged", "Possible merged record"), ("pen_facility_type", "Not a hospital"),
                       ("pen_negated", "Negative/referral mention"), ("pen_numbers", "Implausible numbers")]:
        if (r.get(key) or 0) < 0:
            parts.append(ScorePart(key=key, label=label, points=r[key]))
    return Score(match=r.get("match_score") or 0, trust=r.get("trust_score") or 0,
                 distance=r.get("distance_score") or 0, parts=parts)


def _evidence(r: dict) -> list[Evidence]:
    ev = [Evidence(field=src, label=label, text=t)
          for col, src, label in EVIDENCE_FIELDS for t in (r.get(col) or [])]
    if r.get("description_cited"):
        ev.append(Evidence(field="description", label="Description", text=r["description_cited"].strip()))
    return ev


def to_recommendation(r: dict) -> Recommendation:
    trust = r.get("trust_score") or 0
    tier = r.get("evidence_tier")
    return Recommendation(
        rank=r["rank"], id=r["facility_id"], name=r["facility_name"],
        address=r.get("address"), city=r.get("city"), district=r.get("district"), state=r.get("state"),
        pincode=r.get("pincode"), phone=r.get("phone"), website=r.get("website"), facebook=r.get("facebook"),
        email=r.get("email"), lat=r.get("lat"), lon=r.get("lon"), distance_km=r.get("distance_km"),
        facility_type=r.get("facility_type"), operator_type=r.get("operator_type"),
        confidence=Confidence(label=confidence_for(trust, tier), score=trust, tier=tier, rule=CONFIDENCE_RULE),
        score=_score(r), tags=_tags(r), evidence=_evidence(r),
        rejected_evidence=r.get("negated_or_referral_mentions") or [],
        match_pattern=r.get("match_pattern"), caveats=r.get("caveats") or [],
        sources=r.get("source_urls") or [], why=r.get("why") or "", how=r.get("how") or "",
    )


class FindCareAdapter(Adapter):
    name = "find_care"

    def services(self) -> list[Service]:
        def load():
            rows = sql.query(f"SELECT service_key, service_label, aliases FROM {sql.fq('ref_services')} ORDER BY service_label")
            return [Service(key=r["service_key"], label=r["service_label"], aliases=r["aliases"] or []) for r in rows]
        return _cached("services", 3600, load)

    def places(self) -> list[str]:
        def load():
            rows = sql.query(f"""
                SELECT DISTINCT initcap(lower(district)) AS d FROM {sql.fq('silver_pincode_geo')}
                WHERE district IS NOT NULL AND lat IS NOT NULL ORDER BY d""")
            return [r["d"] for r in rows]
        return _cached("places", 3600, load)

    def recommend(self, q: Query) -> RecommendResponse:
        rows = sql.query(f"SELECT * FROM {sql.fq('find_care')}(:service, :place, CAST(:max_km AS DOUBLE), CAST(:top_n AS INT))",
                         {"service": q.service, "place": q.place, "max_km": q.max_km, "top_n": q.top_n})
        resp = RecommendResponse(query=q, adapter=self.name, method=METHOD)
        if not rows:
            resp.notes.append(self._diagnose(q))
            return resp
        first = rows[0]
        resp.service_label = first.get("searched_service")
        resp.origin = Origin(lat=first.get("origin_lat"), lon=first.get("origin_lon"),
                             label=first.get("searched_from"), matched_as=first.get("origin_matched_as"))
        resp.n_candidates = first.get("n_candidates") or len(rows)
        resp.results = [to_recommendation(r) for r in rows]
        if any(r.confidence.label == "Unconfirmed" for r in resp.results):
            resp.notes.append("Some results only have weak evidence and are shown to fill the list; treat them as unconfirmed.")
        return resp

    def _diagnose(self, q: Query) -> str:
        """Explain an empty result: unknown service, unknown place, or nothing within the radius."""
        svc = q.service.strip().lower()
        known = any(svc in (s.key, s.label.lower(), *s.aliases) for s in self.services())
        if not known:
            return f"'{q.service}' isn't a service we can search yet. Try one from the list."
        loc = sql.query(f"SELECT * FROM {sql.fq('resolve_location')}(:place)", {"place": q.place})
        if not loc:
            return f"We couldn't find '{q.place}'. Try a 6-digit PIN code, a district or a city name."
        return f"No facility with evidence for this service within {q.max_km:g} km of {loc[0]['label']}. Try a larger radius."
