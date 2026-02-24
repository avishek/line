from __future__ import annotations

import inspect
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flow.pipelines.resume_knn_search_flow import (  # noqa: E402
    ResumeKnnSearchFlow,
    _fetch_index_rows,
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


class ResumeKnnSearchFlowHelpersTests(unittest.TestCase):
    def test_fetch_index_rows_filters_and_orders_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _create_resume_profiles_table(db_path)

            index_a = Path(temp_dir) / "a.faiss"
            index_b = Path(temp_dir) / "b.faiss"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        2,
                        "two",
                        "/tmp/two.pdf",
                        "Two",
                        "{}",
                        "sha",
                        str(index_a),
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
                        1,
                        "one",
                        "/tmp/one.pdf",
                        "One",
                        "{}",
                        "sha",
                        str(index_a),
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
                        3,
                        "three",
                        "/tmp/three.pdf",
                        "Three",
                        "{}",
                        "sha",
                        str(index_b),
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.commit()

            rows = _fetch_index_rows(db_path=db_path, index_path=index_a)
            self.assertEqual([row["id"] for row in rows], [1, 2])
            self.assertEqual([row["pdf_stem"] for row in rows], ["one", "two"])

    def test_resolve_neighbors_maps_db_rows_from_faiss_positions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "resume_profiles.db"
            _create_resume_profiles_table(db_path)
            index_path = Path(temp_dir) / "shared.faiss"

            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO resume_profiles
                    (id, pdf_stem, source_pdf, full_name, profile_json, prompt_version_sha, faiss_index_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        10,
                        "alpha",
                        "/tmp/alpha.pdf",
                        "Alpha",
                        "{}",
                        "sha",
                        str(index_path),
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
                        20,
                        "beta",
                        "/tmp/beta.pdf",
                        "Beta",
                        "{}",
                        "sha",
                        str(index_path),
                        "2026-02-22T00:00:00+00:00",
                        "2026-02-22T00:00:00+00:00",
                    ),
                )
                conn.commit()

            state = SimpleNamespace(
                resolved_db_path=db_path,
                resolved_index_path=index_path,
                knn_indices=[1, 0, 99],
                knn_distances=[0.1, 0.2, 0.3],
                effective_k=3,
                end=object(),
            )
            state.next = lambda step: setattr(state, "_next_step", step)

            ResumeKnnSearchFlow.resolve_neighbors(state)

            self.assertEqual(len(state.neighbors), 3)
            self.assertEqual(state.neighbors[0]["id"], 20)
            self.assertEqual(state.neighbors[1]["id"], 10)
            self.assertNotIn("id", state.neighbors[2])
            self.assertEqual(state._next_step, state.end)


class FlowWiringTests(unittest.TestCase):
    def test_resume_knn_search_flow_uses_faiss_and_sqlite_mapping(self) -> None:
        class_source = inspect.getsource(ResumeKnnSearchFlow)
        self.assertIn("faiss.read_index", class_source)
        self.assertIn("_fetch_index_rows", class_source)
        self.assertIn("index.search", class_source)


if __name__ == "__main__":
    unittest.main()
