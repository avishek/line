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
  --name "Avishek Bhatia" \
  --linkedin-profile-url "www.linkedin.com/in/avishekbhatia/" \
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

Optional overrides are identical to the single-PDF flow (`--person-id`, `--person-type`, `--role-family`, `--level`, `--current-title`, `--name`, `--linkedin-profile-url`, `--rubric-name`, `--model`).

## Run the resume extraction flow locally

Use this pipeline to parse each top-level PDF in an input directory into strict resume JSON output:

```bash
uv run python -m flow.pipelines.resume_extraction_batch_flow run \
  --input-dir /absolute/path/to/resume-folder \
  --output-dir outputs/resume_json
```

Optional model override:

```bash
uv run python -m flow.pipelines.resume_extraction_batch_flow run \
  --input-dir /absolute/path/to/resume-folder \
  --output-dir outputs/resume_json \
  --model gpt-5.1
```

Behavior:

- Scans only PDFs directly inside `--input-dir` (non-recursive).
- Sends each PDF directly to OpenAI for structured extraction.
- Persists one file per input PDF as `<pdf_stem>_resume.json`.
- Persists each extracted profile to SQLite at `flow/outputs/resume_profiles.db`.
- Upserts rows by `pdf_stem` with metadata:
  `full_name`, `created_at`, `updated_at`, `prompt_version_sha`, `faiss_index_path`.
- `faiss_index_path` is nullable by default and is intended to be populated by
  a separate FAISS indexing workflow.
- Continues processing remaining files if any file fails.

## Run the resume FAISS backfill flow locally

Use this pipeline to create one shared FAISS `IndexFlatL2` file for all
`resume_profiles` rows and write that shared index path back into SQLite:

```bash
# from repo root
uv --directory flow run python -m flow.pipelines.resume_faiss_backfill_flow run
```

```bash
# or from inside flow/
uv run python -m flow.pipelines.resume_faiss_backfill_flow run
```

Optional overrides:

```bash
uv run python -m flow.pipelines.resume_faiss_backfill_flow run \
  --db-path outputs/resume_profiles.db \
  --index-dir outputs/faiss_indexes \
  --mode missing \
  --model text-embedding-3-large \
  --batch-size 32
```

Behavior:

- Defaults to `--mode full`, selecting all rows in `resume_profiles`.
- Supports `--mode missing` to select only rows where `faiss_index_path IS NULL`.
- Flattens each `profile_json` into deterministic text blocks.
- Calls OpenAI embeddings API in batches.
- Builds a new shared local `faiss.IndexFlatL2` file for each run.
- Updates all selected rows with that shared index file path.
- Exits cleanly with no index write if there are no selected rows.

## Run the single-resume FAISS query flow locally

Use this pipeline to parse one resume PDF, flatten and embed it, print both values,
and run kNN search against an existing FAISS index:

```bash
uv run python -m flow.pipelines.resume_knn_search_flow run \
  --pdf-path /absolute/path/to/resume.pdf \
  --top-n 5
```

Optional overrides:

```bash
uv run python -m flow.pipelines.resume_knn_search_flow run \
  --pdf-path /absolute/path/to/resume.pdf \
  --top-n 5 \
  --index-path /Users/avishek.bhatia/Documents/line/flow/outputs/faiss_indexes/resume_profiles_20260223T071759Z.faiss \
  --db-path outputs/resume_profiles.db \
  --extraction-model gpt-5.1 \
  --embedding-model text-embedding-3-large
```

Behavior:

- Extracts structured JSON from the given PDF using the resume parser prompt.
- Flattens the profile with `flatten_resume_profile`.
- Generates query embeddings with `generate_embeddings`.
- Prints flattened profile text (embeddings are generated internally for search).
- Runs `IndexFlatL2` kNN search against the specified FAISS index.
- Resolves neighbor metadata (`id`, `pdf_stem`, `full_name`) from SQLite when available.

## Run the single-resume flatten-from-SQLite flow locally

Use this pipeline to fetch one row from `resume_profiles` by `pdf_stem`,
flatten the stored `profile_json`, and print the flattened profile:

```bash
uv run python -m flow.pipelines.resume_profile_flatten_flow run \
  --pdf-stem jane-doe
```

Optional override:

```bash
uv run python -m flow.pipelines.resume_profile_flatten_flow run \
  --pdf-stem jane-doe \
  --db-path outputs/resume_profiles.db
```

Behavior:

- Resolves SQLite path from `--db-path` and fails fast if it does not exist.
- Looks up exactly one `resume_profiles` row for the provided `pdf_stem`.
- JSON-decodes `profile_json` and validates it as an object payload.
- Flattens the profile with `flatten_resume_profile`.
- Prints SQLite path, row metadata, and flattened profile text.

## Person attribute derivation

The flow now derives person attributes from resume text by default:

- `current_title`: inferred from title-like lines in the resume.
- `level`: inferred from title tokens such as `Junior`, `Senior`, `Staff`, `Principal`.
- `role_family`: mapped from inferred title to one of `IC|EM|PM|TPM|Other`.
- `name`: inferred from top resume lines when detectable.
- `linkedin_profile_url`: inferred from LinkedIn contact/profile links when present.
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
