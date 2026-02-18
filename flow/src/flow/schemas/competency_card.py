from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeWindow(StrictBaseModel):
    start_date: date | None = None
    end_date: date | None = None


class Person(StrictBaseModel):
    person_id: str
    type: Literal["internal", "candidate"]
    role_family: Literal["IC", "EM", "PM", "TPM", "Other"]
    level: str
    current_title: str
    primary_org: str
    tenure_months: float | None = None
    time_window: TimeWindow


class ScoreScale(StrictBaseModel):
    min: int = 1
    max: int = 5
    meaning: str = "1=needs improvement, 3=meets, 5=exceeds"


class DimensionScore(StrictBaseModel):
    score: float | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]


class CompetencyDimensions(StrictBaseModel):
    execution_velocity: DimensionScore
    ownership: DimensionScore
    technical_depth: DimensionScore
    system_design: DimensionScore
    quality_craftsmanship: DimensionScore
    reliability_operational_excellence: DimensionScore
    cross_functional_influence: DimensionScore
    communication: DimensionScore
    leadership_team_leverage: DimensionScore
    product_sense: DimensionScore


class Overall(StrictBaseModel):
    rating: str | None = None
    summary: str


class CompetencyScores(StrictBaseModel):
    rubric_name: str
    rubric_version: str | None = None
    score_scale: ScoreScale
    dimensions: CompetencyDimensions
    overall: Overall


class Metric(StrictBaseModel):
    name: str
    value: str
    direction: Literal["up", "down", "n/a"]
    confidence: Literal["high", "medium", "low"]


class Highlight(StrictBaseModel):
    title: str
    one_liner: str
    scope: Literal["team", "org", "cross_org", "company", "external_partners"]
    role: Literal["led", "co_led", "key_contributor", "supporting"]
    metrics: list[Metric] = Field(default_factory=list)
    constraints: list[
        Literal[
            "scale",
            "latency",
            "cost",
            "compliance",
            "security",
            "availability",
            "partner_dependency",
        ]
    ] = Field(default_factory=list)
    stakeholders: list[
        Literal["eng", "product", "ops", "finance", "external_partner"]
    ] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]


class ImpactPortfolio(StrictBaseModel):
    time_horizon: Literal["last_6_months", "last_12_months", "last_24_months"]
    highlights: list[Highlight] = Field(default_factory=list)
    primary_domains: str
    technical_stack_signals: list[str] = Field(default_factory=list)


class Theme(StrictBaseModel):
    theme: str
    evidence: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"]
    confidence: Literal["high", "medium", "low"]


class GrowthEdges(StrictBaseModel):
    themes: list[Theme] = Field(default_factory=list)
    suggested_development_moves: list[str] = Field(default_factory=list)


class Signals(StrictBaseModel):
    seniority_signal: Literal["low", "medium", "high"]
    scope_signal: Literal["low", "medium", "high"]
    technical_rigor_signal: Literal["low", "medium", "high"]
    leadership_signal: Literal["low", "medium", "high"]


class ArchetypeFeatures(StrictBaseModel):
    summary_tldr: str
    keywords: list[str] = Field(default_factory=list)
    signals: Signals


class EmbeddingPayloads(StrictBaseModel):
    impact_embedding_text: str
    competency_embedding_text: str
    full_embedding_text: str


class CompetencyCard(StrictBaseModel):
    schema_version: Literal["1.0"] = "1.0"
    person: Person
    competency_scores: CompetencyScores
    impact_portfolio: ImpactPortfolio
    growth_edges: GrowthEdges
    archetype_features: ArchetypeFeatures
    embedding_payloads: EmbeddingPayloads

