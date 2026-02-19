# Flow Pipelines

This project bootstraps local Metaflow pipelines using `uv` + Python 3.

## Pipeline 1: Competency Card from PDF

`CompetencyCardFlow` performs:
1. PDF text extraction
2. Competency Card generation via OpenAI
3. Schema validation with Pydantic
4. JSON persistence to `outputs/`

## Prerequisites

- Python 3.11+ (or newer)
- `uv` installed
- OpenAI API key

## Setup

```bash
cd flow
uv venv
source .venv/bin/activate
uv sync
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`.

## Test PDF extraction locally (no LLM call)

Use the extractor directly to validate your PDF text is readable before running the flow:

```bash
uv --directory flow run python -m flow.services.pdf_extractor /absolute/path/to/input.pdf
```

## Run the flow locally

```bash
uv run python -m flow.pipelines.competency_card_flow run \
  --pdf-path /absolute/path/to/input.pdf \
  --person-id person_123 \
  --person-type candidate \
  --role-family IC \
  --level L5 \
  --current-title "Senior Software Engineer" \
  --primary-org Engineering \
  --tenure-months 18 \
  --start-date 2024-01-01 \
  --end-date 2025-12-31 \
  --rubric-name "Engineering Competency Rubric" \
  --rubric-version v1 \
  --output-dir outputs
```

Optional model override:

```bash
uv run python -m flow.pipelines.competency_card_flow run \
  --pdf-path /absolute/path/to/input.pdf \
  --person-id person_123 \
  --model gpt-4o-mini
```

## Output

The flow writes one JSON file to the configured output directory:

- `<person_id>_<pdf_stem>_competency_card.json`

## Notes

- If PDF text extraction fails (no readable text), the flow exits with an error.
- If OpenAI returns invalid JSON or schema-incompatible data, validation fails with details.
