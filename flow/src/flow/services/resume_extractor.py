from __future__ import annotations

import base64
import json
import os
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any

from openai import OpenAI

from flow.schemas.resume_profile import ResumeProfile


def _load_resume_prompt() -> str:
    prompt_path = files("flow").joinpath("prompts", "resume_parser.md")
    try:
        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "Missing prompt file 'flow/prompts/resume_parser.md'. "
            "Ensure it is packaged and installed."
        ) from exc
    if not prompt_text:
        raise ValueError("Prompt file 'flow/prompts/resume_parser.md' is empty.")
    return prompt_text


def _find_git_repo_root(start_path: Path) -> Path | None:
    path = start_path.resolve()
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def get_resume_parser_prompt_sha() -> str:
    prompt_resource = files("flow").joinpath("prompts", "resume_parser.md")
    prompt_path = Path(str(prompt_resource)).resolve()
    repo_root = _find_git_repo_root(prompt_path)
    if repo_root is None:
        return "unknown"

    try:
        rel_prompt_path = prompt_path.relative_to(repo_root).as_posix()
    except ValueError:
        return "unknown"

    blob_sha_cmd = ["git", "-C", str(repo_root), "rev-parse", f"HEAD:{rel_prompt_path}"]
    blob_sha_result = subprocess.run(
        blob_sha_cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    blob_sha = blob_sha_result.stdout.strip()
    if blob_sha_result.returncode == 0 and blob_sha:
        return blob_sha

    head_sha_cmd = ["git", "-C", str(repo_root), "rev-parse", "HEAD"]
    head_sha_result = subprocess.run(
        head_sha_cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    head_sha = head_sha_result.stdout.strip()
    if head_sha_result.returncode == 0 and head_sha:
        return head_sha
    return "unknown"


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = getattr(response, "output", None)
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            content = getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for entry in content:
                text_value = getattr(entry, "text", None)
                if isinstance(text_value, str) and text_value.strip():
                    chunks.append(text_value)
        if chunks:
            return "\n".join(chunks)

    raise ValueError("OpenAI response did not include parseable text content.")


def extract_resume_profile_from_pdf(pdf_path: str | Path, model: str = "gpt-5.1") -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set.")

    source_path = Path(pdf_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"PDF file not found: {source_path}")
    if source_path.suffix.lower() != ".pdf":
        raise ValueError(f"Input file must be a PDF: {source_path}")

    pdf_bytes = source_path.read_bytes()
    if not pdf_bytes:
        raise ValueError(f"PDF file is empty: {source_path}")

    client = OpenAI(api_key=api_key)
    encoded_pdf = base64.b64encode(pdf_bytes).decode("ascii")

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": _load_resume_prompt()}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Parse this resume PDF and return strict JSON only."},
                    {
                        "type": "input_file",
                        "filename": source_path.name,
                        "file_data": f"data:application/pdf;base64,{encoded_pdf}",
                    },
                ],
            },
        ],
    )

    response_text = _extract_response_text(response)
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI response was not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("OpenAI response JSON must be an object.")

    validated = ResumeProfile.model_validate(parsed)
    return validated.model_dump(mode="json")
