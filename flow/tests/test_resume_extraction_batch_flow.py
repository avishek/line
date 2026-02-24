from __future__ import annotations

import inspect
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flow.pipelines.resume_extraction_batch_flow import (  # noqa: E402
    ResumeExtractionBatchFlow,
    _discover_top_level_pdfs,
    _ensure_resume_profiles_table,
    _make_output_filename,
    _persist_resume_profile,
    _summarize_results,
    _upsert_resume_profile_row,
)
from flow.schemas.resume_profile import ResumeProfile  # noqa: E402
from flow.services.resume_extractor import (  # noqa: E402
    extract_resume_profile_from_pdf,
    get_resume_parser_prompt_sha,
)


_VALID_PROFILE = {
    "personal_information": {
        "full_name": "Jane Doe",
        "headline": "Senior Software Engineer",
        "location": "Seattle, WA",
        "linkedin_url": "https://www.linkedin.com/in/jane-doe",
    },
    "skills": {
        "top_skills": ["Python", "Distributed Systems"],
        "languages": ["English"],
    },
    "experience": [
        {
            "company": "Example Corp",
            "title": "Senior Software Engineer",
            "start_date": "November 2022",
            "end_date": "Present",
            "duration": "(1 year 3 months)",
            "location": "Seattle, WA",
            "description_bullets": ["Built and shipped a critical platform migration."],
        }
    ],
    "education": [
        {
            "institution": "Example University",
            "degree": "B.S.",
            "field_of_study": "Computer Science",
            "start_year": "2014",
            "end_year": "2018",
        }
    ],
}


class ResumeExtractionBatchFlowHelpersTests(unittest.TestCase):
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
        results = [
            {"source_pdf": "/tmp/a.pdf", "success": True, "error_message": None},
            {"source_pdf": "/tmp/b.pdf", "success": False, "error_message": "ValueError: bad"},
            {"source_pdf": "/tmp/c.pdf", "success": True, "error_message": None},
        ]

        success_count, failure_count, failed_results = _summarize_results(results)
        self.assertEqual(success_count, 2)
        self.assertEqual(failure_count, 1)
        self.assertEqual([entry["source_pdf"] for entry in failed_results], ["/tmp/b.pdf"])

    def test_output_filename_uses_pdf_stem(self) -> None:
        self.assertEqual(_make_output_filename(Path("/tmp/jane-doe.pdf")), "jane-doe_resume.json")

    def test_persist_resume_profile_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = _persist_resume_profile(
                profile=_VALID_PROFILE,
                output_dir=Path(temp_dir),
                source_pdf=Path("/tmp/jane-doe.pdf"),
            )
            self.assertEqual(output_path.name, "jane-doe_resume.json")
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["personal_information"]["full_name"], "Jane Doe")

    def test_ensure_resume_profiles_table_creates_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _ensure_resume_profiles_table(db_path)
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='resume_profiles'"
                ).fetchone()
                columns = {
                    column_info[1]
                    for column_info in conn.execute("PRAGMA table_info(resume_profiles)").fetchall()
                }
            self.assertIsNotNone(row)
            self.assertIn("faiss_index_path", columns)

    def test_ensure_resume_profiles_table_migrates_existing_table_with_faiss_column(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE resume_profiles (
                        id INTEGER PRIMARY KEY,
                        pdf_stem TEXT NOT NULL UNIQUE,
                        source_pdf TEXT NOT NULL,
                        full_name TEXT,
                        profile_json TEXT NOT NULL,
                        prompt_version_sha TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()

            _ensure_resume_profiles_table(db_path)
            with sqlite3.connect(db_path) as conn:
                columns = {
                    column_info[1]
                    for column_info in conn.execute("PRAGMA table_info(resume_profiles)").fetchall()
                }
            self.assertIn("faiss_index_path", columns)

    def test_upsert_resume_profile_row_updates_existing_pdf_stem(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _ensure_resume_profiles_table(db_path)
            source_pdf = Path("/tmp/jane-doe.pdf")
            first_profile = json.loads(json.dumps(_VALID_PROFILE))
            second_profile = json.loads(json.dumps(_VALID_PROFILE))
            second_profile["personal_information"]["full_name"] = "Jane Updated"
            second_profile["skills"]["top_skills"] = ["Python", "Systems Design"]

            with patch(
                "flow.pipelines.resume_extraction_batch_flow._utc_now_iso",
                side_effect=["2026-02-22T00:00:00+00:00", "2026-02-22T00:05:00+00:00"],
            ):
                _upsert_resume_profile_row(
                    db_path=db_path,
                    source_pdf=source_pdf,
                    profile=first_profile,
                    prompt_version_sha="sha-v1",
                )
                _upsert_resume_profile_row(
                    db_path=db_path,
                    source_pdf=source_pdf,
                    profile=second_profile,
                    prompt_version_sha="sha-v2",
                )

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, created_at, updated_at
                    FROM resume_profiles
                    WHERE pdf_stem = ?
                    """,
                    ("jane-doe",),
                ).fetchone()

            self.assertIsNotNone(row)
            if row is None:
                self.fail("Expected row for jane-doe to exist.")

            pdf_stem, source_pdf_str, full_name, profile_json, prompt_sha, created_at, updated_at = row
            self.assertEqual(pdf_stem, "jane-doe")
            self.assertEqual(source_pdf_str, str(source_pdf))
            self.assertEqual(full_name, "Jane Updated")
            self.assertEqual(prompt_sha, "sha-v2")
            self.assertEqual(created_at, "2026-02-22T00:00:00+00:00")
            self.assertEqual(updated_at, "2026-02-22T00:05:00+00:00")
            self.assertEqual(
                json.loads(profile_json)["skills"]["top_skills"],
                ["Python", "Systems Design"],
            )


class ResumeExtractorServiceTests(unittest.TestCase):
    @patch("flow.services.resume_extractor._load_resume_prompt", return_value="fixed prompt")
    @patch("flow.services.resume_extractor.OpenAI")
    def test_extract_resume_profile_validates_schema_and_returns_json(
        self, mock_openai: object, _: object
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "resume.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake")

            client = mock_openai.return_value
            client.responses.create.return_value = SimpleNamespace(
                output_text=json.dumps(_VALID_PROFILE)
            )

            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                parsed = extract_resume_profile_from_pdf(pdf_path, model="gpt-5.1")

            self.assertEqual(parsed["skills"]["top_skills"], ["Python", "Distributed Systems"])
            client.responses.create.assert_called_once()
            ResumeProfile.model_validate(parsed)

    @patch("flow.services.resume_extractor._load_resume_prompt", return_value="fixed prompt")
    @patch("flow.services.resume_extractor.OpenAI")
    def test_extract_resume_profile_rejects_invalid_json(self, mock_openai: object, _: object) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "resume.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake")

            client = mock_openai.return_value
            client.responses.create.return_value = SimpleNamespace(output_text="not-json")

            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with self.assertRaises(ValueError):
                    extract_resume_profile_from_pdf(pdf_path, model="gpt-5.1")

    @patch("flow.services.resume_extractor.subprocess.run")
    @patch("flow.services.resume_extractor._find_git_repo_root")
    @patch("flow.services.resume_extractor.files")
    def test_get_resume_parser_prompt_sha_uses_blob_sha_when_available(
        self, mock_files: object, mock_find_repo_root: object, mock_subprocess_run: object
    ) -> None:
        mock_files.return_value = Path("/repo/flow/src/flow")
        mock_find_repo_root.return_value = Path("/repo")
        mock_subprocess_run.return_value = SimpleNamespace(returncode=0, stdout="blob-sha\n")

        sha = get_resume_parser_prompt_sha()

        self.assertEqual(sha, "blob-sha")
        mock_subprocess_run.assert_called_once_with(
            ["git", "-C", "/repo", "rev-parse", "HEAD:flow/src/flow/prompts/resume_parser.md"],
            capture_output=True,
            text=True,
            check=False,
        )


class FlowWiringTests(unittest.TestCase):
    def test_batch_flow_calls_resume_extractor_service(self) -> None:
        class_source = inspect.getsource(ResumeExtractionBatchFlow)
        self.assertIn("extract_resume_profile_from_pdf", class_source)
        self.assertIn("_persist_resume_profile", class_source)
        self.assertIn("_upsert_resume_profile_row", class_source)


if __name__ == "__main__":
    unittest.main()
