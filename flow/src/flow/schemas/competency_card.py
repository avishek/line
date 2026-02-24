from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Person(StrictBaseModel):
    person_id: str
    type: Literal["internal", "candidate"]
    role_family: Literal["IC", "EM", "PM", "TPM", "Other"]
    level: str | None = None
    current_title: str | None = None
    name: str | None = None
    linkedin_profile_url: str | None = None


class ScoreScale(StrictBaseModel):
    min: int = 1
    max: int = 5


class DimensionEvidence(StrictBaseModel):
    text: str
    evidence_type: Literal[
        "quantified_impact",
        "scope_statement",
        "tech_stack",
        "oss",
        "publication",
        "award",
        "testimonial",
        "unknown",
    ]


class DimensionScore(StrictBaseModel):
    score: float | None = None
    evidence: list[DimensionEvidence] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]


class ExpertiseDimensionScore(DimensionScore):
    system_design_signals: list[str] = Field(default_factory=list)


class CompetencyDimensions(StrictBaseModel):
    velocity: DimensionScore
    ownership: DimensionScore
    expertise: ExpertiseDimensionScore
    qed: DimensionScore
    economy: DimensionScore
    code_quality: DimensionScore
    debugging: DimensionScore
    reliability: DimensionScore
    teaching: DimensionScore


class CompetencyScores(StrictBaseModel):
    rubric_name: str
    score_scale: ScoreScale
    dimensions: CompetencyDimensions
    summary: str | None = None


class Highlight(StrictBaseModel):
    text: str
    evidence_type: Literal[
        "quantified_impact",
        "scope_statement",
        "tech_stack",
        "oss",
        "publication",
        "award",
        "testimonial",
        "unknown",
    ]


class Archetype(StrictBaseModel):
    summary_tldr: str
    keywords: list[str] = Field(default_factory=list)


class CompetencyCard(StrictBaseModel):
    person: Person
    competency_scores: CompetencyScores
    highlights: list[Highlight] = Field(default_factory=list)
    archetype: Archetype

