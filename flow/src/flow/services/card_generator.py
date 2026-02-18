from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from flow.schemas.competency_card import CompetencyCard


SYSTEM_PROMPT = """You create competency cards from candidate/person evidence.
Return valid JSON only, no markdown or commentary.
Use this schema strictly. Do not add or remove top-level fields.
When evidence is missing, set nullable fields to null and use low confidence."""


def _build_user_prompt(extracted_text: str, person_payload: dict[str, Any]) -> str:
    schema = CompetencyCard.model_json_schema()
    return (
        "Build a Competency Card JSON object from the extracted PDF text.\n"
        "Respect all enum constraints and required fields.\n"
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
            {"role": "system", "content": SYSTEM_PROMPT},
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

