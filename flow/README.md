# Flow Pipelines

This project runs local Metaflow pipelines for resume profile extraction, FAISS
index backfill, and kNN search.

## Prerequisites

- Python 3.11+
- `uv`
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

## Resume extraction batch flow

Parse each top-level PDF under an input directory into structured resume JSON
and persist each row into SQLite.

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
- Writes one JSON file per input PDF as `<pdf_stem>_resume.json`.
- Upserts metadata + profile payload into `outputs/resume_profiles.db`.

## Resume FAISS backfill flow

Create one shared `faiss.IndexFlatL2` file for selected rows in
`resume_profiles`, then write the shared index path back into SQLite.

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

- `--mode full` indexes all rows, `--mode missing` indexes only rows with null `faiss_index_path`.
- Flattens each `profile_json` into deterministic text via `flatten_resume_profile`.
- Generates embeddings in batches and writes a new local FAISS file.
- Updates selected rows with that shared FAISS index path.

## Resume kNN search flow

Parse one resume PDF, flatten and embed it, then run nearest-neighbor search
against an existing FAISS index.

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
  --index-path /absolute/path/to/resume_profiles_20260223T071759Z.faiss \
  --db-path outputs/resume_profiles.db \
  --extraction-model gpt-5.1 \
  --embedding-model text-embedding-3-large
```

Behavior:

- Extracts structured resume JSON from the given PDF.
- Flattens profile text with `flatten_resume_profile`.
- Embeds the query and runs `IndexFlatL2` search on the FAISS file.
- Resolves neighbor metadata (`id`, `pdf_stem`, `full_name`) from SQLite when available.

## Resume profile flatten flow

Fetch one row from SQLite by `pdf_stem`, flatten its stored profile JSON, and
print the flattened result.

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

## Tests

Run the protected regression suite:

```bash
uv run python -m unittest flow.tests.test_resume_extraction_batch_flow -v
uv run python -m unittest flow.tests.test_resume_faiss_backfill_flow -v
uv run python -m unittest flow.tests.test_resume_profile_flatten_flow -v
```
