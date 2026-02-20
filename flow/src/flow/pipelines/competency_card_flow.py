from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from metaflow import FlowSpec, Parameter, step

from flow.schemas.competency_card import CompetencyCard
from flow.services.card_generator import generate_competency_card
from flow.services.pdf_extractor import extract_text_from_pdf
from flow.services.person_attributes import derive_person_attributes


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return slug or "unknown"


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


class CompetencyCardFlow(FlowSpec):
    pdf_path = Parameter("pdf-path", type=str, help="Path to source PDF file.")
    person_id = Parameter("person-id", type=str, default="")
    person_type = Parameter("person-type", type=str, default="")
    role_family = Parameter("role-family", type=str, default="")
    level = Parameter("level", type=str, default="")
    current_title = Parameter("current-title", type=str, default="")
    rubric_name = Parameter("rubric-name", type=str, default="default_competency_rubric")
    output_dir = Parameter("output-dir", type=str, default="outputs")
    model = Parameter("model", type=str, default="")

    @step
    def start(self):
        load_dotenv()
        self.source_pdf = Path(self.pdf_path).expanduser().resolve()
        if not self.source_pdf.exists():
            raise FileNotFoundError(f"PDF not found at path: {self.source_pdf}")
        self.next(self.extract_pdf_text)

    @step
    def extract_pdf_text(self):
        self.extracted_text = extract_text_from_pdf(self.source_pdf)
        self.next(self.generate_card)

    @step
    def generate_card(self):
        load_dotenv()

        derived_person = derive_person_attributes(self.extracted_text, self.source_pdf)
        selected_type = self.person_type.strip().lower() if self.person_type else ""
        if selected_type not in {"internal", "candidate"}:
            selected_type = derived_person.get("type") or "candidate"

        selected_role_family = self.role_family.strip() if self.role_family else ""
        if selected_role_family not in {"IC", "EM", "PM", "TPM", "Other"}:
            selected_role_family = derived_person.get("role_family") or "Other"

        selected_person_id = self.person_id.strip() if self.person_id else ""
        if not selected_person_id:
            selected_person_id = derived_person.get("person_id") or "unknown_person"

        selected_level = self.level.strip() if self.level else ""
        if not selected_level:
            selected_level = derived_person.get("level") or ""

        selected_current_title = self.current_title.strip() if self.current_title else ""
        if not selected_current_title:
            selected_current_title = derived_person.get("current_title") or ""

        person_payload = {
            "person_id": selected_person_id,
            "type": selected_type,
            "role_family": selected_role_family,
            "level": selected_level or None,
            "current_title": selected_current_title or None,
        }
        generated = generate_competency_card(
            extracted_text=self.extracted_text,
            person_payload=person_payload,
            model=self.model or None,
        )

        generated["person"] = person_payload
        generated.setdefault("competency_scores", {})
        generated["competency_scores"].setdefault("rubric_name", self.rubric_name)
        generated["competency_scores"].setdefault("score_scale", {"min": 1, "max": 5})
        generated["competency_scores"].setdefault("summary", None)
        generated.setdefault("highlights", [])
        generated.setdefault("archetype", {"summary_tldr": "", "keywords": []})
        self.generated_card = generated
        self.next(self.validate_and_persist)

    @step
    def validate_and_persist(self):
        if isinstance(self.generated_card, dict):
            competency_scores = self.generated_card.get("competency_scores", {})
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
                                normalized_evidence.append(
                                    {"text": item, "evidence_type": "unknown"}
                                )
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
            highlights = self.generated_card.get("highlights")
            if highlights is None:
                self.generated_card["highlights"] = []
            elif isinstance(highlights, list):
                normalized_highlights: list[dict[str, str]] = []
                for item in highlights:
                    if isinstance(item, str):
                        normalized_highlights.append(
                            {"text": item, "evidence_type": "unknown"}
                        )
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
                self.generated_card["highlights"] = normalized_highlights
            else:
                self.generated_card["highlights"] = []

            archetype = self.generated_card.get("archetype")
            if not isinstance(archetype, dict):
                self.generated_card["archetype"] = {"summary_tldr": "", "keywords": []}
            else:
                archetype.setdefault("summary_tldr", "")
                keywords = archetype.get("keywords")
                if keywords is None:
                    archetype["keywords"] = []
                elif not isinstance(keywords, list):
                    archetype["keywords"] = [str(keywords)]
        card = CompetencyCard.model_validate(self.generated_card)
        output_root = Path(self.output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)

        person_id_for_filename = card.person.person_id or "unknown_person"
        filename = f"{_safe_slug(person_id_for_filename)}_competency_card.json"
        self.output_path = output_root / filename
        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump(card.model_dump(mode="json"), f, indent=2)
            f.write("\n")

        self.competency_card = card.model_dump(mode="json")
        self.generated_on = date.today().isoformat()
        self.next(self.end)

    @step
    def end(self):
        print(f"Competency Card saved to: {self.output_path}")
        print(f"Generated on: {self.generated_on}")


def main():
    CompetencyCardFlow()


if __name__ == "__main__":
    main()

