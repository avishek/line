from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from metaflow import FlowSpec, Parameter, step

from flow.services.resume_indexer import flatten_resume_profile


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "outputs" / "resume_profiles.db"


def fetch_resume_profile_row_by_stem(*, db_path: Path, pdf_stem: str) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, pdf_stem, profile_json
            FROM resume_profiles
            WHERE pdf_stem = ?
            """,
            (pdf_stem,),
        ).fetchone()

    if row is None:
        raise LookupError(f"No resume_profiles row found for pdf_stem: {pdf_stem}")

    return {"id": int(row[0]), "pdf_stem": row[1], "profile_json": row[2]}


class ResumeProfileFlattenFlow(FlowSpec):
    pdf_stem = Parameter("pdf-stem", type=str, help="PDF stem to look up in resume_profiles.")
    db_path = Parameter("db-path", type=str, default=str(DEFAULT_DB_PATH))

    @step
    def start(self):
        load_dotenv()
        requested_pdf_stem = self.pdf_stem.strip()
        if not requested_pdf_stem:
            raise ValueError("--pdf-stem must be a non-empty string.")

        resolved_db_path = Path(self.db_path).expanduser().resolve()
        if not resolved_db_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {resolved_db_path}")

        row = fetch_resume_profile_row_by_stem(
            db_path=resolved_db_path,
            pdf_stem=requested_pdf_stem,
        )
        profile_json = row["profile_json"]
        if not isinstance(profile_json, str):
            raise ValueError(f"Row {row['id']} has non-string profile_json.")

        try:
            parsed_profile = json.loads(profile_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Row {row['id']} has invalid profile_json: {exc}") from exc

        if not isinstance(parsed_profile, dict):
            raise ValueError(f"Row {row['id']} profile_json must decode to an object.")

        flattened_profile = flatten_resume_profile(parsed_profile)
        if not flattened_profile.strip():
            raise ValueError(f"Row {row['id']} produced empty flattened resume text.")

        self.resolved_db_path = str(resolved_db_path)
        self.row_id = row["id"]
        self.matched_pdf_stem = row["pdf_stem"]
        self.flattened_profile = flattened_profile
        self.next(self.end)

    @step
    def end(self):
        print(f"SQLite input: {self.resolved_db_path}")
        print(f"Row id: {self.row_id}")
        print(f"PDF stem: {self.matched_pdf_stem}")
        print("Flattened resume profile:")
        print(self.flattened_profile)


def main():
    ResumeProfileFlattenFlow()


if __name__ == "__main__":
    main()
