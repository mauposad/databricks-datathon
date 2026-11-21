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


class Service(BaseModel):
    key: str
    label: str
    aliases: list[str] = []


class Evidence(BaseModel):
    field: str            # source column, e.g. "procedure"
    label: str            # human label, e.g. "Listed procedure"
    text: str             # verbatim text from the record


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
    parts: list[ScorePart] = []   # trust components (positives and penalties)


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


class Origin(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    label: Optional[str] = None
    matched_as: Optional[str] = None


class RecommendResponse(BaseModel):
    query: Query
    service_label: Optional[str] = None
    origin: Origin = Origin()
    results: list[Recommendation] = []
    n_candidates: int = 0
    adapter: str = ""
    method: str = ""                    # how ranking works, for the "How we score" panel
    notes: list[str] = []               # e.g. "place not recognised"


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
