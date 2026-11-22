# Performance

No throughput or memory benchmarks are claimed. The analyzer currently reads records and retains per-sequence output and exact k-mer/duplicate maps in memory. Its memory use therefore depends on total bases, distinct k-mers, and sequence count. Keep input files modest and raise the 5 GiB upload cap only when the host can safely support the resulting in-memory work.

Benchmark methodology and large-data support remain future work. Planned improvements include streaming parsing, external/columnar analytical artifacts, bounded result pagination, chart aggregation, and representative throughput and memory measurements.
