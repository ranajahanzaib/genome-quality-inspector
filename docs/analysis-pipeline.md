# Analysis pipeline

1. The API validates file suffix, compressed/uncompressed format, requested dataset type, and upload size.
2. The original file is stored on disk and a dataset row is persisted.
3. Each analysis request creates an immutable `AnalysisRun` row with its own ID, configuration and state. If `GQI_REDIS_URL` is configured, the API enqueues an RQ job on `gqi-analysis`; otherwise a daemon thread runs the job for local development.
4. The worker invokes the Rust CLI with file path, declared dataset type and configured k-mer size.
5. The CLI parses records, calculates supported metrics, and emits JSON to stdout.
6. The API saves the result on the run and as the dataset's latest result, then sets their states to `complete`, or records an actionable error and sets both to `failed`.
7. The web client polls dataset listing and displays persisted results.

Current states include `uploaded`, `queued`, `running`, `complete`, and `failed`. The SSE endpoint streams state changes but not stage percentages. Cancellation, per-stage progress, and retry policies are not yet implemented.
