from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_rows_for_faiss_backfill(
    db_path: Path, *, mode: str = "full"
) -> list[dict[str, Any]]:
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"full", "missing"}:
        raise ValueError("mode must be either 'full' or 'missing'.")

    where_clause = ""
    if normalized_mode == "missing":
        where_clause = "WHERE faiss_index_path IS NULL"

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, pdf_stem, profile_json
            FROM resume_profiles
            {where_clause}
            ORDER BY id ASC
            """
        ).fetchall()
    return [{"id": row[0], "pdf_stem": row[1], "profile_json": row[2]} for row in rows]


def fetch_rows_missing_faiss_index(db_path: Path) -> list[dict[str, Any]]:
    return fetch_rows_for_faiss_backfill(db_path, mode="missing")


def _safe_str(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        normalized = _safe_str(item)
        if normalized:
            values.append(normalized)
    return values


def flatten_resume_profile(profile: dict[str, Any]) -> str:
    lines: list[str] = []
    personal_info = profile.get("personal_information")
    if isinstance(personal_info, dict):
        full_name = _safe_str(personal_info.get("full_name"))
        if full_name:
            lines.append(f"Full Name: {full_name}")

        headline = _safe_str(personal_info.get("headline"))
        if headline:
            lines.append(f"Headline: {headline}")

    skills_obj = profile.get("skills")
    if isinstance(skills_obj, dict):
        skills = _coerce_string_list(skills_obj.get("top_skills"))
        if skills:
            lines.append(f"Skills: {', '.join(skills)}")

    experience = profile.get("experience")
    if isinstance(experience, list):
        experience_lines: list[str] = []
        for item in experience:
            if not isinstance(item, dict):
                continue
            company = _safe_str(item.get("company"))
            title = _safe_str(item.get("title"))
            start_date = _safe_str(item.get("start_date"))
            end_date = _safe_str(item.get("end_date"))

            parts: list[str] = []
            if company:
                parts.append(company)
            if title:
                parts.append(title)
            if start_date or end_date:
                date_range = f"{start_date or 'Unknown'} - {end_date or 'Present'}"
                parts.append(date_range)
            description_bullets = _coerce_string_list(item.get("description_bullets"))
            if description_bullets:
                parts.append("; ".join(description_bullets))
            if parts:
                experience_lines.append(f"- {' | '.join(parts)}")

        if experience_lines:
            lines.append("Experience:")
            lines.extend(experience_lines)

    education = profile.get("education")
    if isinstance(education, list):
        education_lines: list[str] = []
        for item in education:
            if not isinstance(item, dict):
                continue
            institution = _safe_str(item.get("institution"))
            degree = _safe_str(item.get("degree"))
            field = _safe_str(item.get("field_of_study"))
            start_year = _safe_str(item.get("start_year"))
            end_year = _safe_str(item.get("end_year"))

            parts: list[str] = []
            if institution:
                parts.append(institution)
            if degree and field:
                parts.append(f"{degree} in {field}")
            elif degree:
                parts.append(degree)
            elif field:
                parts.append(field)
            if start_year or end_year:
                parts.append(f"{start_year or 'Unknown'} - {end_year or 'Present'}")
            if parts:
                education_lines.append(f"- {' | '.join(parts)}")

        if education_lines:
            lines.append("Education:")
            lines.extend(education_lines)

    return "\n".join(lines)


def build_flattened_text_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened_rows: list[dict[str, Any]] = []
    for row in rows:
        profile_json = row.get("profile_json")
        if not isinstance(profile_json, str):
            raise ValueError(f"Row {row.get('id')} has non-string profile_json.")

        try:
            parsed = json.loads(profile_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Row {row.get('id')} has invalid profile_json: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"Row {row.get('id')} profile_json must decode to an object.")

        flattened_text = flatten_resume_profile(parsed)
        if not flattened_text.strip():
            raise ValueError(f"Row {row.get('id')} produced empty flattened resume text.")

        flattened_rows.append(
            {
                "id": row["id"],
                "pdf_stem": row["pdf_stem"],
                "flattened_text": flattened_text,
            }
        )
    return flattened_rows


def generate_embeddings(
    *,
    flattened_rows: list[dict[str, Any]],
    model: str,
    batch_size: int,
) -> list[list[float]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set.")

    texts = [row["flattened_text"] for row in flattened_rows]
    client = OpenAI(api_key=api_key)
    embeddings: list[list[float]] = []

    for index in range(0, len(texts), batch_size):
        batch = texts[index : index + batch_size]
        response = client.embeddings.create(model=model, input=batch)
        response_data = sorted(response.data, key=lambda item: item.index)
        embeddings.extend(item.embedding for item in response_data)

    if len(embeddings) != len(flattened_rows):
        raise ValueError("Embedding count did not match flattened row count.")

    return embeddings


def write_shared_faiss_index(embeddings: list[list[float]], index_dir: Path) -> Path:
    if not embeddings:
        raise ValueError("No embeddings provided; cannot build FAISS index.")

    vector_size = len(embeddings[0])
    if vector_size == 0:
        raise ValueError("Embedding vector size cannot be zero.")

    for idx, embedding in enumerate(embeddings):
        if len(embedding) != vector_size:
            raise ValueError(
                f"Embedding at position {idx} has dimension {len(embedding)}; "
                f"expected {vector_size}."
            )

    try:
        import faiss
    except ImportError as exc:
        raise ImportError(
            "faiss is not installed. Install `faiss-cpu` to build local indexes."
        ) from exc

    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError("numpy is required to build FAISS indexes.") from exc

    index_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    index_path = index_dir / f"resume_profiles_{timestamp}.faiss"

    vectors = np.array(embeddings, dtype="float32")
    index = faiss.IndexFlatL2(vector_size)
    index.add(vectors)
    faiss.write_index(index, str(index_path))
    return index_path


def update_rows_faiss_index_path(db_path: Path, row_ids: list[int], index_path: Path) -> int:
    if not row_ids:
        return 0

    now = _utc_now_iso()
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        conn.executemany(
            """
            UPDATE resume_profiles
            SET faiss_index_path = ?, updated_at = ?
            WHERE id = ?
            """,
            [(str(index_path), now, row_id) for row_id in row_ids],
        )
        conn.commit()
    return len(row_ids)


def backfill_missing_faiss_indexes(
    *,
    db_path: Path,
    index_dir: Path,
    model: str,
    batch_size: int,
    mode: str = "full",
) -> dict[str, Any]:
    selected_rows = fetch_rows_for_faiss_backfill(db_path, mode=mode)
    normalized_mode = mode.strip().lower()
    if not selected_rows:
        return {
            "mode": normalized_mode,
            "selected_count": 0,
            "pending_count": 0,
            "processed_count": 0,
            "index_path": None,
            "indexed_row_ids": [],
        }

    flattened_rows = build_flattened_text_rows(selected_rows)
    embeddings = generate_embeddings(
        flattened_rows=flattened_rows,
        model=model,
        batch_size=batch_size,
    )
    index_path = write_shared_faiss_index(embeddings, index_dir)
    row_ids = [int(row["id"]) for row in flattened_rows]
    processed_count = update_rows_faiss_index_path(db_path, row_ids, index_path)
    return {
        "mode": normalized_mode,
        "selected_count": len(selected_rows),
        "pending_count": len(selected_rows),
        "processed_count": processed_count,
        "index_path": str(index_path),
        "indexed_row_ids": row_ids,
    }
