# Configuration

| Variable                                    | Default                                  | Purpose                                                                      |
| ------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------- |
| `DATABASE_URL`                              | repository `data/gqi.sqlite3` SQLite URL | SQLAlchemy connection. PostgreSQL driver is `psycopg`.                       |
| `GQI_DATA_DIR`                              | repository `data/`                       | Upload storage directory.                                                    |
| `GQI_ENGINE`                                | `cargo run` fallback                     | Path to a prebuilt `gqi-engine` binary.                                      |
| `GQI_MAX_UPLOAD_BYTES`                      | 5 GiB                                    | Maximum bytes accepted per upload.                                           |
| `GQI_ANALYSIS_TIMEOUT`                      | 3600 seconds                             | Rust process / RQ job timeout.                                               |
| `GQI_REDIS_URL`                             | unset                                    | Enables Redis/RQ queue mode.                                                 |
| `GQI_CORS_ORIGINS`                          | `http://localhost:3000`                  | Comma-separated browser origins.                                             |
| `NEXT_PUBLIC_API_URL`                       | `http://localhost:8000`                  | API URL used by the frontend browser.                                        |
| `GQI_LOCAL_IMPORT_DIRS`                     | unset                                    | Platform-separated local path import roots; imports are disabled when unset. |
| `GQI_SOURCE_URL_HOSTS`                      | unset                                    | Comma-separated exact HTTPS hostnames allowed for URL imports.               |
| `GQI_URL_IMPORT_MAX_BYTES`                  | 256 MiB                                  | Maximum URL import size, further constrained by each request.                |
| `GQI_JSONL_PORTION_MAX_BYTES`               | 16 MiB                                   | Maximum OpenGenome2 JSONL prefix; request and server limit capped at 64 MiB. |
| `GQI_GC_MIN_PERCENT` / `GQI_GC_MAX_PERCENT` | 20 / 80                                  | GC warning bounds.                                                           |
| `GQI_AMBIGUOUS_MAX_PERCENT`                 | 5                                        | Ambiguous-base warning threshold.                                            |
| `GQI_INVALID_SYMBOL_MAX`                    | 0                                        | Invalid-symbol warning threshold.                                            |
| `GQI_DUPLICATE_MAX_PERCENT`                 | 10                                       | Exact-duplicate warning threshold.                                           |
| `GQI_LOW_COMPLEXITY_MAX_PERCENT`            | 15                                       | Low-complexity finding threshold by record count.                            |
| `NCBI_API_KEY`                              | unset                                    | Optional key inherited by the NCBI Datasets CLI.                             |

Copy `.env.example` to `.env` as a starting point. Local SQLite startup does not require a `.env` file.
