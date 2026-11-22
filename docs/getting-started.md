# Getting started

Install Rust/Cargo, Python 3.11+, `uv`, Node.js, and `pnpm`. From the repository root, build the engine:

```bash
cargo build --release --locked --manifest-path crates/gqi-engine/Cargo.toml
```

Then in `apps/api`, initialize the database and launch the HTTP service:

```bash
uv sync --locked
uv run alembic upgrade head
GQI_ENGINE=../../crates/gqi-engine/target/release/gqi-engine uv run uvicorn gqi_api.main:app --reload --port 8000
```

In `apps/web`, install the locked frontend dependencies and start Next.js:

```bash
pnpm install --frozen-lockfile
pnpm dev
```

Open http://localhost:3000 and upload a FASTA or FASTQ. Results are updated automatically while analysis runs. The JSON report button becomes active after completion. API documentation is at http://localhost:8000/docs.

For an immediate first run without downloading external data, select **Load sample datasets** on the empty dashboard. This registers synthetic FASTA, FASTQ, and assembly fixtures and runs the real Rust analysis engine. From `apps/api`, the equivalent seed command is:

```bash
uv run python scripts/seed_demo.py
```

The command requires the API to be running. The fixtures are clearly labeled synthetic, and their metrics are calculated from the included sequence records.

To use PostgreSQL and Redis, run `docker compose up -d`, set the URLs in `.env.example` in the shell running the API, apply the Alembic migration, and start `uv run rq worker gqi-analysis` from `apps/api`. SQLite and in-process jobs need neither service.
