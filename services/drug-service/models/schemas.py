"""Pydantic schemas for drug-service request and response shapes.

These define the public contract for every endpoint. Agent
implementations in later commits return shapes that satisfy these
schemas. Bilingual fields are typed as ``BilingualText`` — both
``en`` and ``ar`` must be supplied; routes upstream of bilingual
content are responsible for picking the right language for the
caller.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal["en", "ar"]
Severity = Literal["contraindicated", "major", "moderate", "minor"]
ConfidenceFloat = float


# ─── Shared building blocks ───────────────────────────────────────


class BilingualText(BaseModel):
    """A string that exists in both English and Arabic.

    Used for disclaimers, agent-emitted user-facing prose, and any
    other content where the service is responsible for both
    languages. Missing language is a 500 — the agent must return both.
    """

    model_config = ConfigDict(frozen=True)
    en: str
    ar: str


class Citation(BaseModel):
    """Source citation attached to an agent response."""

    model_config = ConfigDict(frozen=True)
    source: str  # e.g. "drugs.com", "ddimdl", "rxnorm", "mayo_clinic"
    title: str | None = None
    url: str | None = None
    chunk_id: str | None = None  # Qdrant point id when from RAG
    snippet: str | None = None


class AgentMeta(BaseModel):
    """Per-response telemetry shared by every agent endpoint."""

    model_config = ConfigDict(frozen=True)
    agent_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    latency_ms: int = Field(ge=0)
    tokens_used: int = Field(ge=0, default=0)
    disclaimer: BilingualText


# ─── Drug identifier shapes ───────────────────────────────────────


class DrugIdentifier(BaseModel):
    """A drug as the caller submits it.

    Either ``name`` (preferred — gets normalised) or ``rxcui`` (RxNorm
    Concept Unique Identifier — already canonical). One is required.
    """

    model_config = ConfigDict(frozen=True)
    name: str | None = None
    rxcui: str | None = None

    @field_validator("rxcui")
    @classmethod
    def _rxcui_format(cls, v: str | None) -> str | None:
        if v is not None and not v.isdigit():
            raise ValueError("rxcui must be a numeric string")
        return v


class NormalisedDrug(BaseModel):
    """A drug after RxNorm normalisation."""

    model_config = ConfigDict(frozen=True)
    rxcui: str
    generic_name: str
    brand_names: list[str] = Field(default_factory=list)
    drug_class: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    normalisation_path: Literal["exact", "fuzzy", "rxnorm_api"]


# ─── Lookup ───────────────────────────────────────────────────────


class LookupRequest(BaseModel):
    drug: DrugIdentifier
    language: Language = "en"


class LookupData(BaseModel):
    rxcui: str
    generic_name: str
    brand_names: list[str]
    drug_class: str | None
    indications: list[BilingualText]
    mechanism_of_action: BilingualText | None
    contraindications: list[BilingualText]


class LookupResponse(BaseModel):
    data: LookupData
    citations: list[Citation]
    meta: AgentMeta


# ─── Interactions ─────────────────────────────────────────────────


class InteractionsRequest(BaseModel):
    drugs: list[DrugIdentifier] = Field(min_length=2, max_length=10)
    language: Language = "en"


class InteractionPair(BaseModel):
    drug_a: str
    drug_b: str
    severity: Severity
    description: BilingualText
    source_tier: Literal["ddimdl", "drug_rag", "web_search"]


class InteractionsData(BaseModel):
    pairs: list[InteractionPair]
    overall_severity: Severity | None  # max across pairs


class InteractionsResponse(BaseModel):
    data: InteractionsData
    citations: list[Citation]
    meta: AgentMeta


# ─── Dosage ───────────────────────────────────────────────────────


class PatientContext(BaseModel):
    """Caller-supplied context that modifies dosing recommendations."""

    model_config = ConfigDict(frozen=True)
    age_years: int | None = None
    weight_kg: float | None = None
    renal_function: Literal["normal", "mild", "moderate", "severe"] | None = None
    hepatic_function: Literal["normal", "mild", "moderate", "severe"] | None = None
    pregnancy: bool | None = None
    conditions: list[str] = Field(default_factory=list)


class DosageRequest(BaseModel):
    drug: DrugIdentifier
    patient: PatientContext = Field(default_factory=PatientContext)
    language: Language = "en"


class DosageRegimen(BaseModel):
    population: Literal["adult", "pediatric", "elderly", "renal", "hepatic"]
    standard_dose: BilingualText
    max_daily: BilingualText | None
    notes: BilingualText | None = None


class DosageData(BaseModel):
    regimens: list[DosageRegimen]
    adjustments_applied: list[BilingualText]


class DosageResponse(BaseModel):
    data: DosageData
    citations: list[Citation]
    meta: AgentMeta


# ─── Comparison ───────────────────────────────────────────────────


class ComparisonRequest(BaseModel):
    drugs: list[DrugIdentifier] = Field(min_length=2, max_length=5)
    language: Language = "en"


class ComparisonRow(BaseModel):
    drug_rxcui: str
    drug_name: str
    mechanism: BilingualText
    efficacy_summary: BilingualText
    common_side_effects: list[BilingualText]
    cost_tier: Literal["$", "$$", "$$$", "$$$$"]
    contraindications: list[BilingualText]
    drug_class: str | None


class ComparisonData(BaseModel):
    rows: list[ComparisonRow]


class ComparisonResponse(BaseModel):
    data: ComparisonData
    citations: list[Citation]
    meta: AgentMeta


# ─── Pharmacokinetics ─────────────────────────────────────────────


class PKRequest(BaseModel):
    drug: DrugIdentifier
    language: Language = "en"


class AbsorptionData(BaseModel):
    tmax_hours: float | None
    bioavailability_percent: float | None
    notes: BilingualText | None = None


class DistributionData(BaseModel):
    vd_l_per_kg: float | None
    protein_binding_percent: float | None


class MetabolismData(BaseModel):
    primary_cyp_enzymes: list[str]
    notes: BilingualText | None = None


class ExcretionData(BaseModel):
    half_life_hours: float | None
    primary_route: Literal["renal", "hepatic", "fecal", "mixed"] | None


class PKData(BaseModel):
    absorption: AbsorptionData
    distribution: DistributionData
    metabolism: MetabolismData
    excretion: ExcretionData


class PKResponse(BaseModel):
    data: PKData
    citations: list[Citation]
    meta: AgentMeta


# ─── Alternative ──────────────────────────────────────────────────


class AlternativeRequest(BaseModel):
    drug: DrugIdentifier
    reason: str  # free-text from caller: "patient cough", "QTc prolongation", etc.
    language: Language = "en"


class AlternativeCandidate(BaseModel):
    rxcui: str
    name: str
    drug_class: str | None
    rationale: BilingualText
    same_class: bool


class AlternativeData(BaseModel):
    original_rxcui: str
    candidates: list[AlternativeCandidate]


class AlternativeResponse(BaseModel):
    data: AlternativeData
    citations: list[Citation]
    meta: AgentMeta


# ─── Acquisition ──────────────────────────────────────────────────


class AcquisitionRequest(BaseModel):
    drug: DrugIdentifier
    country_iso: str = Field(min_length=2, max_length=2)  # ISO 3166-1 alpha-2
    language: Language = "en"


class AcquisitionData(BaseModel):
    available_otc: bool | None
    available_prescription: bool | None
    price_tier: Literal["$", "$$", "$$$", "$$$$"] | None
    buying_considerations: list[BilingualText]


class AcquisitionResponse(BaseModel):
    data: AcquisitionData
    citations: list[Citation]
    meta: AgentMeta


# ─── Free-text query (LangGraph orchestrator) ─────────────────────


class QueryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: Language = "en"


class QueryResponse(BaseModel):
    """Result envelope for the orchestrator endpoint.

    ``primary_agent`` is the agent the orchestrator selected as the
    main responder. ``data`` is that agent's data payload (a union of
    the per-agent ``*Data`` types). ``called_agents`` lists every
    agent that contributed to this response in execution order.
    """

    primary_agent: str
    called_agents: list[str]
    data: dict[str, Any]
    citations: list[Citation]
    meta: AgentMeta


__all__ = [
    "AcquisitionData",
    "AcquisitionRequest",
    "AcquisitionResponse",
    "AgentMeta",
    "AlternativeCandidate",
    "AlternativeData",
    "AlternativeRequest",
    "AlternativeResponse",
    "BilingualText",
    "Citation",
    "ComparisonData",
    "ComparisonRequest",
    "ComparisonResponse",
    "ComparisonRow",
    "DosageData",
    "DosageRegimen",
    "DosageRequest",
    "DosageResponse",
    "DrugIdentifier",
    "InteractionPair",
    "InteractionsData",
    "InteractionsRequest",
    "InteractionsResponse",
    "Language",
    "LookupData",
    "LookupRequest",
    "LookupResponse",
    "NormalisedDrug",
    "PKData",
    "PKRequest",
    "PKResponse",
    "PatientContext",
    "QueryRequest",
    "QueryResponse",
    "Severity",
]
