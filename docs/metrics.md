# Metrics

All reported values are computed from uploaded records by `gqi-engine`.

| Metric                | Definition and scope                                                                                                                                     |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sequence count        | Parsed FASTA records or FASTQ reads.                                                                                                                     |
| Total bases           | Sum of sequence lengths, including ambiguous and invalid characters.                                                                                     |
| Canonical bases       | Count of A, C, G, T.                                                                                                                                     |
| Ambiguous bases       | IUPAC nucleotide ambiguity symbols other than A/C/G/T, including N.                                                                                      |
| Invalid symbols       | Characters outside the accepted nucleotide IUPAC alphabet. They are reported and excluded from canonical composition and k-mers.                         |
| GC / AT percentage    | G+C or A+T divided by canonical A/C/G/T count. Null if no canonical bases exist.                                                                         |
| Per-record GC         | G+C divided by that record's canonical A/C/G/T count; null when none exist.                                                                              |
| Length summaries      | Min, max, arithmetic mean, median, population standard deviation, and nearest-rank P10/P25/P50/P75/P90/P95/P99.                                          |
| Composition           | Counts of each canonical base and each IUPAC ambiguity symbol.                                                                                           |
| Ambiguous fraction    | Ambiguous symbols divided by all record positions; invalid symbols reported separately.                                                                  |
| Duplicate identifiers | Repeated first whitespace-delimited identifier token; distinct from duplicate sequence content.                                                          |
| GC histogram          | Count of records at each nearest integer percent GC.                                                                                                     |
| k-mer counts          | Overlapping windows of the configured k (default 21); only windows composed entirely of A/C/G/T count. Counts are not reverse-complement canonicalized.  |
| Exact duplicates      | Repeated identical uppercase sequence strings; case is normalized by parsing.                                                                            |
| Shannon entropy       | Per-record entropy of observed sequence symbols, in bits. This is a composition summary, not a biological complexity verdict.                            |
| Maximum homopolymer   | Longest run of one repeated symbol within the record.                                                                                                    |
| FASTQ quality         | Mean and per-cycle mean Phred, Q20/Q30 base fractions, and per-read mean; ASCII quality minus 33, assuming Phred+33. This encoding is not auto-detected. |
| N50/N75, L50/L75      | Length contiguity statistics, exposed only for an explicitly selected `genome_assembly`. They do not measure completeness.                               |

The tool does not infer sequencing quality from FASTA, taxonomy from base composition, depth or coverage from sequence length, or assembly completeness from N50. Unsupported metrics are omitted or shown as not applicable.
