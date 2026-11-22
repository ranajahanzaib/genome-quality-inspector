use anyhow::{Context, Result, bail};
use clap::Parser;
use flate2::read::MultiGzDecoder;
use serde::Serialize;
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fs::File,
    io::{BufRead, BufReader},
    path::PathBuf,
};

#[derive(Parser)]
#[command(about = "Streaming nucleotide sequence quality analysis")]
struct Args {
    input: PathBuf,
    #[arg(long, value_parser = ["sequence_collection", "raw_reads", "genome_assembly", "reference_genome", "training_corpus", "unknown"])]
    dataset_type: Option<String>,
    #[arg(long, default_value_t = 21, value_parser = clap::value_parser!(u8).range(1..=31))]
    k: u8,
}

#[derive(Serialize, Clone)]
struct Record {
    id: String,
    length: usize,
    gc_percent: Option<f64>,
    ambiguous_bases: usize,
    ambiguous_percent: Option<f64>,
    max_ambiguous_run: usize,
    invalid_symbols: usize,
    shannon_entropy: Option<f64>,
    max_homopolymer: usize,
    low_complexity_regions: Vec<LowComplexityRegion>,
    hash: String,
    mean_phred: Option<f64>,
}
#[derive(Serialize, Clone)]
struct LowComplexityRegion {
    start: usize,
    end: usize,
    minimum_entropy: f64,
    method: &'static str,
    threshold_bits: f64,
}
#[derive(Serialize)]
struct ResultDoc {
    engine_version: &'static str,
    input_format: String,
    dataset_type: String,
    sequence_count: usize,
    total_bases: usize,
    valid_iupac_bases: usize,
    canonical_bases: usize,
    ambiguous_bases: usize,
    ambiguous_percent: Option<f64>,
    invalid_symbols: usize,
    missing_identifiers: usize,
    duplicate_identifiers: usize,
    duplicate_rate_percent: f64,
    nucleotide_counts: BTreeMap<String, usize>,
    ambiguity_symbol_counts: BTreeMap<String, usize>,
    gc_percent: Option<f64>,
    at_percent: Option<f64>,
    length: LengthStats,
    n50: Option<usize>,
    n75: Option<usize>,
    n90: Option<usize>,
    l50: Option<usize>,
    l75: Option<usize>,
    l90: Option<usize>,
    nx_curve: Vec<(usize, usize)>,
    gc_histogram: Vec<usize>,
    length_histogram: BTreeMap<String, usize>,
    k: usize,
    top_kmers: Vec<(String, usize)>,
    top_canonical_kmers: Vec<(String, usize)>,
    kmer_spectrum: Vec<(usize, usize)>,
    kmer_gc_heatmap: Vec<(usize, usize, usize)>,
    duplicate_sequences: usize,
    reverse_complement_duplicate_sequences: usize,
    low_complexity_region_count: usize,
    low_complexity_sequence_count: usize,
    duplicated_bases: usize,
    records: Vec<Record>,
    fastq: Option<FastqStats>,
    limitations: Vec<String>,
}
#[derive(Serialize)]
struct LengthStats {
    min: usize,
    max: usize,
    mean: f64,
    median: f64,
    population_std_dev: f64,
    percentiles: BTreeMap<String, usize>,
}
#[derive(Serialize)]
struct FastqStats {
    mean_phred: f64,
    q20_percent: f64,
    q30_percent: f64,
    per_base_mean_phred: Vec<f64>,
    reads_with_n: usize,
    per_base_composition: Vec<BTreeMap<String, usize>>,
}
type SequenceRecords = Vec<(String, Vec<u8>)>;
type QualityScores = Vec<Vec<u8>>;

fn main() -> Result<()> {
    let args = Args::parse();
    let file =
        File::open(&args.input).with_context(|| format!("cannot open {}", args.input.display()))?;
    let is_gzip = args
        .input
        .extension()
        .is_some_and(|e| e.eq_ignore_ascii_case("gz"));
    let reader: Box<dyn BufRead> = if is_gzip {
        Box::new(BufReader::new(MultiGzDecoder::new(file)))
    } else {
        Box::new(BufReader::new(file))
    };
    let ext = args
        .input
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let fmt = if [".fq", ".fastq"]
        .iter()
        .any(|x| ext.ends_with(x) || ext.ends_with(&format!("{x}.gz")))
    {
        "fastq"
    } else {
        "fasta"
    };
    let (seqs, qualities) = parse(reader, fmt)?;
    if seqs.is_empty() {
        bail!("input contains no sequence records");
    }
    let inferred = if fmt == "fastq" {
        "raw_reads"
    } else {
        "sequence_collection"
    };
    let dtype = args.dataset_type.as_deref().unwrap_or(inferred).to_string();
    println!(
        "{}",
        serde_json::to_string(&analyze(seqs, qualities, fmt, dtype, args.k as usize))?
    );
    Ok(())
}

fn parse(mut r: Box<dyn BufRead>, fmt: &str) -> Result<(SequenceRecords, QualityScores)> {
    let mut lines = Vec::new();
    let mut line = String::new();
    while r.read_line(&mut line)? > 0 {
        lines.push(line.trim_end_matches(['\r', '\n']).to_owned());
        line.clear();
    }
    let mut out = Vec::new();
    let mut qs = Vec::new();
    if fmt == "fasta" {
        let mut id: Option<String> = None;
        let mut seq = Vec::new();
        for l in lines {
            if let Some(h) = l.strip_prefix('>') {
                if let Some(prev) = id.replace(h.to_owned()) {
                    out.push((prev, std::mem::take(&mut seq)));
                }
            } else if !l.trim().is_empty() {
                if id.is_none() {
                    bail!("FASTA sequence data appears before the first > header");
                }
                seq.extend(
                    l.trim()
                        .bytes()
                        .filter(|b| !b.is_ascii_whitespace())
                        .map(|b| b.to_ascii_uppercase()),
                );
            }
        }
        if let Some(id) = id {
            out.push((id, seq));
        }
    } else {
        let mut i = 0;
        while i < lines.len() {
            if lines[i].is_empty() {
                i += 1;
                continue;
            }
            if !lines[i].starts_with('@') || i + 3 >= lines.len() || !lines[i + 2].starts_with('+')
            {
                bail!("malformed FASTQ record near line {}", i + 1);
            }
            let seq = lines[i + 1].trim().to_ascii_uppercase().into_bytes();
            let q = lines[i + 3].as_bytes().to_vec();
            if seq.len() != q.len() {
                bail!(
                    "FASTQ sequence and quality lengths differ for {}",
                    &lines[i][1..]
                );
            }
            if q.iter().any(|score| !(33..=126).contains(score)) {
                bail!(
                    "FASTQ quality scores must be printable Phred+33 values for {}",
                    &lines[i][1..]
                );
            }
            out.push((lines[i][1..].to_owned(), seq));
            qs.push(q);
            i += 4;
        }
    }
    Ok((out, qs))
}

fn entropy(seq: &[u8]) -> Option<f64> {
    if seq.is_empty() {
        return None;
    }
    let mut c = [0usize; 256];
    for b in seq {
        c[*b as usize] += 1;
    }
    Some(
        c.iter()
            .filter(|x| **x > 0)
            .map(|x| {
                let p = *x as f64 / seq.len() as f64;
                -p * p.log2()
            })
            .sum(),
    )
}

fn find_low_complexity_regions(seq: &[u8]) -> Vec<LowComplexityRegion> {
    const WINDOW: usize = 100;
    const STEP: usize = 25;
    const THRESHOLD: f64 = 1.2;
    if seq.len() < WINDOW {
        return Vec::new();
    }
    let mut regions: Vec<LowComplexityRegion> = Vec::new();
    for start in (0..=seq.len() - WINDOW).step_by(STEP) {
        let score = entropy(&seq[start..start + WINDOW]).unwrap_or(f64::INFINITY);
        if score <= THRESHOLD {
            let end = start + WINDOW;
            if let Some(previous) = regions.last_mut().filter(|region| start <= region.end) {
                previous.end = end;
                previous.minimum_entropy = previous.minimum_entropy.min(score);
            } else {
                regions.push(LowComplexityRegion {
                    start,
                    end,
                    minimum_entropy: score,
                    method: "shannon_sliding_window",
                    threshold_bits: THRESHOLD,
                });
            }
        }
    }
    regions
}
fn n_stat(lengths: &[usize], fraction: f64) -> (Option<usize>, Option<usize>) {
    let total: usize = lengths.iter().sum();
    if total == 0 {
        return (None, None);
    }
    let mut s = lengths.to_vec();
    s.sort_unstable_by(|a, b| b.cmp(a));
    let mut sum = 0;
    for (i, n) in s.iter().enumerate() {
        sum += *n;
        if sum as f64 >= total as f64 * fraction {
            return (Some(*n), Some(i + 1));
        }
    }
    (None, None)
}

fn nearest_rank(sorted: &[usize], fraction: f64) -> usize {
    let rank = (fraction * sorted.len() as f64).ceil() as usize;
    sorted[rank.saturating_sub(1).min(sorted.len() - 1)]
}

fn reverse_complement_key(seq: &[u8]) -> Vec<u8> {
    let reverse: Vec<u8> = seq
        .iter()
        .rev()
        .map(|base| match base {
            b'A' => b'T',
            b'T' => b'A',
            b'C' => b'G',
            b'G' => b'C',
            b'R' => b'Y',
            b'Y' => b'R',
            b'S' => b'S',
            b'W' => b'W',
            b'K' => b'M',
            b'M' => b'K',
            b'B' => b'V',
            b'V' => b'B',
            b'D' => b'H',
            b'H' => b'D',
            _ => *base,
        })
        .collect();
    if reverse.as_slice() < seq {
        reverse
    } else {
        seq.to_vec()
    }
}

fn analyze(
    seqs: Vec<(String, Vec<u8>)>,
    qualities: Vec<Vec<u8>>,
    fmt: &str,
    dtype: String,
    k: usize,
) -> ResultDoc {
    let mut lengths = Vec::new();
    let mut records = Vec::new();
    let mut kmers: HashMap<String, usize> = HashMap::new();
    let mut canonical_kmers: HashMap<String, usize> = HashMap::new();
    let mut unique: HashMap<String, usize> = HashMap::new();
    let mut reverse_complement_unique: HashMap<Vec<u8>, usize> = HashMap::new();
    let mut gc = 0usize;
    let mut at = 0usize;
    let mut canonical = 0usize;
    let mut ambiguous = 0usize;
    let mut invalid = 0usize;
    let mut valid_iupac = 0usize;
    let mut nucleotide_counts = [0usize; 4];
    let mut ambiguity_counts = [0usize; 11];
    let mut missing_identifiers = 0usize;
    let mut duplicate_identifiers = 0usize;
    let mut seen_ids = HashSet::new();
    let mut gc_hist = vec![0usize; 101];
    let mut lh = BTreeMap::new();
    let mut duplicated_bases = 0usize;
    for (record_index, (id, seq)) in seqs.iter().enumerate() {
        let len = seq.len();
        lengths.push(len);
        let mut rgc = 0usize;
        let mut rcanonical = 0usize;
        let mut ramb = 0usize;
        let mut rinv = 0usize;
        let mut ambiguous_run = 0usize;
        let mut max_ambiguous_run = 0usize;
        let mut run = 0usize;
        let mut prev = 0;
        let mut maxrun = 0;
        for b in seq {
            match b {
                b'A' => {
                    at += 1;
                    canonical += 1;
                    rcanonical += 1;
                    nucleotide_counts[0] += 1;
                    valid_iupac += 1
                }
                b'T' => {
                    at += 1;
                    canonical += 1;
                    rcanonical += 1;
                    nucleotide_counts[3] += 1;
                    valid_iupac += 1
                }
                b'G' => {
                    gc += 1;
                    rgc += 1;
                    canonical += 1;
                    rcanonical += 1;
                    nucleotide_counts[2] += 1;
                    valid_iupac += 1
                }
                b'C' => {
                    gc += 1;
                    rgc += 1;
                    canonical += 1;
                    rcanonical += 1;
                    nucleotide_counts[1] += 1;
                    valid_iupac += 1
                }
                b'N' | b'R' | b'Y' | b'S' | b'W' | b'K' | b'M' | b'B' | b'D' | b'H' | b'V' => {
                    ambiguous += 1;
                    ramb += 1;
                    valid_iupac += 1;
                    let ambiguity_symbols = b"NRYSWKMBDHV";
                    if let Some(index) = ambiguity_symbols.iter().position(|symbol| symbol == b) {
                        ambiguity_counts[index] += 1;
                    }
                }
                _ => {
                    invalid += 1;
                    rinv += 1
                }
            }
            if matches!(
                b,
                b'N' | b'R' | b'Y' | b'S' | b'W' | b'K' | b'M' | b'B' | b'D' | b'H' | b'V'
            ) {
                ambiguous_run += 1;
                max_ambiguous_run = max_ambiguous_run.max(ambiguous_run);
            } else {
                ambiguous_run = 0;
            }
            if *b == prev {
                run += 1
            } else {
                run = 1;
                prev = *b;
            }
            maxrun = maxrun.max(run);
        }
        if rcanonical > 0 {
            gc_hist[((rgc as f64 / rcanonical as f64 * 100.0).round() as usize).min(100)] += 1;
        }
        let identifier = id.split_whitespace().next().unwrap_or("");
        if identifier.is_empty() {
            missing_identifiers += 1;
        } else if !seen_ids.insert(identifier.to_owned()) {
            duplicate_identifiers += 1;
        }
        let bucket = if len < 100 {
            "0-99".to_owned()
        } else {
            format!("{}-{}", (len / 100) * 100, (len / 100) * 100 + 99)
        };
        *lh.entry(bucket).or_insert(0) += 1;
        let normalized = String::from_utf8_lossy(seq).into_owned();
        let h = blake3::hash(normalized.as_bytes()).to_hex().to_string();
        let occurrences = unique.entry(normalized.clone()).or_insert(0);
        *occurrences += 1;
        if *occurrences > 1 {
            duplicated_bases += len;
        }
        *reverse_complement_unique
            .entry(reverse_complement_key(seq))
            .or_insert(0) += 1;
        for w in seq.windows(k) {
            if w.iter().all(|b| matches!(b, b'A' | b'C' | b'G' | b'T')) {
                *kmers
                    .entry(String::from_utf8_lossy(w).into_owned())
                    .or_insert(0) += 1;
                *canonical_kmers
                    .entry(String::from_utf8_lossy(&reverse_complement_key(w)).into_owned())
                    .or_insert(0) += 1;
            }
        }
        records.push(Record {
            id: id.clone(),
            length: len,
            gc_percent: if rcanonical > 0 {
                Some(rgc as f64 / rcanonical as f64 * 100.)
            } else {
                None
            },
            ambiguous_bases: ramb,
            ambiguous_percent: if len > 0 {
                Some(ramb as f64 / len as f64 * 100.)
            } else {
                None
            },
            max_ambiguous_run,
            invalid_symbols: rinv,
            shannon_entropy: entropy(seq),
            max_homopolymer: maxrun,
            low_complexity_regions: find_low_complexity_regions(seq),
            hash: h,
            mean_phred: qualities.get(record_index).and_then(|scores| {
                (!scores.is_empty()).then(|| {
                    scores
                        .iter()
                        .map(|score| score.saturating_sub(33) as usize)
                        .sum::<usize>() as f64
                        / scores.len() as f64
                })
            }),
        });
    }
    let total: usize = lengths.iter().sum();
    let mut sorted = lengths.clone();
    sorted.sort_unstable();
    let mean = total as f64 / lengths.len() as f64;
    let median = if sorted.len() % 2 == 0 {
        (sorted[sorted.len() / 2 - 1] as f64 + sorted[sorted.len() / 2] as f64) / 2.
    } else {
        sorted[sorted.len() / 2] as f64
    };
    let population_std_dev = (sorted
        .iter()
        .map(|length| (*length as f64 - mean).powi(2))
        .sum::<f64>()
        / sorted.len() as f64)
        .sqrt();
    let percentiles = [10, 25, 50, 75, 90, 95, 99]
        .into_iter()
        .map(|p| (format!("p{p}"), nearest_rank(&sorted, p as f64 / 100.0)))
        .collect();
    // N/L statistics describe contiguity only; expose them only for an
    // explicitly user-classified assembly, never arbitrary sequence windows.
    let (n50, l50, n75, l75, n90, l90) = if dtype == "genome_assembly" {
        let (n50, l50) = n_stat(&lengths, 0.5);
        let (n75, l75) = n_stat(&lengths, 0.75);
        let (n90, l90) = n_stat(&lengths, 0.9);
        (n50, l50, n75, l75, n90, l90)
    } else {
        (None, None, None, None, None, None)
    };
    let nx_curve = if dtype == "genome_assembly" {
        let mut descending = lengths.clone();
        descending.sort_unstable_by(|a, b| b.cmp(a));
        let mut points = Vec::new();
        let mut cumulative = 0usize;
        let mut next_percent = 5usize;
        for length in descending {
            cumulative += length;
            while next_percent <= 100
                && cumulative as f64 >= total as f64 * next_percent as f64 / 100.0
            {
                points.push((next_percent, length));
                next_percent += 5;
            }
        }
        points
    } else {
        Vec::new()
    };
    let mut top: Vec<_> = kmers.into_iter().collect();
    top.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    top.truncate(100);
    let mut canonical_top: Vec<_> = canonical_kmers
        .iter()
        .map(|(word, count)| (word.clone(), *count))
        .collect();
    canonical_top.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    canonical_top.truncate(100);
    let mut spectrum: BTreeMap<usize, usize> = BTreeMap::new();
    let mut gc_heat: BTreeMap<(usize, usize), usize> = BTreeMap::new();
    for (word, abundance) in &canonical_kmers {
        *spectrum.entry(*abundance).or_insert(0) += 1;
        let gc_count = word
            .bytes()
            .filter(|base| matches!(base, b'G' | b'C'))
            .count();
        *gc_heat.entry((gc_count, *abundance)).or_insert(0) += 1;
    }
    let fastq = if fmt == "fastq" {
        let max = qualities.iter().map(Vec::len).max().unwrap_or(0);
        let mut sums = vec![0usize; max];
        let mut counts = vec![0usize; max];
        let mut all = 0usize;
        let mut q20 = 0usize;
        let mut q30 = 0usize;
        let mut nreads = 0;
        let mut nsum = 0usize;
        let mut composition = vec![[0usize; 5]; max];
        for (idx, q) in qualities.iter().enumerate() {
            for (i, b) in q.iter().enumerate() {
                let phred = b.saturating_sub(33) as usize;
                sums[i] += phred;
                counts[i] += 1;
                all += phred;
                q20 += usize::from(phred >= 20);
                q30 += usize::from(phred >= 30);
                let base = seqs[idx].1[i];
                let base_index = match base {
                    b'A' => Some(0),
                    b'C' => Some(1),
                    b'G' => Some(2),
                    b'T' => Some(3),
                    b'N' => Some(4),
                    _ => None,
                };
                if let Some(base_index) = base_index {
                    composition[i][base_index] += 1;
                }
            }
            if seqs[idx].1.contains(&b'N') {
                nreads += 1;
            }
            nsum += q.len();
        }
        Some(FastqStats {
            mean_phred: if nsum > 0 {
                all as f64 / nsum as f64
            } else {
                0.
            },
            q20_percent: if nsum > 0 {
                q20 as f64 / nsum as f64 * 100.
            } else {
                0.
            },
            q30_percent: if nsum > 0 {
                q30 as f64 / nsum as f64 * 100.
            } else {
                0.
            },
            per_base_mean_phred: sums
                .iter()
                .zip(counts.iter())
                .map(|(s, c)| if *c > 0 { *s as f64 / *c as f64 } else { 0. })
                .collect(),
            reads_with_n: nreads,
            per_base_composition: composition
                .into_iter()
                .map(|counts| {
                    ["A", "C", "G", "T", "N"]
                        .into_iter()
                        .enumerate()
                        .map(|(i, base)| (base.to_string(), counts[i]))
                        .collect()
                })
                .collect(),
        })
    } else {
        None
    };
    let mut limitations=vec!["Dataset GC and AT percentages use canonical A/C/G/T bases as denominator; invalid and ambiguous symbols are reported separately.".into(),"Assembly N/L statistics are length-only and must not be interpreted as completeness.".into()];
    if fmt == "fastq" {
        limitations.push("FASTQ quality values are interpreted as Phred+33; the source encoding is not inferred.".into());
    }
    if fmt == "fasta" {
        limitations.push(
            "Read-quality metrics are not applicable because FASTA contains no quality scores."
                .into(),
        );
    }
    if dtype == "sequence_collection" {
        limitations.push("Assembly-specific interpretations require a user-confirmed genome_assembly classification.".into());
    }
    ResultDoc {
        engine_version: env!("CARGO_PKG_VERSION"),
        input_format: fmt.into(),
        dataset_type: dtype,
        sequence_count: seqs.len(),
        total_bases: total,
        valid_iupac_bases: valid_iupac,
        canonical_bases: canonical,
        ambiguous_bases: ambiguous,
        ambiguous_percent: if total > 0 {
            Some(ambiguous as f64 / total as f64 * 100.)
        } else {
            None
        },
        invalid_symbols: invalid,
        missing_identifiers,
        duplicate_identifiers,
        duplicate_rate_percent: unique
            .values()
            .filter(|count| **count > 1)
            .map(|count| count - 1)
            .sum::<usize>() as f64
            / seqs.len() as f64
            * 100.,
        nucleotide_counts: ["A", "C", "G", "T"]
            .into_iter()
            .enumerate()
            .map(|(i, base)| (base.to_string(), nucleotide_counts[i]))
            .collect(),
        ambiguity_symbol_counts: b"NRYSWKMBDHV"
            .iter()
            .enumerate()
            .map(|(i, symbol)| ((*symbol as char).to_string(), ambiguity_counts[i]))
            .collect(),
        gc_percent: if canonical > 0 {
            Some(gc as f64 / canonical as f64 * 100.)
        } else {
            None
        },
        at_percent: if canonical > 0 {
            Some(at as f64 / canonical as f64 * 100.)
        } else {
            None
        },
        length: LengthStats {
            min: *sorted.first().unwrap_or(&0),
            max: *sorted.last().unwrap_or(&0),
            mean,
            median,
            population_std_dev,
            percentiles,
        },
        n50,
        n75,
        n90,
        l50,
        l75,
        l90,
        nx_curve,
        gc_histogram: gc_hist,
        length_histogram: lh,
        k,
        top_kmers: top,
        top_canonical_kmers: canonical_top,
        kmer_spectrum: spectrum.into_iter().collect(),
        kmer_gc_heatmap: gc_heat
            .into_iter()
            .map(|((gc_count, abundance), distinct)| (gc_count, abundance, distinct))
            .collect(),
        duplicate_sequences: unique.values().filter(|x| **x > 1).map(|x| x - 1).sum(),
        reverse_complement_duplicate_sequences: reverse_complement_unique
            .values()
            .filter(|x| **x > 1)
            .map(|x| x - 1)
            .sum(),
        low_complexity_region_count: records
            .iter()
            .map(|record| record.low_complexity_regions.len())
            .sum(),
        low_complexity_sequence_count: records
            .iter()
            .filter(|record| !record.low_complexity_regions.is_empty())
            .count(),
        duplicated_bases,
        records,
        fastq,
        limitations,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn fasta_analysis_reports_independent_expected_values() {
        let (records, qualities) = parse(
            Box::new(BufReader::new(Cursor::new(
                b">alpha\nACGT\n>beta\nGGGG\n>copy\nACGT\n",
            ))),
            "fasta",
        )
        .unwrap();
        let result = analyze(records, qualities, "fasta", "genome_assembly".into(), 2);
        assert_eq!(result.sequence_count, 3);
        assert_eq!(result.total_bases, 12);
        assert!((result.gc_percent.unwrap() - 66.6666666667).abs() < 1e-8);
        assert_eq!(result.length.mean, 4.0);
        assert_eq!(result.length.median, 4.0);
        assert_eq!(result.n50, Some(4));
        assert_eq!(result.n90, Some(4));
        assert_eq!(result.l50, Some(2));
        assert_eq!(result.duplicate_sequences, 1);
        assert!((result.duplicate_rate_percent - 33.3333333333).abs() < 1e-8);
        assert_eq!(result.nucleotide_counts["A"], 2);
        assert_eq!(result.nucleotide_counts["G"], 6);
        assert_eq!(result.missing_identifiers, 0);
        assert_eq!(result.duplicate_identifiers, 0);
        assert_eq!(result.length.percentiles["p95"], 4);
        assert_eq!(
            result.top_kmers.iter().find(|(k, _)| k == "AC").unwrap().1,
            2
        );
        assert_eq!(
            result
                .top_canonical_kmers
                .iter()
                .find(|(k, _)| k == "AC")
                .unwrap()
                .1,
            4
        );
        assert!(
            result
                .kmer_spectrum
                .iter()
                .any(|(abundance, _)| *abundance == 4)
        );
        assert!(
            result
                .kmer_gc_heatmap
                .iter()
                .any(|(gc, abundance, _)| *gc == 1 && *abundance == 4)
        );
    }

    #[test]
    fn low_complexity_regions_use_zero_based_half_open_windows() {
        let sequence = [vec![b'A'; 150], b"ACGT".repeat(38)].concat();
        let regions = find_low_complexity_regions(&sequence);
        assert_eq!(regions.len(), 1);
        assert_eq!((regions[0].start, regions[0].end), (0, 175));
        assert!(regions[0].minimum_entropy < 0.01);
        assert!(find_low_complexity_regions(&b"ACGT".repeat(40)).is_empty());
    }

    #[test]
    fn reverse_complement_equivalence_is_counted_separately_from_exact_duplicates() {
        let result = analyze(
            vec![
                ("forward".into(), b"AACCGT".to_vec()),
                ("reverse".into(), b"ACGGTT".to_vec()),
            ],
            vec![],
            "fasta",
            "sequence_collection".into(),
            3,
        );
        assert_eq!(result.duplicate_sequences, 0);
        assert_eq!(result.reverse_complement_duplicate_sequences, 1);
    }

    #[test]
    fn fastq_quality_uses_phred_33_and_is_not_inferred_for_fasta() {
        let (records, qualities) = parse(
            Box::new(BufReader::new(Cursor::new(b"@r1\nACGT\n+\nIIII\n"))),
            "fastq",
        )
        .unwrap();
        let result = analyze(records, qualities, "fastq", "raw_reads".into(), 3);
        let stats = result.fastq.unwrap();
        assert_eq!(stats.mean_phred, 40.0);
        assert_eq!(stats.q20_percent, 100.0);
        assert_eq!(stats.q30_percent, 100.0);
    }

    #[test]
    fn invalid_symbols_are_separate_from_iupac_ambiguity() {
        let result = analyze(
            vec![("x".into(), b"ACNTZ".to_vec())],
            vec![],
            "fasta",
            "sequence_collection".into(),
            2,
        );
        assert_eq!(result.canonical_bases, 3);
        assert_eq!(result.ambiguous_bases, 1);
        assert_eq!(result.ambiguous_percent, Some(20.0));
        assert_eq!(result.invalid_symbols, 1);
        assert_eq!(result.ambiguity_symbol_counts["N"], 1);
    }

    #[test]
    fn sequence_identifiers_are_counted_separately_from_content_duplicates() {
        let result = analyze(
            vec![
                ("same first description".into(), b"ACGT".to_vec()),
                ("same second description".into(), b"TGCA".to_vec()),
                ("".into(), b"AAAA".to_vec()),
            ],
            vec![],
            "fasta",
            "sequence_collection".into(),
            2,
        );
        assert_eq!(result.duplicate_identifiers, 1);
        assert_eq!(result.missing_identifiers, 1);
        assert_eq!(result.duplicate_sequences, 0);
    }

    #[test]
    fn n_and_l_statistics_cross_known_cumulative_thresholds() {
        assert_eq!(n_stat(&[4, 3, 2, 1], 0.5), (Some(3), Some(2)));
        assert_eq!(n_stat(&[4, 3, 2, 1], 0.75), (Some(2), Some(3)));
    }

    #[test]
    fn assembly_statistics_are_not_applied_to_generic_collections() {
        let seqs = vec![
            ("a".into(), b"AAAA".to_vec()),
            ("b".into(), b"CCCC".to_vec()),
        ];
        let result = analyze(seqs, vec![], "fasta", "sequence_collection".into(), 2);
        assert_eq!(result.n50, None);
        assert_eq!(result.l50, None);
    }
}
