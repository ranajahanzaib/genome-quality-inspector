# OpenGenome2 imports

The API browses `arcinstitute/opengenome2` through the Hugging Face Hub and resolves branch or tag names to a commit SHA. Imports use that SHA for metadata lookup and download, then persist the revision with the dataset so that the selected source is traceable.

## Catalog behavior

- The UI lists up to 100 files for FASTA, JSONL, or metadata catalog views. The API accepts a `subpath` for narrowing a catalog query.
- The metadata view previews the actual `species_metadata.csv` header and up to 50 source rows. The file is bounded by `GQI_METADATA_MAX_BYTES` (default 10 MiB); preview values remain source annotations, not classifications produced by the application.
- Selected FASTA shards can be imported with record reservoir sampling. Plain JSONL shards can be imported from a bounded prefix (default 16 MiB, hard maximum 64 MiB); no full shard fetch occurs. Extraction handles nucleotide-only values under common sequence/text field names, preserves detected training tags and special tokens, and stores those counts in sampling provenance. Metadata files remain preview-only.
- The import endpoint rejects unsafe paths, unsupported formats, unknown source sizes, and source files above `GQI_IMPORT_MAX_BYTES` (default 1 GiB). The expanded sequence content is also bounded during parsing.
- Public datasets can be accessed without a token when the upstream repository permits it. Set `HF_TOKEN` in the API environment for gated access.

## Sampling

The UI imports a deterministic reservoir sample of at most 10,000 records using seed 42. This gives every source record an equal chance of inclusion without retaining the whole source in memory. If the shard has 10,000 or fewer records, every record is included. The API accepts `sample_size` from 1 to 100,000; `sample_size: 0` explicitly requests all records and remains subject to the import size cap. `sample_seed` controls reproducibility.

The dataset response records whether sampling occurred, the selected and source record counts, method, seed, original source byte size, repository path, optional Hub blob ID, and resolved commit. JSONL portion imports also record byte count and training tag/token counts. Analysis metrics describe the stored selected records; the UI labels sampled datasets accordingly. Deleting the dataset also deletes its local imported file.

This first integration handles FASTA only. It does not imply species identity, completeness, taxonomic assignment, or assembly quality.
