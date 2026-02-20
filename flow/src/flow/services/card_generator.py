from __future__ import annotations

import json
import os
from importlib.resources import files
from typing import Any

from openai import OpenAI

from flow.schemas.competency_card import CompetencyCard

def _load_system_prompt() -> str:
    prompt_path = files("flow").joinpath("prompts", "agent.md")
    try:
        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "Missing prompt file 'flow/prompts/agent.md'. Ensure it is packaged and installed."
        ) from exc
    if not prompt_text:
        raise ValueError("Prompt file 'flow/prompts/agent.md' is empty.")
    return prompt_text


def _build_user_prompt(extracted_text: str, person_payload: dict[str, Any]) -> str:
    schema = CompetencyCard.model_json_schema()
    return (
        "Build a Competency Card JSON object from the extracted PDF text.\n"
        "Respect all enum constraints and required fields.\n"
        "Do not invent extra keys. Keep output strictly aligned to the provided schema.\n"
        "For each competency dimension, evidence must be an array of objects "
        "with {text, evidence_type}. Never return evidence as string arrays.\n"
        f"Use this person payload as input context:\n{json.dumps(person_payload, indent=2)}\n\n"
        f"JSON schema:\n{json.dumps(schema, indent=2)}\n\n"
        f"Extracted PDF text:\n{extracted_text}\n"
    )


def generate_competency_card(
    extracted_text: str,
    person_payload: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set.")

    selected_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=selected_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _load_system_prompt()},
            {"role": "user", "content": _build_user_prompt(extracted_text, person_payload)},
        ],
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("OpenAI response did not include content.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI response was not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("OpenAI response JSON must be an object.")

    return parsed

