from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from metaflow import FlowSpec, Parameter, step

from flow.services.resume_extractor import (
    extract_resume_profile_from_pdf,
    get_resume_parser_prompt_sha,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESUME_SQLITE_PATH = PROJECT_ROOT / "outputs" / "resume_profiles.db"
DEBUG_LOG_PATH = Path("/Users/avishek.bhatia/Documents/line/.cursor/debug-900b31.log")
DEBUG_SESSION_ID = "900b31"


def _debug_log(*, run_id: str, hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    payload = {
        "sessionId": DEBUG_SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload, default=str))
            log_file.write("\n")
    except Exception:
        pass


def _discover_top_level_pdfs(input_root: Path) -> list[Path]:
    return sorted(path for path in input_root.glob("*.pdf") if path.is_file())


def _make_output_filename(source_pdf: Path) -> str:
    return f"{source_pdf.stem}_resume.json"


def _persist_resume_profile(profile: dict[str, Any], output_dir: Path, source_pdf: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _make_output_filename(source_pdf)
    with output_path.open("w", encoding="utf-8") as file_obj:
        json.dump(profile, file_obj, indent=2)
        file_obj.write("\n")
    return output_path


def _ensure_resume_profiles_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resume_profiles (
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
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(resume_profiles)").fetchall()
        }
        if "faiss_index_path" not in existing_columns:
            conn.execute("ALTER TABLE resume_profiles ADD COLUMN faiss_index_path TEXT")
        conn.commit()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_full_name(profile: dict[str, Any]) -> str | None:
    personal_info = profile.get("personal_information")
    if not isinstance(personal_info, dict):
        return None
    full_name = personal_info.get("full_name")
    if isinstance(full_name, str) and full_name.strip():
        return full_name
    return None


def _upsert_resume_profile_row(
    *,
    db_path: Path,
    source_pdf: Path,
    profile: dict[str, Any],
    prompt_version_sha: str,
) -> None:
    now = _utc_now_iso()
    payload = json.dumps(profile, ensure_ascii=False)
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        conn.execute(
            """
            INSERT INTO resume_profiles (
                pdf_stem,
                source_pdf,
                full_name,
                profile_json,
                prompt_version_sha,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pdf_stem) DO UPDATE SET
                source_pdf = excluded.source_pdf,
                full_name = excluded.full_name,
                profile_json = excluded.profile_json,
                prompt_version_sha = excluded.prompt_version_sha,
                updated_at = excluded.updated_at
            """,
            (
                source_pdf.stem,
                str(source_pdf),
                _get_full_name(profile),
                payload,
                prompt_version_sha,
                now,
                now,
            ),
        )
        conn.commit()


def _summarize_results(results: list[dict[str, Any]]) -> tuple[int, int, list[dict[str, Any]]]:
    failed_results = [result for result in results if not result.get("success", False)]
    success_count = len(results) - len(failed_results)
    failure_count = len(failed_results)
    return success_count, failure_count, failed_results


class ResumeExtractionBatchFlow(FlowSpec):
    input_dir = Parameter("input-dir", type=str, help="Path to source PDF folder.")
    output_dir = Parameter("output-dir", type=str, default="outputs")
    model = Parameter("model", type=str, default="gpt-5.1")

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
        self.sqlite_db_path = str(RESUME_SQLITE_PATH.resolve())
        _ensure_resume_profiles_table(Path(self.sqlite_db_path))
        self.prompt_version_sha = get_resume_parser_prompt_sha()
        # region agent log
        _debug_log(
            run_id="pre-fix",
            hypothesis_id="H1",
            location="resume_extraction_batch_flow.py:start",
            message="Initialized sqlite and prompt sha in start step",
            data={
                "has_sqlite_db_path": hasattr(self, "sqlite_db_path"),
                "has_prompt_version_sha": hasattr(self, "prompt_version_sha"),
                "db_path_name": Path(self.sqlite_db_path).name,
            },
        )
        # endregion

        pdf_paths = _discover_top_level_pdfs(input_root)
        if not pdf_paths:
            raise FileNotFoundError(f"No PDF files found in: {input_root}")

        self.pdf_paths = [str(path) for path in pdf_paths]
        self.next(self.process_pdf, foreach="pdf_paths")

    @step
    def process_pdf(self):
        load_dotenv()
        source_pdf = Path(self.input).expanduser().resolve()
        self.result = {
            "source_pdf": str(source_pdf),
            "output_path": None,
            "success": False,
            "error_message": None,
        }

        try:
            extracted_profile = extract_resume_profile_from_pdf(source_pdf, model=self.model)
            output_path = _persist_resume_profile(
                profile=extracted_profile,
                output_dir=self.output_root,
                source_pdf=source_pdf,
            )
            _upsert_resume_profile_row(
                db_path=Path(self.sqlite_db_path),
                source_pdf=source_pdf,
                profile=extracted_profile,
                prompt_version_sha=self.prompt_version_sha,
            )
            self.result["output_path"] = str(output_path)
            self.result["sqlite_db_path"] = self.sqlite_db_path
            self.result["success"] = True
        except Exception as exc:  # noqa: BLE001
            self.result["error_message"] = f"{type(exc).__name__}: {exc}"

        self.next(self.join)

    @step
    def join(self, inputs):
        input_list = list(inputs)
        first_input = input_list[0] if input_list else None
        # region agent log
        _debug_log(
            run_id="pre-fix",
            hypothesis_id="H2",
            location="resume_extraction_batch_flow.py:join",
            message="Join step artifact visibility check",
            data={
                "join_has_sqlite_db_path": hasattr(self, "sqlite_db_path"),
                "input_count": len(input_list),
                "first_input_has_sqlite_db_path": first_input is not None
                and hasattr(first_input, "sqlite_db_path"),
                "first_input_has_prompt_version_sha": first_input is not None
                and hasattr(first_input, "prompt_version_sha"),
            },
        )
        # endregion
        if first_input is not None:
            self.sqlite_db_path = getattr(
                first_input,
                "sqlite_db_path",
                str(RESUME_SQLITE_PATH.resolve()),
            )
            self.prompt_version_sha = getattr(first_input, "prompt_version_sha", "unknown")
        else:
            self.sqlite_db_path = str(RESUME_SQLITE_PATH.resolve())
            self.prompt_version_sha = "unknown"

        self.results = [input_obj.result for input_obj in input_list]
        (
            self.success_count,
            self.failure_count,
            self.failed_results,
        ) = _summarize_results(self.results)
        self.generated_on = date.today().isoformat()
        self.next(self.end)

    @step
    def end(self):
        # region agent log
        _debug_log(
            run_id="pre-fix",
            hypothesis_id="H3",
            location="resume_extraction_batch_flow.py:end",
            message="End step pre-print artifact visibility",
            data={
                "end_has_sqlite_db_path": hasattr(self, "sqlite_db_path"),
                "result_count": len(self.results),
            },
        )
        # endregion
        print(f"Batch run completed on: {self.generated_on}")
        print(f"Total PDFs processed: {len(self.results)}")
        print(f"Successful resumes: {self.success_count}")
        print(f"Failures: {self.failure_count}")
        print(f"SQLite output: {self.sqlite_db_path}")
        if self.failed_results:
            print("Failed files:")
            for failed in self.failed_results:
                print(f"- {failed['source_pdf']}: {failed['error_message']}")


def main():
    ResumeExtractionBatchFlow()


if __name__ == "__main__":
    main()
