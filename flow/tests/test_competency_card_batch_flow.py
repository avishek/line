from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flow.pipelines.competency_card_batch_flow import (  # noqa: E402
    _discover_top_level_pdfs,
    _summarize_results,
)
from flow.pipelines.competency_card_shared import persist_competency_card  # noqa: E402


class CompetencyCardBatchFlowHelpersTests(unittest.TestCase):
    def test_discovers_only_top_level_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "one.pdf").write_text("x", encoding="utf-8")
            (root / "two.pdf").write_text("x", encoding="utf-8")
            (root / "notes.txt").write_text("x", encoding="utf-8")

            nested = root / "nested"
            nested.mkdir()
            (nested / "three.pdf").write_text("x", encoding="utf-8")

            discovered = _discover_top_level_pdfs(root)
            self.assertEqual([path.name for path in discovered], ["one.pdf", "two.pdf"])

    def test_summarizes_success_and_failures(self) -> None:
        results: list[dict[str, object]] = [
            {"source_pdf": "/tmp/a.pdf", "success": True, "error_message": None},
            {"source_pdf": "/tmp/b.pdf", "success": False, "error_message": "ValueError: bad"},
            {"source_pdf": "/tmp/c.pdf", "success": True, "error_message": None},
            {"source_pdf": "/tmp/d.pdf", "success": False, "error_message": "TimeoutError: slow"},
        ]

        success_count, failure_count, failed_results = _summarize_results(results)
        self.assertEqual(success_count, 2)
        self.assertEqual(failure_count, 2)
        self.assertEqual(
            [entry["source_pdf"] for entry in failed_results],
            ["/tmp/b.pdf", "/tmp/d.pdf"],
        )


class _FakeValidatedCard:
    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "person": {"person_id": "dummy", "type": "candidate", "role_family": "Other"},
            "competency_scores": {
                "rubric_name": "default",
                "score_scale": {"min": 1, "max": 5},
                "dimensions": {},
            },
            "highlights": [],
            "archetype": {"summary_tldr": "", "keywords": []},
        }


class CompetencyCardBatchFilenameTests(unittest.TestCase):
    @patch("flow.pipelines.competency_card_shared.CompetencyCard.model_validate")
    def test_persist_omits_suffix_when_person_id_matches_stem(self, mock_validate) -> None:
        mock_validate.return_value = _FakeValidatedCard()
        with tempfile.TemporaryDirectory() as temp_dir:
            _, output_path = persist_competency_card(
                generated_card={},
                output_dir=temp_dir,
                filename_person_id="arihants",
                filename_suffix="arihants",
            )
        self.assertEqual(output_path.name, "arihants_competency_card.json")

    @patch("flow.pipelines.competency_card_shared.CompetencyCard.model_validate")
    def test_persist_keeps_suffix_when_different_from_person_id(self, mock_validate) -> None:
        mock_validate.return_value = _FakeValidatedCard()
        with tempfile.TemporaryDirectory() as temp_dir:
            _, output_path = persist_competency_card(
                generated_card={},
                output_dir=temp_dir,
                filename_person_id="arihants",
                filename_suffix="profile_v2",
            )
        self.assertEqual(output_path.name, "arihants_profile_v2_competency_card.json")


if __name__ == "__main__":
    unittest.main()
