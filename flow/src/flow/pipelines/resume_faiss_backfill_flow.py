from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from metaflow import FlowSpec, Parameter, step

from flow.services.resume_indexer import backfill_missing_faiss_indexes


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "outputs" / "resume_profiles.db"
DEFAULT_INDEX_DIR = PROJECT_ROOT / "outputs" / "faiss_indexes"


class ResumeFaissBackfillFlow(FlowSpec):
    db_path = Parameter("db-path", type=str, default=str(DEFAULT_DB_PATH))
    index_dir = Parameter("index-dir", type=str, default=str(DEFAULT_INDEX_DIR))
    model = Parameter("model", type=str, default="text-embedding-3-large")
    batch_size = Parameter("batch-size", type=int, default=32)
    mode = Parameter("mode", type=str, default="full")

    @step
    def start(self):
        load_dotenv()
        normalized_mode = self.mode.strip().lower()
        if normalized_mode not in {"full", "missing"}:
            raise ValueError("--mode must be either 'full' or 'missing'.")

        resolved_db_path = Path(self.db_path).expanduser().resolve()
        if not resolved_db_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {resolved_db_path}")

        resolved_index_dir = Path(self.index_dir).expanduser().resolve()
        self.summary = backfill_missing_faiss_indexes(
            db_path=resolved_db_path,
            index_dir=resolved_index_dir,
            model=self.model,
            batch_size=self.batch_size,
            mode=normalized_mode,
        )
        self.resolved_db_path = str(resolved_db_path)
        self.resolved_index_dir = str(resolved_index_dir)
        self.next(self.end)

    @step
    def end(self):
        print(f"SQLite input: {self.resolved_db_path}")
        print(f"Index output dir: {self.resolved_index_dir}")
        print(f"Backfill mode: {self.summary['mode']}")
        print(f"Rows selected: {self.summary['selected_count']}")
        print(f"Rows updated: {self.summary['processed_count']}")
        if self.summary["index_path"]:
            print(f"Shared FAISS index: {self.summary['index_path']}")
        else:
            print("No FAISS index generated (no rows selected).")


def main():
    ResumeFaissBackfillFlow()


if __name__ == "__main__":
    main()
