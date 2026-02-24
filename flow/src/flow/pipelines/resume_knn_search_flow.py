from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from metaflow import FlowSpec, Parameter, step

from flow.services.resume_extractor import extract_resume_profile_from_pdf
from flow.services.resume_indexer import flatten_resume_profile, generate_embeddings


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "outputs" / "resume_profiles.db"
DEFAULT_INDEX_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "faiss_indexes"
    / "resume_profiles_20260223T071759Z.faiss"
)


def _fetch_index_rows(db_path: Path, index_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, pdf_stem, full_name
            FROM resume_profiles
            WHERE faiss_index_path = ?
            ORDER BY id ASC
            """,
            (str(index_path),),
        ).fetchall()
    return [
        {"id": int(row[0]), "pdf_stem": row[1], "full_name": row[2]}
        for row in rows
    ]


class ResumeKnnSearchFlow(FlowSpec):
    pdf_path = Parameter("pdf-path", type=str, help="Path to source resume PDF.")
    top_n = Parameter("top-n", type=int, help="Number of nearest neighbors to return.")
    index_path = Parameter("index-path", type=str, default=str(DEFAULT_INDEX_PATH))
    db_path = Parameter("db-path", type=str, default=str(DEFAULT_DB_PATH))
    extraction_model = Parameter("extraction-model", type=str, default="gpt-5.1")
    embedding_model = Parameter("embedding-model", type=str, default="text-embedding-3-large")

    @step
    def start(self):
        load_dotenv()
        self.source_pdf = Path(self.pdf_path).expanduser().resolve()
        if not self.source_pdf.exists():
            raise FileNotFoundError(f"PDF file not found: {self.source_pdf}")
        if self.source_pdf.suffix.lower() != ".pdf":
            raise ValueError(f"Input file must be a PDF: {self.source_pdf}")

        self.resolved_index_path = Path(self.index_path).expanduser().resolve()
        if not self.resolved_index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {self.resolved_index_path}")

        self.resolved_db_path = Path(self.db_path).expanduser().resolve()
        if self.top_n <= 0:
            raise ValueError("--top-n must be greater than 0.")

        self.next(self.extract_and_embed)

    @step
    def extract_and_embed(self):
        load_dotenv()
        self.resume_profile = extract_resume_profile_from_pdf(
            self.source_pdf,
            model=self.extraction_model,
        )
        self.flattened_profile = flatten_resume_profile(self.resume_profile)
        if not self.flattened_profile.strip():
            raise ValueError("Flattened resume profile is empty.")

        embeddings = generate_embeddings(
            flattened_rows=[{"flattened_text": self.flattened_profile}],
            model=self.embedding_model,
            batch_size=1,
        )
        self.query_embedding = embeddings[0]

        print("Flattened resume profile:")
        print(self.flattened_profile)
        self.next(self.search)

    @step
    def search(self):
        try:
            import faiss
        except ImportError as exc:
            raise ImportError(
                "faiss is not installed. Install `faiss-cpu` to run kNN search."
            ) from exc

        try:
            import numpy as np
        except ImportError as exc:
            raise ImportError("numpy is required to run kNN search.") from exc

        index = faiss.read_index(str(self.resolved_index_path))
        if index.ntotal <= 0:
            raise ValueError(f"FAISS index is empty: {self.resolved_index_path}")

        query_vector = np.array([self.query_embedding], dtype="float32")
        if query_vector.shape[1] != index.d:
            raise ValueError(
                f"Embedding dimension mismatch: query has {query_vector.shape[1]}, "
                f"index expects {index.d}."
            )

        self.effective_k = min(self.top_n, index.ntotal)
        distances, indices = index.search(query_vector, self.effective_k)
        self.knn_distances = [float(value) for value in distances[0].tolist()]
        self.knn_indices = [int(value) for value in indices[0].tolist()]
        self.next(self.resolve_neighbors)

    @step
    def resolve_neighbors(self):
        mapped_rows: list[dict[str, Any]] = []
        if self.resolved_db_path.exists():
            mapped_rows = _fetch_index_rows(
                db_path=self.resolved_db_path,
                index_path=self.resolved_index_path,
            )

        self.neighbors: list[dict[str, Any]] = []
        for rank, (faiss_idx, distance) in enumerate(
            zip(self.knn_indices, self.knn_distances),
            start=1,
        ):
            row_data: dict[str, Any] = {
                "rank": rank,
                "distance": distance,
                "faiss_index_position": faiss_idx,
            }
            if 0 <= faiss_idx < len(mapped_rows):
                row_data.update(mapped_rows[faiss_idx])
            self.neighbors.append(row_data)

        print()
        print(f"Top {self.effective_k} nearest neighbors:")
        for neighbor in self.neighbors:
            base = (
                f"[{neighbor['rank']}] distance={neighbor['distance']:.6f} "
                f"faiss_index_position={neighbor['faiss_index_position']}"
            )
            if "id" in neighbor:
                print(
                    f"{base} id={neighbor['id']} "
                    f"pdf_stem={neighbor.get('pdf_stem')} "
                    f"full_name={neighbor.get('full_name')}"
                )
            else:
                print(base)

        self.next(self.end)

    @step
    def end(self):
        print()
        print(f"Query PDF: {self.source_pdf}")
        print(f"FAISS index: {self.resolved_index_path}")
        print(f"SQLite mapping DB: {self.resolved_db_path}")
        print(f"Requested top_n: {self.top_n}")
        print(f"Returned neighbors: {len(self.neighbors)}")


def main():
    ResumeKnnSearchFlow()


if __name__ == "__main__":
    main()
