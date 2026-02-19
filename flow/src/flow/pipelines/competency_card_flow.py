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


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return slug or "unknown"


class CompetencyCardFlow(FlowSpec):
    pdf_path = Parameter("pdf-path", type=str, help="Path to source PDF file.")
    person_id = Parameter("person-id", type=str, default="unknown_person")
    person_type = Parameter("person-type", type=str, default="candidate")
    role_family = Parameter("role-family", type=str, default="Other")
    level = Parameter("level", type=str, default="unknown")
    current_title = Parameter("current-title", type=str, default="unknown")
    primary_org = Parameter("primary-org", type=str, default="unknown")
    tenure_months = Parameter("tenure-months", type=str, default="")
    start_date = Parameter("start-date", type=str, default="")
    end_date = Parameter("end-date", type=str, default="")
    rubric_name = Parameter("rubric-name", type=str, default="default_competency_rubric")
    rubric_version = Parameter("rubric-version", type=str, default="")
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
        tenure_months = None
        if self.tenure_months:
            try:
                tenure_months = float(self.tenure_months)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid tenure-months value '{self.tenure_months}'. Expected a number."
                ) from exc

        person_payload = {
            "person_id": self.person_id,
            "type": self.person_type,
            "role_family": self.role_family,
            "level": self.level,
            "current_title": self.current_title,
            "primary_org": self.primary_org,
            "tenure_months": tenure_months,
            "time_window": {
                "start_date": self.start_date or None,
                "end_date": self.end_date or None,
            },
        }
        generated = generate_competency_card(
            extracted_text=self.extracted_text,
            person_payload=person_payload,
            model=self.model or None,
        )

        generated.setdefault("schema_version", "1.0")
        generated["person"] = person_payload
        generated.setdefault("competency_scores", {})
        generated["competency_scores"].setdefault("rubric_name", self.rubric_name)
        generated["competency_scores"].setdefault(
            "rubric_version", self.rubric_version or None
        )
        self.generated_card = generated
        self.next(self.validate_and_persist)

    @step
    def validate_and_persist(self):
        if isinstance(self.generated_card, dict):
            dimensions = self.generated_card.get("competency_scores", {}).get("dimensions", {})
            if isinstance(dimensions, dict):
                for dimension_data in dimensions.values():
                    if isinstance(dimension_data, dict) and dimension_data.get("evidence") is None:
                        dimension_data["evidence"] = []
        card = CompetencyCard.model_validate(self.generated_card)
        output_root = Path(self.output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)

        filename = (
            f"{_safe_slug(self.person_id)}_"
            f"{_safe_slug(self.source_pdf.stem)}_"
            "competency_card.json"
        )
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

