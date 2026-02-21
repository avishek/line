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
  --output-dir outputs
```

Optional overrides:

```bash
uv run python -m flow.pipelines.competency_card_flow run \
  --pdf-path /absolute/path/to/input.pdf \
  --person-id person_123 \
  --person-type candidate \
  --role-family IC \
  --level "Senior" \
  --current-title "Senior Software Engineer" \
  --rubric-name "Engineering Competency Rubric" \
  --model gpt-4o-mini
```

## Run the batch flow locally

Use this variant to process all top-level `*.pdf` files under a folder:

```bash
uv run python -m flow.pipelines.competency_card_batch_flow run \
  --input-dir /absolute/path/to/input-folder \
  --output-dir outputs
```

Behavior:

- Scans only PDFs directly inside `--input-dir` (non-recursive).
- Continues processing even if one PDF fails.
- Prints a final summary with successful and failed files.

Optional overrides are identical to the single-PDF flow (`--person-id`, `--person-type`, `--role-family`, `--level`, `--current-title`, `--rubric-name`, `--model`).

## Person attribute derivation

The flow now derives person attributes from resume text by default:

- `current_title`: inferred from title-like lines in the resume.
- `level`: inferred from title tokens such as `Junior`, `Senior`, `Staff`, `Principal`.
- `role_family`: mapped from inferred title to one of `IC|EM|PM|TPM|Other`.
- `person_id`: derived from candidate name when detectable, otherwise from PDF file name.

Attributes that are not reliably derivable from resume alone:

- `person.type` (`internal` or `candidate`) without external context.

When CLI overrides are provided, merge precedence is:

1. Explicit CLI value
2. Derived value from resume
3. Safe fallback (`person_id=unknown_person`, `person.type=candidate`, `role_family=Other`)

## Output

The flow writes one JSON file to the configured output directory:

- Single flow: `<person_id>_competency_card.json`
- Batch flow: `<person_id>_<pdf_stem>_competency_card.json` (or
  `<person_id>_competency_card.json` when `pdf_stem` matches `person_id`)
- Schema contract: `schema_version: "1.0"` with competency dimensions:
  `velocity`, `ownership`, `expertise`, `qed`, `economy`, `code_quality`,
  `debugging`, `reliability`, `teaching`
- Each `competency_scores.dimensions.*.evidence` entry is an object:
  `{ "text": "...", "evidence_type": "..." }`

## Prompt source

- System prompt file: `src/flow/prompts/agent.md`
- `flow.services.card_generator` loads this file at runtime as the system message.
- To change rubric behavior, update `agent.md` (no code changes required unless prompt assembly changes).

## Notes

- If PDF text extraction fails (no readable text), the flow exits with an error.
- If OpenAI returns invalid JSON or schema-incompatible data, validation fails with details.
