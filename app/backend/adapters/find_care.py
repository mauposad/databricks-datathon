"""Adapter for workspace.datathon.find_care(service, place, max_km, top_n).

Maps the SQL function's columns onto the universal contract and builds the interpretability
fields (score parts, evidence by column, tags, confidence rule).
"""
from __future__ import annotations

import logging
from typing import Optional

from .. import config, sql
from ..cache import Refreshing, TTLCache
from ..schema import (Check, Claim, Confidence, DoubleCheck, Evidence, LocationCheck, LocationValidation, Origin, Query,
                      RecommendResponse, Recommendation, Score, ScorePart, Service, ServiceGroup, ServiceTerm)
from .base import Adapter

log = logging.getLogger(__name__)

CONFIDENCE_RULE = ("High: trust ≥ 70 with strong/moderate evidence · Medium: trust 45–69 · Low: trust < 45 · "
                   "capped at Medium when the record's identity is not settled (possible merged record, near-duplicate "
                   "record nearby, or coordinates and PIN code disagree with nothing to settle it) · "
                   "Probable: the procedure is not named, but a large or teaching hospital lists the specialty (call to confirm) · "
                   "Unconfirmed: only weak evidence (a related specialty or a passing mention in the description) · "
                   "High when a reviewer confirmed the service by phone · "
                   "Ranking puts High before Medium before Low/Probable, then orders by Quality within each group")

QUALITY = ("Quality (0–100) = evidence for this service in the record (up to 50) + readiness (up to 30: hospital vs "
           "clinic, bed count, supporting services such as ICU or blood bank) + record reliability (up to 20: independent "
           "source websites, location certainty, coherence) minus penalties for possible merged records, non-hospital "
           "facilities for hospital services, negative/referral-only mentions and implausible numbers.")

EVIDENCE_FIELDS = [  # (column in find_care, source column in the raw data, label)
    ("procedures_cited", "procedure", "Listed procedure"),
    ("capabilities_cited", "capability", "Listed capability"),
    ("equipment_cited", "equipment", "Listed equipment"),
    ("specialties_cited", "specialties", "Listed specialty"),
]

def _result_key(q: Query) -> tuple:
    """Searches that only differ in case or spacing share a cache entry."""
    norm = lambda s: " ".join(s.split()).lower()
    return (norm(q.service), norm(q.place), round(float(q.max_km), 1), int(q.top_n), bool(q.public_only))


def _bool(v) -> bool | None:
    """Struct fields arrive as JSON strings ("true"/"false") from the SQL API."""
    if v is None or isinstance(v, bool):
        return v
    return str(v).lower() == "true"


def confidence_for(trust: float, tier: str | None, identity_conflict: bool = False) -> str:
    if tier == "weak":
        return "Unconfirmed"
    if tier == "probable":
        return "Probable"
    if trust >= 70 and not identity_conflict:
        return "High"
    if trust >= 45:  # includes trust >= 70 capped by an identity conflict
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
    if r.get("travel_min") is not None:
        tags.append(f"~{r['travel_min']} min travel")
    if r.get("ranking_band") == "farther option":
        tags.append("Farther option")
    if r.get("is_nearest_alternative"):
        tags.append("Nearest option")
    if r.get("possible_duplicate_names"):
        tags.append("Possible duplicate record")
    if r.get("identity_conflict"):
        tags.append("Identity not settled")
    if r.get("verified_service") == "confirmed":
        tags.append("Confirmed by a reviewer")
    elif r.get("verified_service") == "rejected":
        tags.append("Reported not available")
    return tags


QUALITY_PARTS = [  # (column, label, max)
    ("q_evidence", "Evidence for this service", 50),
    ("q_facility_type", "Facility type", 10), ("q_beds", "Beds", 10), ("q_support", "Supporting services", 10),
    ("q_sources", "Independent sources", 8), ("q_location", "Location certainty", 6), ("q_coherence", "Record coherence", 6),
]
PENALTIES = [("pen_merged", "Possible merged record"), ("pen_facility_type", "Not a hospital"),
             ("pen_negated", "Negative/referral mention"), ("pen_numbers", "Implausible numbers")]


def _score(r: dict) -> Score:
    parts = []
    quality_first = r.get("quality_score") is not None
    components = QUALITY_PARTS if quality_first else [
        ("pts_evidence", "Evidence in record", 60), ("pts_sources", "Independent sources", 15),
        ("pts_scale", "Reported size", 10), ("pts_location", "Location certainty", 15)]
    for key, label, mx in components:
        if r.get(key) is not None:
            parts.append(ScorePart(key=key, label=label, points=r[key], max=mx))
    for key, label in PENALTIES:
        if (r.get(key) or 0) < 0:
            parts.append(ScorePart(key=key, label=label, points=r[key]))
    return Score(match=r.get("match_score") or 0, trust=r.get("trust_score") or 0,
                 distance=r.get("distance_score") or 0, parts=parts,
                 mode="quality_first" if quality_first else "weighted")


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
        # find_care computes the label (the ranking orders by it); the Python rule is a fallback for older functions
        confidence=Confidence(label=r.get("confidence_label") or confidence_for(trust, tier, bool(r.get("identity_conflict"))),
                              score=trust, tier=tier,
                              rule=CONFIDENCE_RULE),
        score=_score(r), tags=_tags(r), evidence=_evidence(r),
        rejected_evidence=r.get("negated_or_referral_mentions") or [],
        match_pattern=r.get("match_pattern"), caveats=r.get("caveats") or [],
        sources=r.get("source_urls") or [], why=r.get("why") or "", how=r.get("how") or "",
        travel_min=r.get("travel_min"), travel_budget_min=r.get("travel_budget_min"),
        ranking_band=r.get("ranking_band"), points_below_best=r.get("points_below_best"),
        support_found=r.get("support_found") or [],
        is_nearest_alternative=bool(r.get("is_nearest_alternative")), is_better_farther=bool(r.get("is_better_farther")),
        tradeoff_note=r.get("tradeoff_note"), counterfactual_note=r.get("counterfactual_note"),
        checks=[Check(key=c["check_key"], label=c["check_label"], status=c["status"], points=c["points"] or 0,
                      max_points=c["max_points"] or 0, cited_text=c.get("cited_text"), field=c.get("field"),
                      claim_type=c.get("claim_type")) for c in (r.get("evidence_checks") or [])],
        claims=[Claim(text=c["text"], field=c["field"], claim_type=c["claim_type"]) for c in (r.get("claims_cited") or [])],
        call_to_confirm=r.get("call_to_confirm"),
        identity_conflict=bool(r.get("identity_conflict")), coherence=r.get("record_coherence_score"),
        verified_service=r.get("verified_service"),
        double_checks=[DoubleCheck(kind=c["kind"], label=c["label"], still_first=_bool(c.get("still_first")),
                                   winner=c.get("winner")) for c in (r.get("double_checks") or [])],
        pick_strength=r.get("pick_strength"), pick_strength_note=r.get("pick_strength_note"), tip_note=r.get("tip_note"),
        location_validation=_location_validation(r),
    )


def _location_validation(r: dict) -> Optional[LocationValidation]:
    status = r.get("location_validation_status")
    if not status:  # find_care from before the location gate
        return None
    return LocationValidation(
        status=status, score=r.get("location_validation_score"), label=r.get("location_validation_label"),
        checks=[LocationCheck(key=c["check_key"], label=c["check_label"], kind=c.get("kind") or "main",
                              status=c.get("status"), why=c.get("why")) for c in (r.get("location_checks") or [])])


def _load_services() -> list[Service]:
    rows = sql.query(f"SELECT service_key, service_label, aliases FROM {sql.fq('ref_services')} ORDER BY service_label")
    return [Service(key=r["service_key"], label=r["service_label"], aliases=r["aliases"] or []) for r in rows]


def _load_service_groups() -> list[ServiceGroup]:
    groups = sql.query(f"""SELECT group_key, group_label, description, services, default_service, refine_question
                           FROM {sql.fq('ref_service_groups')} ORDER BY sort_order""")
    terms = sql.query(f"SELECT term, group_key, service_key FROM {sql.fq('ref_service_terms')} ORDER BY term")
    by_group: dict[str, list[ServiceTerm]] = {}
    for t in terms:
        by_group.setdefault(t["group_key"], []).append(ServiceTerm(term=t["term"], service=t["service_key"]))
    return [ServiceGroup(key=g["group_key"], label=g["group_label"], description=g["description"] or "",
                         services=g["services"] or [], default_service=g["default_service"],
                         refine_question=g["refine_question"], terms=by_group.get(g["group_key"], []))
            for g in groups]


def _load_places() -> list[str]:
    rows = sql.query(f"""
        SELECT DISTINCT initcap(lower(district)) AS d FROM {sql.fq('silver_pincode_geo')}
        WHERE district IS NOT NULL AND lat IS NOT NULL ORDER BY d""")
    return [r["d"] for r in rows]


class FindCareAdapter(Adapter):
    name = "find_care"

    def __init__(self):
        self._services = Refreshing("services", _load_services, ttl=3600,
                                    parse=lambda rows: [Service(**r) for r in rows])
        self._groups = Refreshing("service_groups", _load_service_groups, ttl=3600,
                                  parse=lambda rows: [ServiceGroup(**r) for r in rows])
        self._places = Refreshing("places", _load_places, ttl=3600)
        self._results = TTLCache(ttl=config.RESULT_CACHE_TTL, maxsize=256)

    def services(self) -> list[Service]:
        return self._services.get()

    def service_groups(self) -> list[ServiceGroup]:
        try:
            return self._groups.get()
        except Exception as e:  # no snapshot and the tables are missing: the app still works with specific services
            log.warning("Service groups unavailable: %s", e)
            return []

    def places(self) -> list[str]:
        return self._places.get()

    def prefetch(self) -> None:
        self._services.prefetch()
        self._places.prefetch()
        try:
            self._groups.prefetch()
        except Exception as e:
            log.warning("Service groups not loaded: %s", e)

    def invalidate_results(self) -> None:
        """A reviewer's Confirm / Reject changes rankings, so cached searches are dropped."""
        self._results.clear()

    def recommend(self, q: Query) -> RecommendResponse:
        key = _result_key(q)
        hit = self._results.get(key)
        if hit is not None:
            resp = hit.model_copy(deep=True)
            resp.query = q
            return resp
        resp = self._recommend(q)
        self._results.set(key, resp.model_copy(deep=True))
        return resp

    def _recommend(self, q: Query) -> RecommendResponse:
        rows = sql.query(f"SELECT * FROM {sql.fq('find_care')}(:service, :place, CAST(:max_km AS DOUBLE), CAST(:top_n AS INT), "
                         f"CAST(:operator AS STRING))",
                         {"service": q.service, "place": q.place, "max_km": q.max_km, "top_n": q.top_n,
                          "operator": "public" if q.public_only else None})
        resp = RecommendResponse(query=q, adapter=self.name, method=QUALITY)
        if not rows:
            resp.notes.append(self._diagnose(q))
            return resp
        first = rows[0]
        resp.service_label = first.get("searched_service")
        resp.origin = Origin(lat=first.get("origin_lat"), lon=first.get("origin_lon"),
                             label=first.get("searched_from"), matched_as=first.get("origin_matched_as"))
        resp.n_candidates = first.get("n_candidates") or len(rows)
        resp.results = [to_recommendation(r) for r in rows]
        resp.service_key = next((s.key for s in self.services() if s.label == resp.service_label), None)
        resp.ranking_rule = first.get("ranking_rule") or ""
        resp.travel_assumption = first.get("travel_assumption") or ""
        resp.search_note = first.get("search_note") or None
        resp.safety_note = first.get("safety_note") or None
        if resp.ranking_rule:
            resp.method = f"{resp.ranking_rule} {QUALITY} {resp.travel_assumption}"
        if resp.search_note:
            resp.notes.append(resp.search_note)
        resp.n_excluded_unverified_location = first.get("n_excluded_unverified_location") or 0
        if resp.n_excluded_unverified_location:
            n = resp.n_excluded_unverified_location
            resp.notes.append(f"{n} {'facility' if n == 1 else 'facilities'} with evidence for this service "
                              f"{'was' if n == 1 else 'were'} left out because {'its' if n == 1 else 'their'} location "
                              "could not be verified (location score 0-2 of 5).")
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
