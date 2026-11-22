# Architecture

The current implementation has three executable pieces:

1. `crates/gqi-engine` is a Rust command-line analyzer. The API runs it as a subprocess and parses its JSON output.
2. `apps/api/gqi_api` is a synchronous FastAPI/SQLAlchemy HTTP service. Dataset metadata, state, and the latest analysis document are stored in a relational database. Uploaded files remain on disk outside the database.
3. `apps/web` is a Next.js App Router client that reads persisted API data and renders charts, summary metrics, k-mer counts, and sequence rows.

```text
Browser → Next.js UI → FastAPI → SQLite/PostgreSQL
                              ├→ uploaded FASTA/FASTQ files
                              └→ Rust analysis process → JSON result → database
                                      ↑
                          optional RQ worker ← Redis
```

SQLite is the zero-setup default. Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL and apply the Alembic migration for shared local development. Set `GQI_REDIS_URL` on the API and run an RQ worker for durable queue processing. Without Redis, analysis runs in a daemon thread and is lost if the API exits during a job.

The result JSON currently lives in a text column. The project does not yet use Parquet, DuckDB, object storage, event streaming, or a separate worker service in the default run. The parser currently retains sequence data and result rows in memory; split large inputs into manageable files.

## Source layout

- `crates/gqi-engine/`: Rust analyzer and unit tests.
- `apps/api/gqi_api/`: API, upload handling, SQLAlchemy model, subprocess/queue orchestration.
- `apps/api/migrations/`: Alembic migration.
- `apps/api/tests/`: API tests.
- `apps/web/src/app/`: Next.js application and styles.
- `docs/`: scientific, architecture, setup, and configuration notes.
