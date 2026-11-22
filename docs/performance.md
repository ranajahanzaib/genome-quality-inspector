# Performance

No throughput or memory benchmarks are claimed. The analyzer currently reads records and retains per-sequence output and exact k-mer/duplicate maps in memory. Its memory use therefore depends on total bases, distinct k-mers, and sequence count. Keep input files modest and raise the 5 GiB upload cap only when the host can safely support the resulting in-memory work.

Large-file performance has not been characterized, and the application does not publish throughput or memory benchmarks. Streaming parsing and disk-backed analytical results are not supported.
