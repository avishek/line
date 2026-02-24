from __future__ import annotations

import inspect
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flow.pipelines.resume_faiss_backfill_flow import ResumeFaissBackfillFlow  # noqa: E402
from flow.services.resume_indexer import (  # noqa: E402
    backfill_missing_faiss_indexes,
    fetch_rows_for_faiss_backfill,
    fetch_rows_missing_faiss_index,
    flatten_resume_profile,
    update_rows_faiss_index_path,
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
            "headline": "Senior Software Engineer at Stealth Startup",
            "location": "San Francisco, CA",
            "linkedin_url": "https://www.linkedin.com/in/example",
        },
        "skills": {
            "top_skills": ["JavaScript", "Node.js", "React.js"],
            "languages": ["English"],
        },
        "experience": [
            {
                "company": "Stealth",
                "title": "Software Engineer",
                "start_date": "Nov 2022",
                "end_date": "Present",
                "duration": None,
                "location": "Remote",
                "description_bullets": [],
            },
            {
                "company": "Tesla",
                "title": "Senior Software Engineer",
                "start_date": "Feb 2021",
                "end_date": "Nov 2022",
                "duration": None,
                "location": "Palo Alto, CA",
                "description_bullets": [],
            },
        ],
        "education": [
            {
                "institution": "UIUC",
                "degree": "B.S.",
                "field_of_study": "Computer Science",
                "start_year": "2011",
                "end_year": "2015",
            }
        ],
    }


class ResumeIndexerServiceTests(unittest.TestCase):
    def test_fetch_rows_for_faiss_backfill_full_mode_selects_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _create_resume_profiles_table(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "avishek-bhatia",
                        "/tmp/avishek-bhatia.pdf",
                        "Avishek Bhatia",
                        json.dumps(_sample_profile("Avishek Bhatia")),
                        "sha-1",
                        None,
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        2,
                        "jane-doe",
                        "/tmp/jane-doe.pdf",
                        "Jane Doe",
                        json.dumps(_sample_profile("Jane Doe")),
                        "sha-1",
                        "/tmp/existing.faiss",
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.commit()

            selected = fetch_rows_for_faiss_backfill(db_path, mode="full")
            self.assertEqual([row["id"] for row in selected], [1, 2])

    def test_fetch_rows_missing_faiss_index_selects_only_null_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _create_resume_profiles_table(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "avishek-bhatia",
                        "/tmp/avishek-bhatia.pdf",
                        "Avishek Bhatia",
                        json.dumps(_sample_profile("Avishek Bhatia")),
                        "sha-1",
                        None,
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        2,
                        "jane-doe",
                        "/tmp/jane-doe.pdf",
                        "Jane Doe",
                        json.dumps(_sample_profile("Jane Doe")),
                        "sha-1",
                        "/tmp/existing.faiss",
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.commit()

            pending = fetch_rows_missing_faiss_index(db_path)
            self.assertEqual([row["id"] for row in pending], [1])
            self.assertEqual(pending[0]["pdf_stem"], "avishek-bhatia")

    def test_flatten_resume_profile_formats_deterministic_text(self) -> None:
        flattened = flatten_resume_profile(_sample_profile("Avishek Bhatia"))
        expected = (
            "Full Name: Avishek Bhatia\n"
            "Headline: Senior Software Engineer at Stealth Startup\n"
            "Skills: JavaScript, Node.js, React.js\n"
            "Experience:\n"
            "- Stealth | Software Engineer | Nov 2022 - Present\n"
            "- Tesla | Senior Software Engineer | Feb 2021 - Nov 2022\n"
            "Education:\n"
            "- UIUC | B.S. in Computer Science | 2011 - 2015"
        )
        self.assertEqual(flattened, expected)

    def test_flatten_resume_profile_includes_experience_description_bullets(self) -> None:
        profile = _sample_profile("Avishek Bhatia")
        experience = profile["experience"]
        self.assertIsInstance(experience, list)
        first_role = experience[0]
        self.assertIsInstance(first_role, dict)
        first_role["description_bullets"] = [
            "Built recommendation ranking service.",
            "Improved retrieval relevance by 20%.",
            "   ",
        ]

        flattened = flatten_resume_profile(profile)
        self.assertIn(
            "- Stealth | Software Engineer | Nov 2022 - Present | "
            "Built recommendation ranking service.; Improved retrieval relevance by 20%.",
            flattened,
        )

    def test_update_rows_faiss_index_path_updates_only_selected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _create_resume_profiles_table(db_path)
            with sqlite3.connect(db_path) as conn:
                for idx, stem in enumerate(["one", "two", "three"], start=1):
                    conn.execute(
                        """
                        INSERT INTO resume_profiles
                        (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            idx,
                            stem,
                            f"/tmp/{stem}.pdf",
                            stem.title(),
                            json.dumps(_sample_profile(stem.title())),
                            "sha-1",
                            None if idx < 3 else "/tmp/already.faiss",
                            "2026-02-22T00:00:00+00:00",
                            "2026-02-22T00:00:00+00:00",
                        ),
                    )
                conn.commit()

            updated = update_rows_faiss_index_path(db_path, [1, 2], Path("/tmp/shared.faiss"))
            self.assertEqual(updated, 2)

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT id, faiss_index_path FROM resume_profiles ORDER BY id ASC"
                ).fetchall()

            self.assertEqual(rows[0][1], "/tmp/shared.faiss")
            self.assertEqual(rows[1][1], "/tmp/shared.faiss")
            self.assertEqual(rows[2][1], "/tmp/already.faiss")

    @patch(
        "flow.services.resume_indexer.generate_embeddings",
        return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
    )
    @patch(
        "flow.services.resume_indexer.write_shared_faiss_index",
        return_value=Path("/tmp/resume_profiles_20260222T000000Z.faiss"),
    )
    def test_backfill_missing_faiss_indexes_full_mode_overwrites_all_rows_with_shared_index_path(
        self, _: object, __: object
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _create_resume_profiles_table(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "avishek-bhatia",
                        "/tmp/avishek-bhatia.pdf",
                        "Avishek Bhatia",
                        json.dumps(_sample_profile("Avishek Bhatia")),
                        "sha-1",
                        None,
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        2,
                        "jane-doe",
                        "/tmp/jane-doe.pdf",
                        "Jane Doe",
                        json.dumps(_sample_profile("Jane Doe")),
                        "sha-1",
                        "/tmp/existing.faiss",
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.commit()

            summary = backfill_missing_faiss_indexes(
                db_path=db_path,
                index_dir=Path(temp_dir) / "faiss_indexes",
                model="text-embedding-3-large",
                batch_size=8,
                mode="full",
            )

            self.assertEqual(summary["mode"], "full")
            self.assertEqual(summary["selected_count"], 2)
            self.assertEqual(summary["pending_count"], 2)
            self.assertEqual(summary["processed_count"], 2)
            self.assertEqual(
                summary["index_path"],
                "/tmp/resume_profiles_20260222T000000Z.faiss",
            )
            self.assertEqual(summary["indexed_row_ids"], [1, 2])

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT id, faiss_index_path FROM resume_profiles ORDER BY id ASC"
                ).fetchall()
            self.assertEqual(rows[0][1], "/tmp/resume_profiles_20260222T000000Z.faiss")
            self.assertEqual(rows[1][1], "/tmp/resume_profiles_20260222T000000Z.faiss")

    @patch("flow.services.resume_indexer.generate_embeddings", return_value=[[0.1, 0.2, 0.3]])
    @patch(
        "flow.services.resume_indexer.write_shared_faiss_index",
        return_value=Path("/tmp/resume_profiles_20260222T000000Z.faiss"),
    )
    def test_backfill_missing_faiss_indexes_missing_mode_only_updates_null_rows(
        self, _: object, __: object
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _create_resume_profiles_table(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "avishek-bhatia",
                        "/tmp/avishek-bhatia.pdf",
                        "Avishek Bhatia",
                        json.dumps(_sample_profile("Avishek Bhatia")),
                        "sha-1",
                        None,
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        2,
                        "jane-doe",
                        "/tmp/jane-doe.pdf",
                        "Jane Doe",
                        json.dumps(_sample_profile("Jane Doe")),
                        "sha-1",
                        "/tmp/existing.faiss",
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.commit()

            summary = backfill_missing_faiss_indexes(
                db_path=db_path,
                index_dir=Path(temp_dir) / "faiss_indexes",
                model="text-embedding-3-large",
                batch_size=8,
                mode="missing",
            )

            self.assertEqual(summary["mode"], "missing")
            self.assertEqual(summary["selected_count"], 1)
            self.assertEqual(summary["processed_count"], 1)
            self.assertEqual(summary["indexed_row_ids"], [1])

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT id, faiss_index_path FROM resume_profiles ORDER BY id ASC"
                ).fetchall()
            self.assertEqual(rows[0][1], "/tmp/resume_profiles_20260222T000000Z.faiss")
            self.assertEqual(rows[1][1], "/tmp/existing.faiss")


class FlowWiringTests(unittest.TestCase):
    def test_resume_faiss_backfill_flow_calls_indexer_service(self) -> None:
        class_source = inspect.getsource(ResumeFaissBackfillFlow)
        self.assertIn("backfill_missing_faiss_indexes", class_source)
        self.assertIn("batch_size", class_source)
        self.assertIn("mode", class_source)


if __name__ == "__main__":
    unittest.main()
