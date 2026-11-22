"""The universal contract between any recommendation source (adapter) and the UI.

The frontend reads only these shapes. Keep them stable; add optional fields rather than renaming.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Query(BaseModel):
    service: str = Field(description="Service key or label, e.g. 'dialysis'")
    place: str = Field(description="PIN code, city, district, or 'lat,lon'")
    max_km: float = 75
    top_n: int = 5
    public_only: bool = False     # government (public) facilities only


class Service(BaseModel):
    key: str
    label: str
    aliases: list[str] = []


class ServiceTerm(BaseModel):
    term: str                     # everyday word, symptom or Hindi/Hinglish word, lower case
    service: Optional[str] = None # the one service it points at, or None for the group's default


class ServiceGroup(BaseModel):
    """A broad, user-friendly care area ("Pregnancy & childbirth") over one or more specific services."""
    key: str
    label: str
    description: str = ""
    services: list[str] = []                  # member service keys; services[0] is listed first
    default_service: Optional[str] = None     # used when the user names only the group; None = ask refine_question
    refine_question: Optional[str] = None
    terms: list[ServiceTerm] = []


class Evidence(BaseModel):
    field: str            # source column, e.g. "procedure"
    label: str            # human label, e.g. "Listed procedure"
    text: str             # verbatim text from the record


class Check(BaseModel):
    """One evidence dimension for a headline service (not a clinical checklist)."""
    key: str
    label: str
    status: str                   # found / unknown / contradicted
    points: float
    max_points: float
    cited_text: Optional[str] = None
    field: Optional[str] = None   # source column, or "service:<key>" when another service's evidence counts
    claim_type: Optional[str] = None


class Claim(BaseModel):
    """A verbatim phrase that mentions the service, with how it was judged."""
    text: str
    field: str
    claim_type: str               # direct / list_dump / hedged / third_party / negated


class LocationCheck(BaseModel):
    """One of the five location validation checks (notebooks/location_validation_scoring/SCORING_CRITERIA.md)."""
    key: str                      # pincode / city_state / district_region / circle_division / coordinates
    label: str
    kind: str                     # main / secondary
    status: Optional[str] = None  # pass / partial (counts half) / fail / missing
    why: Optional[str] = None     # plain-language reason when it failed


class LocationValidation(BaseModel):
    """How consistent the facility's location claims are with each other. Shown on the card; feeds q_location."""
    status: str                   # scored / not_scored
    score: Optional[int] = None   # 0-5; pass >= 3 (facilities scoring 0-2 are never returned)
    label: Optional[str] = None   # verified_all / verified_strong / verified_partial
    checks: list[LocationCheck] = []


class ScorePart(BaseModel):
    key: str
    label: str
    points: float
    max: Optional[float] = None   # None for penalties


class Score(BaseModel):
    match: float                  # final ranking score
    trust: float                  # 0-100 evidence/data-quality score
    distance: float               # 0-100, 100 = at the search point
    trust_weight: float = 0.6
    distance_weight: float = 0.4
    parts: list[ScorePart] = []   # components of `match` (positives and penalties)
    mode: str = "weighted"        # "weighted" (match = 0.6 trust + 0.4 distance) or "quality_first" (match = Quality)


class Confidence(BaseModel):
    label: str                    # High / Medium / Low / Unconfirmed
    score: float                  # 0-100
    tier: Optional[str] = None    # strong / moderate / weak
    rule: str = ""                # the rule that produced the label, for display


class Recommendation(BaseModel):
    rank: int
    id: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[int] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    facebook: Optional[str] = None
    email: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    distance_km: Optional[float] = None
    facility_type: Optional[str] = None
    operator_type: Optional[str] = None
    confidence: Confidence
    score: Score
    tags: list[str] = []
    evidence: list[Evidence] = []
    rejected_evidence: list[str] = []   # negative / referral-only mentions that were NOT counted
    match_pattern: Optional[str] = None # regex used to find the service in the text (for highlighting)
    caveats: list[str] = []
    sources: list[str] = []
    why: str = ""                       # one-paragraph plain-language reason
    how: str = ""                       # the score arithmetic as text
    # quality-first ranking (optional; adapters that don't rank this way leave them empty)
    travel_min: Optional[int] = None            # estimated travel time
    travel_budget_min: Optional[int] = None     # how long a patient can reasonably travel for this service
    ranking_band: Optional[str] = None          # reachable / farther option / unconfirmed
    points_below_best: Optional[int] = None     # Quality points below the best remaining option when ranked
    support_found: list[str] = []               # supporting services counted in readiness (e.g. ICU, blood bank)
    is_nearest_alternative: bool = False        # nearest qualifying facility, shown although it is not #1
    is_better_farther: bool = False             # clearly better, but beyond the travel budget
    tradeoff_note: Optional[str] = None
    counterfactual_note: Optional[str] = None   # "what would change this"
    checks: list[Check] = []                    # evidence checklist (headline services)
    claims: list[Claim] = []                    # every matched phrase with its claim type
    call_to_confirm: Optional[str] = None       # one fact worth checking by phone
    identity_conflict: bool = False
    coherence: Optional[float] = None           # record coherence score 0-100
    verified_service: Optional[str] = None      # latest reviewer decision on the service itself: confirmed / rejected
    # "How solid is this pick?" (#1 only) and tips for the other cards
    double_checks: list["DoubleCheck"] = []     # the ranking re-run with one doubt at a time
    pick_strength: Optional[str] = None         # "Solid" / "Shaky"
    pick_strength_note: Optional[str] = None    # "Shaky pick: if its one website is wrong, X is #1."
    tip_note: Optional[str] = None              # "Would be your best option if you can travel up to 2 hours."
    location_validation: Optional[LocationValidation] = None


class Origin(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    label: Optional[str] = None
    matched_as: Optional[str] = None


class DoubleCheck(BaseModel):
    kind: str                         # "data" (doubts about the records) or "situation" (the patient's circumstances)
    label: str                        # "Facilities found on just one website are ignored"
    still_first: Optional[bool] = None  # None = no facility passes this check
    winner: Optional[str] = None      # who is #1 under this check


Recommendation.model_rebuild()


class RecommendResponse(BaseModel):
    query: Query
    service_label: Optional[str] = None
    service_key: Optional[str] = None
    origin: Origin = Origin()
    results: list[Recommendation] = []
    n_candidates: int = 0
    adapter: str = ""
    method: str = ""                    # how ranking works, for the "How we score" panel
    notes: list[str] = []               # e.g. "place not recognised"
    ranking_rule: str = ""              # the rule, printed verbatim
    travel_assumption: str = ""
    search_note: Optional[str] = None   # e.g. "search widened to 150 km"
    safety_note: Optional[str] = None   # e.g. "if unstable, go to the nearest 24x7 emergency facility first"
    n_excluded_unverified_location: int = 0   # facilities left out because their location could not be verified


class VerifyRequest(BaseModel):
    facility_id: str
    service_key: str
    check_key: str = "service"          # a checklist item, or "service" for the service itself
    status: str                         # confirmed / rejected
    note: Optional[str] = None
    evidence_url: Optional[str] = None


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []
    max_km: Optional[float] = None


class ChatResponse(BaseModel):
    reply: str
    query: Optional[Query] = None
    recommendations: Optional[RecommendResponse] = None
    parsed_by: str = ""                 # "llm" or "keywords"
    reply_source: str = ""              # "llm" (passed the grounding check) or "template" (+ why)
