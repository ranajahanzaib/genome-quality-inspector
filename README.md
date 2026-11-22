# genome-quality-inspector

Local-first application for inspecting nucleotide FASTA and FASTQ datasets. The Rust engine computes results from uploaded records; the FastAPI service persists dataset metadata and analysis results; the Next.js interface visualizes those persisted results.

The supported workflow is FASTA/FASTQ import, analysis, dataset inspection, comparison, and JSON report export. See [scientific limitations](docs/scientific-limitations.md) for the tool's interpretation boundaries.

## Supported today

- FASTA (`.fa`, `.fasta`, `.fna`, `.ffn`) and FASTQ (`.fq`, `.fastq`), including gzip-compressed files.
- Single and multi-file uploads, allowlisted local-path and HTTPS URL imports, dataset tags, and selected OpenGenome2 FASTA or bounded JSONL portion imports.
- Sequence counts, composition, IUPAC ambiguity, low-complexity entropy regions, duplicate IDs, exact and reverse-complement duplicate counts, k-mer counts, length percentiles, and GC/length histograms.
- FASTQ Phred+33 summaries, per-position mean quality, per-cycle base counts, and Q20/Q30 percentages; FASTA quality metrics are not applicable.
- Assembly N50/N75/N90, L50/L75/L90, and Nx curves only when the user explicitly selects `genome_assembly`. These are contiguity statistics, not completeness estimates.
- Configurable findings with acknowledgement/dismissal, saved comparisons, bounded sequence windows, and taxonomy summaries from user-supplied CSV/TSV mappings.
- Metadata-only NCBI genome search through the optional NCBI Datasets CLI and GTDB release discovery. These integrations do not download genome collections.
- SQLite for a zero-setup local run; PostgreSQL through `DATABASE_URL`; Alembic schema migration; optional RQ/Redis queue; paginated API results; sequence ID filtering; JSON report export.
- Immutable analysis run history with saved k-mer configuration, software version in result payloads, versioned `/api/v1` routes, readiness/capability checks, and Server-Sent Events for run state.

## Built-in demo

The web app includes three bundled **synthetic** fixtures. Start the API and web app using the instructions below, then choose **Load sample datasets** on the empty workspace. The Rust engine analyzes the fixture records; the UI labels them synthetic so their metrics are not mistaken for biological observations.

The bundled fixtures produce these results:

| Fixture                     | Records | Bases | Example metrics                         |
| --------------------------- | ------: | ----: | --------------------------------------- |
| Sequence collection (FASTA) |       8 | 1,208 | GC 49.33%; 1 exact duplicate            |
| Read quality (FASTQ)        |       4 |    67 | Mean Phred 30.0; Q20 92.54%; Q30 62.69% |
| Assembly (FASTA)            |       5 | 1,074 | GC 54.75%; N50 320 bp                   |

These values are calculated from the bundled files in [`apps/api/fixtures/demo/`](apps/api/fixtures/demo/). The fixtures make the analysis views explorable without importing external data.

## Requirements

- Rust toolchain and Cargo.
- Python 3.11 or newer and `uv`.
- Node.js and `pnpm`.
- Optional: Docker Compose for PostgreSQL and Redis.

## Run locally

From the repository root, in separate terminals:

```bash
# Build the analysis engine once
cargo build --release --locked --manifest-path crates/gqi-engine/Cargo.toml

# Prepare and start the API
cd apps/api
uv sync --locked
uv run alembic upgrade head
GQI_ENGINE=../../crates/gqi-engine/target/release/gqi-engine uv run uvicorn gqi_api.main:app --reload --port 8000

# Start the web app
cd ../web
pnpm install --frozen-lockfile
pnpm dev
```

Open http://localhost:3000. Uploaded data is stored under repository `data/` by default. Set `GQI_DATA_DIR` to change the directory and `GQI_MAX_UPLOAD_BYTES` to change the upload limit (default 5 GiB). Set `NEXT_PUBLIC_API_URL` when the API is not at `http://localhost:8000`.

For a one-command engine invocation:

```bash
cargo run --release --locked --manifest-path crates/gqi-engine/Cargo.toml -- sample.fasta --dataset-type genome_assembly --k 21
```

The CLI prints one JSON analysis document to stdout. `--dataset-type` accepts `sequence_collection`, `raw_reads`, `genome_assembly`, `reference_genome`, `training_corpus`, or `unknown`.

## PostgreSQL and RQ

For PostgreSQL, copy `.env.example` to `.env` in the repository root, set `POSTGRES_PASSWORD` to a local password, then run `docker compose up -d`. Configure `DATABASE_URL` as `postgresql+psycopg://gqi:${POSTGRES_PASSWORD}@localhost:5432/gqi` and run `uv run alembic upgrade head` from `apps/api`. SQLite is the default and needs no credentials.

To use durable background jobs, set `GQI_REDIS_URL=redis://localhost:6379/0` for the API and start a worker from `apps/api`:

```bash
uv run rq worker gqi-analysis
```

Without `GQI_REDIS_URL`, the local API uses a background thread for convenience. That fallback is not durable across process restarts. For local development, `docker compose up -d` starts PostgreSQL and Redis; set the corresponding environment variables before launching API and worker processes.

## API

- `GET /api/health`
- `GET /api/datasets?q=&offset=&limit=`
- `POST /api/datasets` (multipart `file`; optional `name`, `description`, `dataset_type`)
- `GET`, `PATCH`, `DELETE /api/datasets/{id}`
- `POST /api/datasets/{id}/analysis`
- `GET /api/datasets/{id}/sequences?q=&min_length=&max_length=&offset=&limit=`
- `GET /api/datasets/{id}/report`
- Interactive OpenAPI documentation at http://localhost:8000/docs

## Validation

```bash
cargo fmt --manifest-path crates/gqi-engine/Cargo.toml --check
cargo test --locked --manifest-path crates/gqi-engine/Cargo.toml
cargo clippy --locked --manifest-path crates/gqi-engine/Cargo.toml --all-targets -- -D warnings
cd apps/api && uv run pytest && uv run ruff check gqi_api tests migrations && uv run mypy gqi_api
cd ../web && pnpm exec tsc --noEmit && pnpm lint && pnpm build
```

## Current scope and limitations

Read [`docs/scientific-limitations.md`](docs/scientific-limitations.md), [`docs/metrics.md`](docs/metrics.md), and [`docs/architecture.md`](docs/architecture.md) for supported metrics, architecture, and interpretation boundaries. OpenGenome2 import behavior is described in [`docs/opengenome2.md`](docs/opengenome2.md). Automated GTDB taxonomy classification, NCBI reference-sequence comparison, BUSCO/CheckM2 execution, near-duplicate matching, disk-backed analytics, multi-user authentication, and advanced report formats are not supported. QUAST can analyze uploaded assembly FASTA when its optional CLI is installed. The engine retains sequence records and results in memory, so use input sizes appropriate for the available memory. Generic sequence statistics do not establish completeness, taxonomy, coverage, or reference consistency.

## License

MIT. Input data remains under the user's control; review the upstream dataset license and attribution terms before importing or redistributing third-party data.
