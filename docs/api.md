# API

The API is served by `apps/api/gqi_api/main.py`. FastAPI provides interactive OpenAPI docs at `/docs`. Current endpoints are available under `/api/v1`; legacy `/api` paths remain available for existing local clients.

| Method and path                                      | Purpose                                                                                                                                           |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/health`                                    | Database health and configured engine mode.                                                                                                       |
| `GET /api/datasets`                                  | Search and paginate registered datasets.                                                                                                          |
| `POST /api/datasets`                                 | Upload FASTA/FASTQ multipart file and register provenance metadata.                                                                               |
| `POST /api/v1/datasets/batch`                        | Upload up to 20 FASTA/FASTQ files in one request.                                                                                                 |
| `POST /api/v1/datasets/import-local`                 | Copy a selected FASTA/FASTQ file from an allowlisted local directory.                                                                             |
| `POST /api/v1/datasets/import-url`                   | Import a bounded FASTA/FASTQ file from an allowlisted HTTPS host.                                                                                 |
| `POST /api/v1/datasets/{id}/metadata`                | Attach CSV/TSV sequence-to-taxon metadata mappings.                                                                                               |
| `GET /api/v1/datasets/{id}/taxonomy`                 | Aggregate mapped sequence counts and nucleotide totals without performing classification.                                                         |
| `GET /api/datasets/{id}`                             | Read dataset and latest analysis.                                                                                                                 |
| `PATCH /api/datasets/{id}`                           | Update name, description, and user tags.                                                                                                          |
| `DELETE /api/datasets/{id}`                          | Delete registry row and uploaded file.                                                                                                            |
| `POST /api/datasets/{id}/analysis`                   | Queue or start analysis.                                                                                                                          |
| `GET /api/datasets/{id}/sequences`                   | Filter and paginate analyzed sequence summaries.                                                                                                  |
| `GET /api/v1/datasets/{id}/sequence-window`          | Retrieve a zero-based sequence window capped at 10,000 bases.                                                                                     |
| `GET /api/v1/datasets/{id}/findings`                 | List rule-based quality findings.                                                                                                                 |
| `PATCH /api/v1/findings/{id}`                        | Acknowledge, dismiss, or reopen a finding.                                                                                                        |
| `GET /api/datasets/{id}/report`                      | Downloadable JSON report payload.                                                                                                                 |
| `GET /api/v1/ready`                                  | Readiness check including database connectivity.                                                                                                  |
| `GET /api/v1/capabilities`                           | Supported formats and optional executable detection.                                                                                              |
| `POST /api/v1/datasets/{id}/analyze`                 | Start an immutable run, optionally with `{"k": 15}` (1–31).                                                                                       |
| `GET /api/v1/datasets/{id}/analyses`                 | Paginated analysis run history and configurations.                                                                                                |
| `GET /api/v1/analyses/{id}`                          | Read an analysis run and its result.                                                                                                              |
| `GET /api/v1/analyses/{id}/events`                   | Server-Sent Events reporting run state changes.                                                                                                   |
| `POST /api/v1/comparisons`                           | Compare and persist two to four completed dataset analyses; first dataset is the baseline.                                                        |
| `GET /api/v1/comparisons`                            | List saved comparisons.                                                                                                                           |
| `GET`, `DELETE /api/v1/comparisons/{id}`             | Read or delete a saved comparison.                                                                                                                |
| `POST /api/v1/demo/seed`                             | Idempotently register three synthetic demo fixtures and start real analyses.                                                                      |
| `GET /api/v1/integrations`                           | Integration and optional-tool availability.                                                                                                       |
| `GET /api/v1/integrations/opengenome2/files`         | Revision-pinned FASTA, JSONL, and metadata file catalog; supports `category`, `subpath`, `revision`, and `limit`.                                 |
| `GET /api/v1/integrations/opengenome2/metadata`      | Bounded preview of `species_metadata.csv` columns and rows.                                                                                       |
| `POST /api/v1/integrations/opengenome2/import`       | Import a selected FASTA shard, pin its revision, and optionally reservoir-sample records.                                                         |
| `POST /api/v1/integrations/opengenome2/import-jsonl` | Read up to a configured byte range from one plain JSONL shard, sample sequence-bearing examples, and retain tags/special tokens as provenance.    |
| `GET /api/v1/integrations/ncbi/search`               | Search NCBI genome assembly metadata through the optional `datasets` CLI (`kind=taxon` or `accession`); no genome sequence package is downloaded. |
| `GET /api/v1/integrations/gtdb/releases`             | Discover GTDB release directory names from the official metadata index without downloading release files.                                         |
| `POST /api/v1/datasets/{id}/integrations/quast`      | Queue QUAST for an uploaded `genome_assembly` FASTA when `quast.py` is installed.                                                                 |
| `GET /api/v1/tool-runs/{id}`                         | Read optional tool status, parsed result metrics, version, and bounded raw report.                                                                |

Uploads use form fields `file`, optional `name`, optional `description`, optional comma-separated `tags`, and optional `dataset_type`. Batch uploads use repeated `files` fields and accept up to 20 files. Dataset types are explicitly validated. FASTA defaults to `sequence_collection`; FASTQ defaults to `raw_reads`.

Finding defaults are controlled with `GQI_GC_MIN_PERCENT`, `GQI_GC_MAX_PERCENT`, `GQI_AMBIGUOUS_MAX_PERCENT`, `GQI_INVALID_SYMBOL_MAX`, and `GQI_DUPLICATE_MAX_PERCENT`. Findings are deterministic warnings, not clinical or taxonomic conclusions. The sequence-window endpoint scans the source file to locate the record and then returns only the requested bounded slice; it does not cache all sequence strings in a separate index.

Local imports are disabled until `GQI_LOCAL_IMPORT_DIRS` lists one or more allowed roots separated by the platform path separator. URL imports require HTTPS and an exact hostname allowlist in `GQI_SOURCE_URL_HOSTS`; DNS addresses must be public, redirects are disabled, and `GQI_URL_IMPORT_MAX_BYTES` caps transfer size (default 256 MiB). OpenGenome2 JSONL imports read only a bounded prefix/range (default 16 MiB, maximum 64 MiB); they do not fetch a full JSONL shard. NCBI search requires the optional NCBI Datasets v2 CLI named `datasets`; `NCBI_API_KEY`, when configured, is inherited by the CLI.

QUAST runs are persisted and use the configured RQ queue when `GQI_REDIS_URL` is set, otherwise a local background thread. The endpoint rejects non-assembly datasets and returns unavailable when QUAST is absent. `GQI_SPECIALIZED_TOOL_TIMEOUT` caps execution time (default 2 hours). BUSCO and CheckM2 are currently detection-only; their lineage/database configuration and execution workflows are not implemented.
