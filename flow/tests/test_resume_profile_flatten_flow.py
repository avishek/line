from __future__ import annotations

import inspect
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flow.pipelines.resume_profile_flatten_flow import (  # noqa: E402
    ResumeProfileFlattenFlow,
    fetch_resume_profile_row_by_stem,
)


def _create_resume_profiles_table(db_path: Path) -> None:
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
                faiss_index_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _sample_profile(full_name: str) -> dict[str, object]:
    return {
        "personal_information": {
            "full_name": full_name,
            "headline": "Software Engineer",
            "location": "Remote",
            "linkedin_url": "https://www.linkedin.com/in/example",
        },
        "skills": {
            "top_skills": ["Python", "SQL"],
            "languages": ["English"],
        },
        "experience": [],
        "education": [],
    }


class ResumeProfileFlattenFlowHelpersTests(unittest.TestCase):
    def test_fetch_resume_profile_row_by_stem_returns_matching_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _create_resume_profiles_table(db_path)

            profile_payload = json.dumps(_sample_profile("Jane Doe"))
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "jane-doe",
                        "/tmp/jane-doe.pdf",
                        "Jane Doe",
                        profile_payload,
                        "sha-1",
                        None,
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.commit()

            row = fetch_resume_profile_row_by_stem(db_path=db_path, pdf_stem="jane-doe")
            self.assertEqual(row["id"], 1)
            self.assertEqual(row["pdf_stem"], "jane-doe")
            self.assertEqual(row["profile_json"], profile_payload)

    def test_fetch_resume_profile_row_by_stem_raises_for_missing_pdf_stem(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _create_resume_profiles_table(db_path)

            with self.assertRaises(LookupError):
                fetch_resume_profile_row_by_stem(db_path=db_path, pdf_stem="missing-stem")


class FlowWiringTests(unittest.TestCase):
    def test_resume_profile_flatten_flow_uses_flatten_resume_profile(self) -> None:
        class_source = inspect.getsource(ResumeProfileFlattenFlow)
        self.assertIn("fetch_resume_profile_row_by_stem", class_source)
        self.assertIn("flatten_resume_profile", class_source)


if __name__ == "__main__":
    unittest.main()
