from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flow.schemas.competency_card import CompetencyCard

_WEAK_EVIDENCE_SCORE_CAP = 2.0
_MIN_COMPETENCY_SCORE = 1.0
_MAX_COMPETENCY_SCORE = 5.0

_DIMENSION_SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "velocity": (
        "deadline",
        "eta",
        "launch",
        "milestone",
        "released",
        "rollout",
        "schedule",
        "shipped",
        "timeline",
        "unblock",
    ),
    "ownership": (
        "accountable",
        "dri",
        "driver",
        "end to end",
        "end-to-end",
        "owned",
        "ownership",
        "responsible",
        "took ownership",
    ),
    "expertise": (
        "architecture",
        "distributed",
        "optimization tradeoff",
        "paradigm",
        "protocol",
        "scalability design",
        "system design",
        "tradeoff",
    ),
    "qed": (
        "a/b test",
        "ab test",
        "analysis",
        "confidence interval",
        "experiment",
        "hypothesis",
        "significance",
        "statistical",
        "validated",
    ),
    "economy": (
        "cost",
        "efficiency",
        "headcount",
        "infra spend",
        "optimization",
        "reduce spend",
        "resource usage",
        "saved",
    ),
    "code_quality": (
        "coverage",
        "lint",
        "maintainability",
        "refactor",
        "review",
        "static analysis",
        "test",
        "tooling",
    ),
    "debugging": (
        "debug",
        "incident investigation",
        "postmortem",
        "rca",
        "root cause",
        "troubleshoot",
        "mttr",
    ),
    "reliability": (
        "alerting",
        "availability",
        "failover",
        "on-call",
        "resilien",
        "runbook",
        "sli",
        "slo",
        "uptime",
    ),
    "teaching": (
        "coached",
        "knowledge sharing",
        "mentored",
        "onboard",
        "talk",
        "training",
        "workshop",
    ),
}


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return slug or "unknown"


def build_person_payload(
    derived_person: dict[str, Any],
    person_id: str = "",
    person_type: str = "",
    role_family: str = "",
    level: str = "",
    current_title: str = "",
    name: str = "",
    linkedin_profile_url: str = "",
) -> dict[str, Any]:
    selected_type = person_type.strip().lower() if person_type else ""
    if selected_type not in {"internal", "candidate"}:
        selected_type = str(derived_person.get("type") or "candidate")

    selected_role_family = role_family.strip() if role_family else ""
    if selected_role_family not in {"IC", "EM", "PM", "TPM", "Other"}:
        selected_role_family = str(derived_person.get("role_family") or "Other")

    selected_person_id = person_id.strip() if person_id else ""
    if not selected_person_id:
        selected_person_id = str(derived_person.get("person_id") or "unknown_person")

    selected_level = level.strip() if level else ""
    if not selected_level:
        selected_level = str(derived_person.get("level") or "")

    selected_current_title = current_title.strip() if current_title else ""
    if not selected_current_title:
        selected_current_title = str(derived_person.get("current_title") or "")

    selected_name = name.strip() if name else ""
    if not selected_name:
        selected_name = str(derived_person.get("name") or "")

    selected_linkedin_profile_url = (
        linkedin_profile_url.strip() if linkedin_profile_url else ""
    )
    if not selected_linkedin_profile_url:
        selected_linkedin_profile_url = str(derived_person.get("linkedin_profile_url") or "")

    return {
        "person_id": selected_person_id,
        "type": selected_type,
        "role_family": selected_role_family,
        "level": selected_level or None,
        "current_title": selected_current_title or None,
        "name": selected_name or None,
        "linkedin_profile_url": selected_linkedin_profile_url or None,
    }


def normalize_generated_card(generated_card: dict[str, Any], rubric_name: str) -> dict[str, Any]:
    generated_card["competency_scores"].setdefault("rubric_name", rubric_name)
    generated_card["competency_scores"].setdefault("score_scale", {"min": 1, "max": 5})
    generated_card["competency_scores"].setdefault("summary", None)
    generated_card.setdefault("highlights", [])
    generated_card.setdefault("archetype", {"summary_tldr": "", "keywords": []})

    competency_scores = generated_card.get("competency_scores", {})
    score_scale = (
        competency_scores.get("score_scale", {})
        if isinstance(competency_scores, dict)
        else {}
    )
    scale_min = float(score_scale.get("min", _MIN_COMPETENCY_SCORE))
    scale_max = float(score_scale.get("max", _MAX_COMPETENCY_SCORE))
    if scale_min > scale_max:
        scale_min, scale_max = _MIN_COMPETENCY_SCORE, _MAX_COMPETENCY_SCORE

    dimensions = competency_scores.get("dimensions", {}) if isinstance(competency_scores, dict) else {}
    if isinstance(dimensions, dict):
        for dimension_name, dimension_data in dimensions.items():
            if not isinstance(dimension_data, dict):
                continue

            evidence = dimension_data.get("evidence")
            if evidence is None:
                dimension_data["evidence"] = []
            elif isinstance(evidence, list):
                normalized_evidence: list[dict[str, str]] = []
                for item in evidence:
                    if isinstance(item, str):
                        normalized_evidence.append({"text": item, "evidence_type": "unknown"})
                    elif isinstance(item, dict):
                        text_value = item.get("text")
                        if text_value is None:
                            text_value = str(item)
                        evidence_type = item.get("evidence_type") or "unknown"
                        normalized_evidence.append(
                            {
                                "text": str(text_value),
                                "evidence_type": str(evidence_type),
                            }
                        )
                    else:
                        normalized_evidence.append(
                            {"text": str(item), "evidence_type": "unknown"}
                        )
                dimension_data["evidence"] = normalized_evidence
            else:
                dimension_data["evidence"] = []

            score = dimension_data.get("score")
            if isinstance(score, (int, float)):
                clamped_score = max(scale_min, min(float(score), scale_max))
                if not _has_dimension_specific_signal(
                    str(dimension_name), dimension_data.get("evidence")
                ):
                    clamped_score = min(clamped_score, _WEAK_EVIDENCE_SCORE_CAP)
                    if dimension_data.get("confidence") == "high":
                        dimension_data["confidence"] = "medium"
                dimension_data["score"] = clamped_score

        expertise = dimensions.get("expertise")
        if isinstance(expertise, dict) and not isinstance(
            expertise.get("system_design_signals"), list
        ):
            expertise["system_design_signals"] = []

    highlights = generated_card.get("highlights")
    if highlights is None:
        generated_card["highlights"] = []
    elif isinstance(highlights, list):
        normalized_highlights: list[dict[str, str]] = []
        for item in highlights:
            if isinstance(item, str):
                normalized_highlights.append({"text": item, "evidence_type": "unknown"})
            elif isinstance(item, dict):
                text_value = item.get("text")
                if text_value is None:
                    text_value = str(item)
                evidence_type = item.get("evidence_type") or "unknown"
                normalized_highlights.append(
                    {
                        "text": str(text_value),
                        "evidence_type": str(evidence_type),
                    }
                )
            else:
                normalized_highlights.append(
                    {"text": str(item), "evidence_type": "unknown"}
                )
        generated_card["highlights"] = normalized_highlights
    else:
        generated_card["highlights"] = []

    archetype = generated_card.get("archetype")
    if not isinstance(archetype, dict):
        generated_card["archetype"] = {"summary_tldr": "", "keywords": []}
    else:
        archetype.setdefault("summary_tldr", "")
        keywords = archetype.get("keywords")
        if keywords is None:
            archetype["keywords"] = []
        elif not isinstance(keywords, list):
            archetype["keywords"] = [str(keywords)]

    return generated_card


def persist_competency_card(
    generated_card: dict[str, Any],
    output_dir: str | Path,
    filename_person_id: str,
    filename_suffix: str = "",
) -> tuple[dict[str, Any], Path]:
    card = CompetencyCard.model_validate(generated_card)
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    person_id_slug = safe_slug(filename_person_id or "unknown_person")
    suffix_slug = safe_slug(filename_suffix) if filename_suffix else ""
    suffix_segment = (
        f"_{suffix_slug}" if suffix_slug and suffix_slug != person_id_slug else ""
    )
    filename = f"{person_id_slug}{suffix_segment}_competency_card.json"
    output_path = output_root / filename

    with output_path.open("w", encoding="utf-8") as file_obj:
        json.dump(card.model_dump(mode="json"), file_obj, indent=2)
        file_obj.write("\n")

    return card.model_dump(mode="json"), output_path


def _normalize_signal_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _contains_keyword(normalized_text: str, keyword: str) -> bool:
    normalized_keyword = _normalize_signal_text(keyword)
    if not normalized_keyword:
        return False
    if " " in normalized_keyword:
        return normalized_keyword in normalized_text
    return bool(re.search(rf"\b{re.escape(normalized_keyword)}\b", normalized_text))


def _extract_evidence_texts(evidence: object) -> list[str]:
    if not isinstance(evidence, list):
        return []
    texts: list[str] = []
    for item in evidence:
        if isinstance(item, dict):
            text_value = item.get("text")
            if text_value is not None:
                texts.append(str(text_value))
        elif isinstance(item, str):
            texts.append(item)
    return texts


def _has_dimension_specific_signal(dimension_name: str, evidence: object) -> bool:
    keywords = _DIMENSION_SIGNAL_KEYWORDS.get(dimension_name, ())
    if not keywords:
        return True
    evidence_texts = _extract_evidence_texts(evidence)
    if not evidence_texts:
        return False

    for evidence_text in evidence_texts:
        normalized_text = _normalize_signal_text(evidence_text)
        if not normalized_text:
            continue
        if any(_contains_keyword(normalized_text, keyword) for keyword in keywords):
            return True
    return False
