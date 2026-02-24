from __future__ import annotations

from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from metaflow import FlowSpec, Parameter, step

from flow.pipelines.competency_card_shared import (
    build_person_payload,
    normalize_generated_card,
    persist_competency_card,
)
from flow.services.card_generator import generate_competency_card
from flow.services.pdf_extractor import extract_text_from_pdf
from flow.services.person_attributes import derive_person_attributes


class CompetencyCardFlow(FlowSpec):
    pdf_path = Parameter("pdf-path", type=str, help="Path to source PDF file.")
    person_id = Parameter("person-id", type=str, default="")
    person_type = Parameter("person-type", type=str, default="")
    role_family = Parameter("role-family", type=str, default="")
    level = Parameter("level", type=str, default="")
    current_title = Parameter("current-title", type=str, default="")
    person_name = Parameter("name", type=str, default="")
    linkedin_profile_url = Parameter("linkedin-profile-url", type=str, default="")
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
        person_payload = build_person_payload(
            derived_person=derived_person,
            person_id=self.person_id,
            person_type=self.person_type,
            role_family=self.role_family,
            level=self.level,
            current_title=self.current_title,
            name=self.person_name,
            linkedin_profile_url=self.linkedin_profile_url,
        )
        generated = generate_competency_card(
            extracted_text=self.extracted_text,
            person_payload=person_payload,
            model=self.model or None,
        )

        generated["person"] = person_payload
        self.generated_card = normalize_generated_card(generated, rubric_name=self.rubric_name)
        self.next(self.validate_and_persist)

    @step
    def validate_and_persist(self):
        self.competency_card, self.output_path = persist_competency_card(
            generated_card=self.generated_card,
            output_dir=self.output_dir,
            filename_person_id=self.generated_card["person"]["person_id"],
        )
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

