from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PersonalInformation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None
    headline: str | None
    location: str | None
    linkedin_url: str | None


class Skills(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class ExperienceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    title: str
    start_date: str | None
    end_date: str | None
    duration: str | None
    location: str | None
    description_bullets: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution: str
    degree: str | None
    field_of_study: str | None
    start_year: str | None
    end_year: str | None


class ResumeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personal_information: PersonalInformation
    skills: Skills
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
