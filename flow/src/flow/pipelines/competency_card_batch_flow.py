from __future__ import annotations

import os
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


def _discover_top_level_pdfs(input_root: Path) -> list[Path]:
    return sorted(path for path in input_root.glob("*.pdf") if path.is_file())


def _summarize_results(results: list[dict[str, object]]) -> tuple[int, int, list[dict[str, object]]]:
    failed_results = [result for result in results if not result.get("success", False)]
    success_count = len(results) - len(failed_results)
    failure_count = len(failed_results)
    return success_count, failure_count, failed_results


class CompetencyCardBatchFlow(FlowSpec):
    input_dir = Parameter("input-dir", type=str, help="Path to source PDF folder.")
    output_dir = Parameter("output-dir", type=str, default="outputs")
    person_id = Parameter("person-id", type=str, default="")
    person_type = Parameter("person-type", type=str, default="")
    role_family = Parameter("role-family", type=str, default="")
    level = Parameter("level", type=str, default="")
    current_title = Parameter("current-title", type=str, default="")
    rubric_name = Parameter("rubric-name", type=str, default="default_competency_rubric")
    model = Parameter("model", type=str, default="")

    @step
    def start(self):
        load_dotenv()
        input_root = Path(self.input_dir).expanduser().resolve()
        if not input_root.exists():
            raise FileNotFoundError(f"Input directory not found: {input_root}")
        if not input_root.is_dir():
            raise NotADirectoryError(f"Input path is not a directory: {input_root}")

        self.output_root = Path(self.output_dir).expanduser().resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)

        pdf_paths = _discover_top_level_pdfs(input_root)
        if not pdf_paths:
            raise FileNotFoundError(f"No PDF files found in: {input_root}")

        self.pdf_paths = [str(path) for path in pdf_paths]
        self.next(self.process_pdf, foreach="pdf_paths")

    @step
    def process_pdf(self):
        load_dotenv()
        self.source_pdf = Path(self.input).expanduser().resolve()
        self.result = {
            "source_pdf": str(self.source_pdf),
            "output_path": None,
            "success": False,
            "error_message": None,
        }

        try:
            extracted_text = extract_text_from_pdf(self.source_pdf)
            derived_person = derive_person_attributes(extracted_text, self.source_pdf)
            person_payload = build_person_payload(
                derived_person=derived_person,
                person_id=self.person_id,
                person_type=self.person_type,
                role_family=self.role_family,
                level=self.level,
                current_title=self.current_title,
            )
            generated = generate_competency_card(
                extracted_text=extracted_text,
                person_payload=person_payload,
                model=self.model or None,
            )
            generated["person"] = person_payload
            normalized_card = normalize_generated_card(
                generated_card=generated,
                rubric_name=self.rubric_name,
            )
            filename_suffix = self.source_pdf.stem
            _, output_path = persist_competency_card(
                generated_card=normalized_card,
                output_dir=self.output_root,
                filename_person_id=person_payload["person_id"],
                filename_suffix=filename_suffix,
            )
            self.result["output_path"] = str(output_path)
            self.result["success"] = True
        except Exception as exc:  # noqa: BLE001
            self.result["error_message"] = f"{type(exc).__name__}: {exc}"

        self.next(self.join)

    @step
    def join(self, inputs):
        self.results = [input_obj.result for input_obj in inputs]
        (
            self.success_count,
            self.failure_count,
            self.failed_results,
        ) = _summarize_results(self.results)
        self.generated_on = date.today().isoformat()
        self.next(self.end)

    @step
    def end(self):
        print(f"Batch run completed on: {self.generated_on}")
        print(f"Total PDFs processed: {len(self.results)}")
        print(f"Successful cards: {self.success_count}")
        print(f"Failures: {self.failure_count}")
        if self.failed_results:
            print("Failed files:")
            for failed in self.failed_results:
                print(f"- {failed['source_pdf']}: {failed['error_message']}")


def main():
    CompetencyCardBatchFlow()


if __name__ == "__main__":
    main()
