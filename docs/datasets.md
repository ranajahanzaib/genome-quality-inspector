# Datasets

The supported sequence ingestion paths are uploaded FASTA/FASTQ files, multi-file uploads (up to 20), allowlisted local paths, allowlisted HTTPS URLs, and selected OpenGenome2 FASTA/JSONL portions. FASTA/FASTQ may be gzip-compressed where the source importer supports it. Uploaded originals are stored on the local filesystem under generated dataset IDs. Relational metadata records the display name, tags, original filename, byte size, format, declared dataset type, source, timestamps, status, and latest result.

Compressed suffixes are checked against the inner supported file extension. File names are reduced to their basename before storage. Upload size is bounded by `GQI_MAX_UPLOAD_BYTES`. Local path import is restricted to configured `GQI_LOCAL_IMPORT_DIRS`; source URL import requires an exact host allowlist, HTTPS, public DNS, no redirects, and a bounded download. Metadata CSV/TSV can map sequence IDs to user-supplied taxon names and IDs. Taxonomy aggregation reports sequence and nucleotide totals independently and labels results as imported metadata, not sequence-based classification.

Each upload is classified by format default, and users may choose another supported dataset type in the API. Treat classification as user-provided metadata, not an automated biological determination.
