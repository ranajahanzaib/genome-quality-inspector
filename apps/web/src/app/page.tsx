"use client";

import { scaleLinear } from "d3-scale";
import type { ChangeEvent } from "react";
import { useCallback, useEffect, useState } from "react";

type RecordRow = {
  id: string;
  length: number;
  gc_percent: number | null;
  ambiguous_bases: number;
  invalid_symbols: number;
  shannon_entropy: number | null;
  max_homopolymer: number;
  low_complexity_regions?: {
    start: number;
    end: number;
    minimum_entropy: number;
    method: string;
    threshold_bits: number;
  }[];
  hash: string;
};
type Analysis = {
  input_format: string;
  dataset_type: string;
  sequence_count: number;
  total_bases: number;
  valid_iupac_bases: number;
  canonical_bases: number;
  ambiguous_bases: number;
  invalid_symbols: number;
  low_complexity_region_count?: number;
  low_complexity_sequence_count?: number;
  gc_percent: number | null;
  at_percent: number | null;
  length: { min: number; max: number; mean: number; median: number };
  n50: number | null;
  n75: number | null;
  n90?: number | null;
  l50: number | null;
  l75: number | null;
  l90?: number | null;
  nx_curve?: [number, number][];
  gc_histogram: number[];
  length_histogram: Record<string, number>;
  k: number;
  top_kmers: [string, number][];
  top_canonical_kmers?: [string, number][];
  kmer_spectrum?: [number, number][];
  kmer_gc_heatmap?: [number, number, number][];
  duplicate_sequences: number;
  duplicated_bases: number;
  reverse_complement_duplicate_sequences?: number;
  records?: RecordRow[];
  fastq: {
    mean_phred: number;
    per_base_mean_phred: number[];
    per_base_composition?: Record<string, number>[];
    reads_with_n: number;
  } | null;
  limitations: string[];
};
type DetailedAnalysis = Analysis & {
  ambiguous_percent?: number | null;
  missing_identifiers?: number;
  duplicate_identifiers?: number;
  duplicate_rate_percent?: number;
  nucleotide_counts?: Record<string, number>;
  ambiguity_symbol_counts?: Record<string, number>;
  length: Analysis["length"] & {
    population_std_dev?: number;
    percentiles?: Record<string, number>;
  };
  fastq: {
    mean_phred: number;
    q20_percent?: number;
    q30_percent?: number;
    per_base_mean_phred: number[];
    per_base_composition?: Record<string, number>[];
    reads_with_n: number;
  } | null;
};
type Sampling = {
  sampled: boolean;
  portion_limited?: boolean;
  bytes_read?: number;
  sample_size: number;
  source_record_count: number;
  method: string;
  seed: number | null;
  source_file_size_bytes: number;
  source_path?: string;
  source_oid?: string | null;
};
type Dataset = {
  id: string;
  name: string;
  description: string;
  tags?: string[];
  filename: string;
  format: string;
  dataset_type: string;
  data_source?: string;
  source_revision?: string | null;
  sampling?: Sampling | null;
  bytes: number;
  status: string;
  error: string | null;
  created_at: string;
  analysis: Analysis | null;
};
type AnalysisRun = {
  id: string;
  dataset_id: string;
  status: string;
  config: { k: number; dataset_type: string };
  error: string | null;
  created_at: string;
  completed_at: string | null;
};
type FindingRow = {
  id: string;
  code: string;
  severity: string;
  message: string;
  status: string;
  value: number | null;
};
type SequenceWindow = {
  record_id: string;
  length: number;
  start: number;
  end: number;
  sequence: string;
};
type HubFile = {
  path: string;
  size_bytes: number | null;
  revision: string;
  oid: string | null;
  format: string;
};
type HubMetadata = {
  columns: string[];
  rows: Record<string, string>[];
  truncated: boolean;
};
type CompareItem = {
  id: string;
  name: string;
  dataset_type: string;
  sequence_count: number | null;
  total_bases: number | null;
  gc_percent: number | null;
  ambiguous_percent: number | null;
  duplicate_rate_percent: number | null;
  length_mean: number | null;
  length_median: number | null;
  n50: number | null;
  sampled: boolean;
};
type Comparison = {
  items: CompareItem[];
  baseline_id: string;
  comparisons: {
    baseline_id: string;
    dataset_id: string;
    deltas: Record<string, number | null>;
  }[];
  warnings: string[];
};
type SavedComparison = {
  id: string;
  name: string;
  created_at: string;
  result: Comparison;
};
type TaxonomySummary = {
  source: string | null;
  release: string | null;
  items: {
    taxon_name: string;
    taxon_id: string | null;
    rank: string | null;
    sequence_count: number;
    nucleotide_count: number;
  }[];
  sequence_count: number;
  mapped_sequence_count: number;
  unmapped_sequence_count: number;
  mapped_nucleotide_count: number;
  unmapped_nucleotide_count: number;
  interpretation: string;
};
const comparisonMetrics: {
  key: keyof Pick<
    CompareItem,
    | "sequence_count"
    | "total_bases"
    | "gc_percent"
    | "ambiguous_percent"
    | "duplicate_rate_percent"
    | "length_mean"
    | "length_median"
    | "n50"
  >;
  label: string;
  percent?: boolean;
}[] = [
  { key: "sequence_count", label: "Sequences" },
  { key: "total_bases", label: "Total bases" },
  { key: "gc_percent", label: "GC content", percent: true },
  { key: "ambiguous_percent", label: "Ambiguous bases", percent: true },
  {
    key: "duplicate_rate_percent",
    label: "Exact duplicate rate",
    percent: true,
  },
  { key: "length_mean", label: "Mean length (bp)" },
  { key: "length_median", label: "Median length (bp)" },
  { key: "n50", label: "N50 (bp)" },
];
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const fmt = (n: number) => new Intl.NumberFormat().format(n);
const pct = (n: number | null) => (n === null ? "N/A" : `${n.toFixed(2)}%`);

export default function Home() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<Dataset | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [apiOnline, setApiOnline] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [datasetType, setDatasetType] = useState("auto");
  const [uploadTags, setUploadTags] = useState("");
  const [kValue, setKValue] = useState("21");
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [seqFilter, setSeqFilter] = useState("");
  const [page, setPage] = useState(0);
  const [excludeOutliers, setExcludeOutliers] = useState(false);
  const [sequenceRows, setSequenceRows] = useState<RecordRow[]>([]);
  const [sequenceTotal, setSequenceTotal] = useState(0);
  const [hubOpen, setHubOpen] = useState(false);
  const [hubCategory, setHubCategory] = useState("fasta");
  const [hubFiles, setHubFiles] = useState<HubFile[]>([]);
  const [hubRevision, setHubRevision] = useState("");
  const [hubLoading, setHubLoading] = useState(false);
  const [importingPath, setImportingPath] = useState("");
  const [hubHasMore, setHubHasMore] = useState(false);
  const [hubMetadata, setHubMetadata] = useState<HubMetadata | null>(null);
  const [findings, setFindings] = useState<FindingRow[]>([]);
  const [sequenceWindow, setSequenceWindow] = useState<SequenceWindow | null>(
    null,
  );
  const [windowStart, setWindowStart] = useState("0");
  const [taxonomy, setTaxonomy] = useState<TaxonomySummary | null>(null);
  const [metadataBusy, setMetadataBusy] = useState(false);
  const [hubSubpath, setHubSubpath] = useState("");
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [compareBusy, setCompareBusy] = useState(false);
  const [savedComparisons, setSavedComparisons] = useState<SavedComparison[]>(
    [],
  );
  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/datasets`);
      if (!r.ok)
        throw new Error("API unavailable. Start the local API to continue.");
      const data = await r.json();
      setDatasets(data.items);
      setSelected((current) =>
        current && data.items.some((d: Dataset) => d.id === current)
          ? current
          : (data.items[0]?.id ?? null),
      );
      setError("");
      setApiOnline(true);
    } catch (e) {
      setError((e as Error).message);
      setApiOnline(false);
    }
  }, []);
  useEffect(() => {
    const initial = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(initial);
  }, [refresh]);
  useEffect(() => {
    const timer = setInterval(() => void refresh(), 2500);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const load = async () => {
      try {
        const r = await fetch(`${API}/api/v1/datasets/${selected}`);
        const data = await r.json();
        if (active && r.ok) setSelectedDetail(data);
      } catch {
        if (active) setSelectedDetail(null);
      }
    };
    const initial = setTimeout(() => void load(), 0);
    const timer = setInterval(() => void load(), 2500);
    return () => {
      active = false;
      clearTimeout(initial);
      clearInterval(timer);
    };
  }, [selected]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const load = async () => {
      try {
        const r = await fetch(`${API}/api/v1/datasets/${selected}/analyses`);
        const data = await r.json();
        if (active && r.ok) setRuns(data.items);
      } catch {
        if (active) setRuns([]);
      }
    };
    const initial = setTimeout(() => void load(), 0);
    const timer = setInterval(() => void load(), 2500);
    return () => {
      active = false;
      clearTimeout(initial);
      clearInterval(timer);
    };
  }, [selected]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    void fetch(`${API}/api/v1/datasets/${selected}/findings`)
      .then((r) => r.json())
      .then((data) => {
        if (active) setFindings(data.items ?? []);
      })
      .catch(() => {
        if (active) setFindings([]);
      });
    return () => {
      active = false;
    };
  }, [selected, selectedDetail?.status]);
  useEffect(() => {
    if (!compareOpen) return;
    let active = true;
    void fetch(`${API}/api/v1/comparisons?limit=50`)
      .then((r) => r.json())
      .then((data) => {
        if (active) setSavedComparisons(data.items ?? []);
      })
      .catch(() => {
        if (active) setSavedComparisons([]);
      });
    return () => {
      active = false;
    };
  }, [compareOpen, comparison]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    void fetch(`${API}/api/v1/datasets/${selected}/taxonomy`)
      .then((r) => r.json())
      .then((data) => {
        if (active) setTaxonomy(data.source ? data : null);
      })
      .catch(() => {
        if (active) setTaxonomy(null);
      });
    return () => {
      active = false;
    };
  }, [selected, selectedDetail?.status]);
  const dataset =
    selectedDetail?.id === selected
      ? selectedDetail
      : (datasets.find((d) => d.id === selected) ?? null);
  const analysis = (dataset?.analysis as DetailedAnalysis | null) ?? null;
  const hasAnalysis = Boolean(analysis);
  useEffect(() => {
    if (!selected || !hasAnalysis) return;
    let active = true;
    const query = new URLSearchParams({
      q: seqFilter,
      offset: String(page * 12),
      limit: "12",
      exclude_outliers: String(excludeOutliers),
    });
    void fetch(`${API}/api/v1/datasets/${selected}/sequences?${query}`)
      .then(async (response) => {
        const data = await response.json();
        if (active && response.ok) {
          setSequenceRows(data.items);
          setSequenceTotal(data.total);
        }
      })
      .catch(() => {
        if (active) {
          setSequenceRows([]);
          setSequenceTotal(0);
        }
      });
    return () => {
      active = false;
    };
  }, [selected, hasAnalysis, seqFilter, page, excludeOutliers]);
  const filtered = sequenceRows;
  async function loadHub(category = hubCategory, subpath = hubSubpath) {
    setHubLoading(true);
    setError("");
    setHubMetadata(null);
    try {
      const r = await fetch(
        `${API}/api/v1/integrations/opengenome2/files?category=${category}&subpath=${encodeURIComponent(category === "metadata" ? "" : subpath)}&limit=100`,
      );
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Could not browse OpenGenome2");
      setHubFiles(data.files);
      setHubRevision(data.revision);
      setHubHasMore(data.has_more);
      setHubCategory(category);
      if (category === "metadata") {
        const mr = await fetch(
          `${API}/api/v1/integrations/opengenome2/metadata?revision=${data.revision}&limit=50`,
        );
        const md = await mr.json();
        if (!mr.ok)
          throw new Error(md.detail || "Could not preview species metadata");
        setHubMetadata(md);
        setHubRevision(md.revision);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setHubLoading(false);
    }
  }
  async function importHubFile(file: HubFile) {
    setImportingPath(file.path);
    setError("");
    try {
      const jsonl = hubCategory === "jsonl";
      const route = jsonl ? "import-jsonl" : "import";
      const r = await fetch(`${API}/api/v1/integrations/opengenome2/${route}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          jsonl
            ? {
                path: file.path,
                revision: file.revision,
                max_bytes: 16 * 1024 ** 2,
                sample_size: 10000,
                sample_seed: 42,
              }
            : {
                path: file.path,
                revision: file.revision,
                dataset_type: "sequence_collection",
                sample_size: 10000,
                sample_seed: 42,
              },
        ),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "OpenGenome2 import failed");
      const job = await fetch(`${API}/api/v1/datasets/${data.id}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ k: Number(kValue) }),
      });
      if (!job.ok) {
        const failure = await job.json();
        throw new Error(
          failure.detail || "Import succeeded but analysis could not start",
        );
      }
      setSelected(data.id);
      setPage(0);
      setHubOpen(false);
      setNotice(
        `${file.path} imported at pinned revision ${data.source_revision.slice(0, 12)} and analysis started.`,
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setImportingPath("");
    }
  }
  async function runComparison() {
    setCompareBusy(true);
    setError("");
    try {
      const r = await fetch(`${API}/api/v1/comparisons`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset_ids: compareIds }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Could not compare datasets");
      setComparison(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCompareBusy(false);
    }
  }
  async function setFindingStatus(
    id: string,
    status: "acknowledged" | "dismissed",
  ) {
    const r = await fetch(`${API}/api/v1/findings/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!r.ok) {
      setError("Could not update finding.");
      return;
    }
    setFindings((current) =>
      current.map((f) => (f.id === id ? { ...f, status } : f)),
    );
  }
  async function loadSequenceWindow(
    recordId: string,
    start = Number(windowStart),
  ) {
    if (!selected) return;
    const query = new URLSearchParams({
      record_id: recordId,
      start: String(start),
      end: String(start + 1000),
    });
    const r = await fetch(
      `${API}/api/v1/datasets/${selected}/sequence-window?${query}`,
    );
    const data = await r.json();
    if (!r.ok) {
      setError(data.detail || "Could not retrieve sequence window");
      return;
    }
    setSequenceWindow(data);
  }
  async function uploadTaxonomyMetadata(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !selected) return;
    setMetadataBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("source", "user_metadata");
      const r = await fetch(`${API}/api/v1/datasets/${selected}/metadata`, {
        method: "POST",
        body,
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Could not import metadata");
      const tr = await fetch(`${API}/api/v1/datasets/${selected}/taxonomy`);
      const summary = await tr.json();
      if (!tr.ok)
        throw new Error(
          summary.detail || "Metadata imported but taxonomy summary failed",
        );
      setTaxonomy(summary);
      setNotice(`Imported ${fmt(data.mapping_count)} taxonomy mappings.`);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setMetadataBusy(false);
      e.target.value = "";
    }
  }
  async function loadDemo() {
    setDemoBusy(true);
    setError("");
    try {
      const r = await fetch(`${API}/api/v1/demo/seed`, { method: "POST" });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Could not load demo datasets");
      const collection = data.items.find(
        (item: Dataset) => item.filename === "sequence-collection.fasta",
      );
      if (collection) setSelected(collection.id);
      const running = data.items.some(
        (item: Dataset) =>
          item.status === "queued" || item.status === "running",
      );
      setNotice(
        running
          ? "Synthetic demo datasets are ready. The Rust engine is analyzing the fixtures."
          : "Synthetic demo datasets are ready. Select one from the library to explore its metrics.",
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDemoBusy(false);
    }
  }
  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const body = new FormData();
      files.forEach((file) =>
        body.append(files.length > 1 ? "files" : "file", file),
      );
      if (datasetType !== "auto") body.append("dataset_type", datasetType);
      if (uploadTags.trim()) body.append("tags", uploadTags);
      const endpoint =
        files.length > 1
          ? `${API}/api/v1/datasets/batch`
          : `${API}/api/v1/datasets`;
      const r = await fetch(endpoint, { method: "POST", body });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Upload failed");
      const items: Dataset[] = files.length > 1 ? data.items : [data];
      for (const item of items) {
        const job = await fetch(`${API}/api/v1/datasets/${item.id}/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ k: Number(kValue) }),
        });
        if (!job.ok) {
          const failure = await job.json();
          throw new Error(
            `${item.filename} uploaded but analysis could not start: ${failure.detail || "unknown error"}`,
          );
        }
      }
      setSelected(items[0].id);
      setNotice(
        `${items.length} sequence file${items.length === 1 ? "" : "s"} uploaded. Analysis started.`,
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }
  async function rerun() {
    if (!dataset) return;
    setError("");
    const r = await fetch(`${API}/api/v1/datasets/${dataset.id}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ k: Number(kValue) }),
    });
    if (!r.ok) {
      const d = await r.json();
      setError(d.detail || "Could not start analysis");
    } else setNotice("Analysis queued.");
    await refresh();
  }
  async function remove() {
    if (!dataset) return;
    const r = await fetch(`${API}/api/datasets/${dataset.id}`, {
      method: "DELETE",
    });
    if (!r.ok) {
      setError("Could not delete dataset.");
      return;
    }
    setSelected(null);
    setNotice("Dataset and uploaded file deleted.");
    await refresh();
  }
  async function exportReport() {
    if (!dataset) return;
    const r = await fetch(`${API}/api/datasets/${dataset.id}/report`);
    if (!r.ok) {
      setError("Report is not available yet.");
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${dataset.name.replace(/[^a-z0-9-_]+/gi, "-")}-report.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">g</div>
          <div>
            <strong>
              genome<span>.</span>
            </strong>
            <small>QUALITY INSPECTOR</small>
          </div>
        </div>
        <div className="side-label">WORKSPACE</div>
        <div className="nav-active">
          <span className="nav-icon">▤</span> Datasets{" "}
          <span className="count">{datasets.length}</span>
        </div>
        <div className="side-label library-label">
          LIBRARY{" "}
          <button
            onClick={() => document.getElementById("file")?.click()}
            title="Import dataset"
          >
            ＋
          </button>
        </div>
        <div className="dataset-list">
          {datasets.map((d) => (
            <button
              className={`dataset-link ${selected === d.id ? "selected" : ""}`}
              key={d.id}
              onClick={() => {
                setSelected(d.id);
                setPage(0);
              }}
            >
              <i
                className={
                  d.status === "complete"
                    ? "dot green"
                    : d.status === "failed"
                      ? "dot red"
                      : "dot amber"
                }
              />
              <span>
                <b>{d.name}</b>
                <small>
                  {d.format.toUpperCase()} · {d.status}
                </small>
              </span>
            </button>
          ))}
        </div>
        <div className="side-bottom">
          <div className="worker-dot" /> Local analysis engine <span>●</span>
          <small>Private workspace</small>
        </div>
      </aside>
      <section className="main-area">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span> <b>{dataset?.name || "Datasets"}</b>
          </div>
          <div className="top-actions">
            <span className="api-status">
              <i style={{ background: apiOnline ? "#36a678" : "#cc7167" }} />{" "}
              API {apiOnline ? "connected" : "disconnected"}
            </span>
            <div className="avatar" aria-label="Local workspace">
              G
            </div>
          </div>
        </header>
        <div className="content">
          {error && (
            <div className="alert error">
              {error}
              <button onClick={() => void refresh()}>Retry</button>
            </div>
          )}
          {notice && (
            <div className="alert success">
              {notice}
              <button onClick={() => setNotice("")}>×</button>
            </div>
          )}
          {hubOpen && (
            <div
              className="hub-backdrop"
              role="presentation"
              onMouseDown={(e) => {
                if (e.target === e.currentTarget) setHubOpen(false);
              }}
            >
              <section
                className="hub-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="hub-title"
              >
                <div className="panel-heading">
                  <div>
                    <div className="eyebrow">PUBLIC DATASET CATALOG</div>
                    <h2 id="hub-title">OpenGenome2</h2>
                    <p>
                      Browse files from arcinstitute/opengenome2. Imports are
                      pinned to a repository revision.
                    </p>
                  </div>
                  <button
                    className="hub-close"
                    aria-label="Close catalog"
                    onClick={() => setHubOpen(false)}
                  >
                    ×
                  </button>
                </div>
                <div className="hub-meta">
                  <span>Apache-2.0</span>
                  <code>{hubRevision || "Resolving revision…"}</code>
                </div>
                <div className="hub-tabs">
                  {[
                    ["fasta", "FASTA shards"],
                    ["jsonl", "JSONL files"],
                    ["metadata", "Metadata"],
                  ].map(([category, label]) => (
                    <button
                      key={category}
                      className={hubCategory === category ? "active" : ""}
                      onClick={() => void loadHub(category)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {hubCategory !== "metadata" && (
                  <div className="hub-path">
                    <input
                      aria-label="Repository subfolder"
                      placeholder="Optional folder, for example bacteria"
                      value={hubSubpath}
                      onChange={(e) => setHubSubpath(e.target.value)}
                    />
                    <button
                      className="button secondary"
                      onClick={() => void loadHub(hubCategory, hubSubpath)}
                    >
                      Browse folder
                    </button>
                  </div>
                )}
                {hubCategory !== "fasta" && (
                  <div className="hub-note">
                    JSONL import reads at most the first 16 MiB of complete
                    lines from the selected shard, extracts nucleotide examples,
                    and preserves source tags and special tokens.
                  </div>
                )}
                {hubLoading ? (
                  <div className="empty-inline">Loading repository files…</div>
                ) : (
                  <div className="hub-files">
                    {hubFiles.map((file) => (
                      <div className="hub-file" key={file.path}>
                        <div>
                          <b>{file.path}</b>
                          <small>
                            {file.size_bytes === null
                              ? "size unavailable"
                              : `${(file.size_bytes / 1024 / 1024).toFixed(1)} MB`}{" "}
                            · {file.format.toUpperCase()}
                          </small>
                        </div>
                        <button
                          className="button primary"
                          disabled={
                            hubCategory === "metadata" ||
                            !!importingPath ||
                            file.size_bytes === null ||
                            file.size_bytes >
                              (hubCategory === "jsonl"
                                ? 16 * 1024 ** 2
                                : 1024 ** 3)
                          }
                          onClick={() => void importHubFile(file)}
                        >
                          {hubCategory === "metadata"
                            ? "Preview only"
                            : importingPath === file.path
                              ? "Importing…"
                              : file.size_bytes !== null &&
                                  file.size_bytes >
                                    (hubCategory === "jsonl"
                                      ? 16 * 1024 ** 2
                                      : 1024 ** 3)
                                ? hubCategory === "jsonl"
                                  ? "Over 16 MiB"
                                  : "Over 1 GB"
                                : hubCategory === "jsonl"
                                  ? "Import portion"
                                  : "Import FASTA"}
                        </button>
                      </div>
                    ))}
                    {!hubFiles.length && (
                      <div className="empty-inline">
                        No files in this catalog view.
                      </div>
                    )}
                  </div>
                )}
                {hubCategory === "metadata" && hubMetadata && (
                  <div className="metadata-preview">
                    <div className="hub-note">
                      Previewing {hubMetadata.rows.length} rows from the source
                      metadata schema. Values are source annotations, not
                      classifications computed by this app.
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            {hubMetadata.columns.map((column) => (
                              <th key={column}>{column}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {hubMetadata.rows.map((row, index) => (
                            <tr key={index}>
                              {hubMetadata.columns.map((column) => (
                                <td key={column}>{row[column] || "—"}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {hubMetadata.truncated && (
                      <small>Preview truncated to the first 50 rows.</small>
                    )}
                  </div>
                )}
                {hubHasMore && (
                  <div className="hub-note">Showing the first 100 files.</div>
                )}
                <div className="hub-footer">
                  Selected FASTA shards use deterministic record sampling; JSONL
                  imports read a bounded 16 MiB prefix and sample
                  sequence-bearing complete lines (seed 42). Set HF_TOKEN in the
                  API environment for gated access.
                </div>
              </section>
            </div>
          )}
          {compareOpen && (
            <div
              className="hub-backdrop"
              role="presentation"
              onMouseDown={(e) => {
                if (e.target === e.currentTarget) setCompareOpen(false);
              }}
            >
              <section
                className="hub-dialog compare-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="compare-title"
              >
                <div className="panel-heading">
                  <div>
                    <div className="eyebrow">DATASET ANALYSIS</div>
                    <h2 id="compare-title">Compare datasets</h2>
                    <p>
                      Select two to four completed analyses. The first selected
                      dataset is the baseline.
                    </p>
                  </div>
                  <button
                    className="hub-close"
                    aria-label="Close comparison"
                    onClick={() => setCompareOpen(false)}
                  >
                    ×
                  </button>
                </div>
                <div className="compare-select">
                  {datasets.map((item) => (
                    <label key={item.id}>
                      <input
                        type="checkbox"
                        checked={compareIds.includes(item.id)}
                        disabled={
                          item.status !== "complete" ||
                          (!compareIds.includes(item.id) &&
                            compareIds.length >= 4)
                        }
                        onChange={(e) => {
                          setCompareIds((current) =>
                            e.target.checked
                              ? [...current, item.id]
                              : current.filter((id) => id !== item.id),
                          );
                          setComparison(null);
                        }}
                      />
                      <span>
                        <b>{item.name}</b>
                        <small>
                          {item.dataset_type.replaceAll("_", " ")} ·{" "}
                          {item.status}
                        </small>
                      </span>
                    </label>
                  ))}
                </div>
                <button
                  className="button primary compare-run"
                  disabled={compareIds.length < 2 || compareBusy}
                  onClick={() => void runComparison()}
                >
                  {compareBusy ? "Comparing…" : "Compare selected datasets"}
                </button>
                {savedComparisons.length > 0 && (
                  <div className="saved-comparisons">
                    <b>Saved comparisons</b>
                    {savedComparisons.map((saved) => (
                      <button
                        key={saved.id}
                        onClick={() => {
                          setComparison(saved.result);
                          setCompareIds(
                            saved.result.items.map((item) => item.id),
                          );
                        }}
                      >
                        {saved.name} ·{" "}
                        {new Date(saved.created_at).toLocaleDateString()}
                      </button>
                    ))}
                  </div>
                )}
                {comparison && (
                  <div className="comparison-results">
                    {comparison.warnings.map((warning) => (
                      <div className="hub-note" key={warning}>
                        {warning}
                      </div>
                    ))}
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>METRIC</th>
                            {comparison.items.map((item) => (
                              <th key={item.id}>
                                {item.name}
                                {item.id === comparison.baseline_id
                                  ? " · BASELINE"
                                  : ""}
                                {item.sampled ? " · SAMPLED" : ""}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {comparisonMetrics.map((metric) => (
                            <tr key={metric.key}>
                              <td>{metric.label}</td>
                              {comparison.items.map((item) => {
                                const value = item[metric.key];
                                return (
                                  <td key={item.id}>
                                    {value === null
                                      ? "N/A"
                                      : metric.percent
                                        ? `${value.toFixed(2)}%`
                                        : fmt(value)}
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <small>
                      Differences are descriptive. Input type and sampling may
                      affect comparability.
                    </small>
                  </div>
                )}
              </section>
            </div>
          )}
          {!datasets.length ? (
            <div className="welcome">
              <div className="eyebrow">SEQUENCE QUALITY WORKSPACE</div>
              <h1>
                Make every base
                <br />
                <em>count.</em>
              </h1>
              <p>
                Audit nucleotide datasets with reproducible, transparent
                analysis. Upload a FASTA or FASTQ file to get started.
              </p>
              <label className={`upload-card ${busy ? "disabled" : ""}`}>
                <input
                  id="file"
                  type="file"
                  multiple
                  accept=".fa,.fasta,.fna,.ffn,.fq,.fastq,.gz"
                  onChange={upload}
                  disabled={busy}
                />
                <span className="upload-symbol">↑</span>
                <b>{busy ? "Uploading…" : "Import a sequence file"}</b>
                <small>FASTA / FASTQ, optionally gzip compressed</small>
                <span className="browse">Browse files</span>
              </label>
              <button
                className="button secondary hub-start"
                onClick={() => void loadDemo()}
                disabled={demoBusy}
              >
                {demoBusy ? "Loading demo datasets…" : "Load sample datasets"}
              </button>
              <button
                className="button secondary hub-start"
                onClick={() => {
                  setHubOpen(true);
                  void loadHub("fasta");
                }}
              >
                Browse OpenGenome2
              </button>
              <div className="science-note">
                <span>i</span> Samples are synthetic; displayed metrics are
                calculated from their records.
              </div>
            </div>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">DATASET OVERVIEW</div>
                  <h1>{dataset?.name || "Your datasets"}</h1>
                  <p>
                    {dataset
                      ? `${dataset.filename} · ${(dataset.bytes / 1024 / 1024).toFixed(2)} MB · ${dataset.dataset_type.replaceAll("_", " ")}`
                      : "Select a dataset from your library."}
                  </p>
                </div>
                <div className="heading-actions">
                  <button
                    className="button secondary"
                    onClick={() => {
                      setHubOpen(true);
                      void loadHub("fasta");
                    }}
                  >
                    OpenGenome2
                  </button>
                  {dataset?.data_source === "built_in_demo" && (
                    <button
                      className="button secondary"
                      onClick={() => void loadDemo()}
                      disabled={demoBusy}
                    >
                      {demoBusy ? "Checking demos…" : "Ensure demo datasets"}
                    </button>
                  )}
                  <button
                    className="button secondary"
                    disabled={datasets.length < 2}
                    onClick={() => {
                      setCompareIds(selected ? [selected] : []);
                      setComparison(null);
                      setCompareOpen(true);
                    }}
                  >
                    Compare datasets
                  </button>
                  {dataset && (
                    <label className="button secondary">
                      {metadataBusy
                        ? "Importing metadata…"
                        : "Import taxonomy metadata"}
                      <input
                        type="file"
                        accept=".csv,.tsv,.txt"
                        onChange={uploadTaxonomyMetadata}
                        disabled={metadataBusy}
                      />
                    </label>
                  )}
                  <select
                    className="type-select"
                    value={datasetType}
                    onChange={(e) => setDatasetType(e.target.value)}
                    aria-label="Dataset type for next import"
                  >
                    <option value="auto">Auto classify</option>
                    <option value="sequence_collection">
                      Sequence collection
                    </option>
                    <option value="raw_reads">Raw reads</option>
                    <option value="genome_assembly">Genome assembly</option>
                    <option value="reference_genome">Reference genome</option>
                    <option value="training_corpus">Training corpus</option>
                    <option value="unknown">Unknown</option>
                  </select>
                  <label className="button secondary">
                    <input
                      type="file"
                      multiple
                      accept=".fa,.fasta,.fna,.ffn,.fq,.fastq,.gz"
                      onChange={upload}
                      disabled={busy}
                    />
                    ＋ Import
                  </label>
                  {dataset && (
                    <>
                      <button
                        className="button secondary"
                        onClick={exportReport}
                        disabled={!analysis}
                      >
                        ↓ Export report
                      </button>
                      <button
                        className="button primary"
                        onClick={rerun}
                        disabled={
                          dataset.status === "running" ||
                          dataset.status === "queued"
                        }
                      >
                        {dataset.status === "running" ||
                        dataset.status === "queued"
                          ? "◌ Analyzing"
                          : "↻ Reanalyze"}
                      </button>
                    </>
                  )}
                </div>
              </div>
              <div className="analysis-config">
                <label htmlFor="k-value">Analysis k-mer size</label>
                <select
                  id="k-value"
                  className="type-select"
                  value={kValue}
                  onChange={(e) => setKValue(e.target.value)}
                >
                  <option value="15">k = 15</option>
                  <option value="21">k = 21</option>
                  <option value="31">k = 31</option>
                </select>
                <small>
                  This setting applies to the next upload or reanalysis.
                </small>
                <label htmlFor="upload-tags">Dataset tags</label>
                <input
                  id="upload-tags"
                  className="search-input"
                  placeholder="comma-separated tags"
                  value={uploadTags}
                  onChange={(e) => setUploadTags(e.target.value)}
                />
              </div>
              {dataset?.data_source === "built_in_demo" && (
                <div className="sampling-banner">
                  <b>Synthetic demonstration data</b>
                  <span>
                    This fixture is synthetic. Every metric below is calculated
                    from its actual sequence records by the analysis engine.
                  </span>
                </div>
              )}
              {dataset && dataset.status !== "complete" && (
                <div className={`run-state ${dataset.status}`}>
                  <span className="spinner" />
                  <div>
                    <b>
                      {dataset.status === "failed"
                        ? "Analysis failed"
                        : dataset.status === "uploaded"
                          ? "Analysis not started"
                          : "Analysis in progress"}
                    </b>
                    <small>
                      {dataset.error ||
                        (dataset.status === "failed"
                          ? "Review the error, then re-run analysis."
                          : "The Rust engine is processing your sequence records. This view refreshes automatically.")}
                    </small>
                  </div>
                  {dataset.status === "uploaded" && (
                    <button onClick={rerun}>Start analysis</button>
                  )}
                </div>
              )}
              {analysis && (
                <>
                  {dataset?.sampling?.sampled && (
                    <div className="sampling-banner">
                      <b>Sampled source data</b>
                      <span>
                        {dataset.sampling.portion_limited
                          ? `Read ${fmt(dataset.sampling.bytes_read ?? 0)} bytes from the shard prefix; sampled ${fmt(dataset.sampling.sample_size)} of ${fmt(dataset.sampling.source_record_count)} sequence-bearing examples found in that portion (seed ${dataset.sampling.seed}). This is not a whole-shard total.`
                          : `Analyzed ${fmt(dataset.sampling.sample_size)} of ${fmt(dataset.sampling.source_record_count)} records from ${dataset.sampling.source_path} using deterministic reservoir sampling (seed ${dataset.sampling.seed}) at revision ${dataset.source_revision?.slice(0, 12)}.`}
                      </span>
                    </div>
                  )}
                  <div className="metrics-grid">
                    <Metric
                      label="SEQUENCES"
                      value={fmt(analysis.sequence_count)}
                      sub={`${dataset?.format.toUpperCase()} records`}
                      icon="▤"
                    />
                    <Metric
                      label="TOTAL BASES"
                      value={fmt(analysis.total_bases)}
                      sub={`${fmt(analysis.valid_iupac_bases)} valid IUPAC`}
                      icon="⌁"
                    />
                    <Metric
                      label="GC CONTENT"
                      value={pct(analysis.gc_percent)}
                      sub="Canonical bases only"
                      icon="◉"
                    />
                    <Metric
                      label="N50"
                      value={analysis.n50 === null ? "N/A" : fmt(analysis.n50)}
                      sub={
                        analysis.n50 === null
                          ? dataset?.dataset_type === "genome_assembly"
                            ? "N50 unavailable"
                            : "Assembly-only metric"
                          : `${analysis.l50} sequences to reach 50%`
                      }
                      icon="⌗"
                    />
                  </div>
                  <div className="chart-grid">
                    <section className="panel chart-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>GC distribution</h2>
                          <p>Share of sequences by rounded GC percentage</p>
                        </div>
                        <span className="panel-tag">
                          {analysis.sequence_count} sequences
                        </span>
                      </div>
                      <GcChart data={analysis.gc_histogram} />
                      <div className="chart-foot">
                        <span>0% GC</span>
                        <span>GC content</span>
                        <span>100% GC</span>
                      </div>
                    </section>
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Sequence profile</h2>
                          <p>Summary statistics</p>
                        </div>
                        <span className="panel-tag">
                          {analysis.input_format.toUpperCase()}
                        </span>
                      </div>
                      <div className="stat-rows">
                        <Stat
                          label="Mean length"
                          value={`${fmt(Math.round(analysis.length.mean))} bp`}
                        />
                        <Stat
                          label="Median length"
                          value={`${fmt(Math.round(analysis.length.median))} bp`}
                        />
                        <Stat
                          label="Length range"
                          value={`${fmt(analysis.length.min)}–${fmt(analysis.length.max)} bp`}
                        />
                        <Stat
                          label="N75 / L75"
                          value={
                            analysis.n75 === null
                              ? "N/A"
                              : `${fmt(analysis.n75)} bp / ${analysis.l75}`
                          }
                        />
                        <Stat
                          label="N90 / L90"
                          value={
                            analysis.n90 == null
                              ? "N/A"
                              : `${fmt(analysis.n90)} bp / ${analysis.l90}`
                          }
                        />
                        <Stat
                          label="Exact duplicates"
                          value={fmt(analysis.duplicate_sequences)}
                        />
                        <Stat
                          label="Ambiguous bases"
                          value={fmt(analysis.ambiguous_bases)}
                        />
                        <Stat
                          label="Invalid symbols"
                          value={fmt(analysis.invalid_symbols)}
                        />
                        {analysis.fastq && (
                          <Stat
                            label="Mean Phred score"
                            value={analysis.fastq.mean_phred.toFixed(1)}
                          />
                        )}
                      </div>
                    </section>
                  </div>
                  <section className="panel chart-panel length-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Sequence length distribution</h2>
                        <p>Count of records per 100 bp interval</p>
                      </div>
                      <span className="panel-tag">
                        {analysis.length.min}–{fmt(analysis.length.max)} bp
                      </span>
                    </div>
                    <LengthChart data={analysis.length_histogram} />
                  </section>
                  {analysis.nx_curve && analysis.nx_curve.length > 0 && (
                    <section className="panel chart-panel length-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Cumulative Nx curve</h2>
                          <p>
                            Contig length at cumulative assembly size thresholds
                          </p>
                        </div>
                        <span className="panel-tag">ASSEMBLY</span>
                      </div>
                      <div className="stat-rows">
                        {analysis.nx_curve
                          .filter(([percent]) => percent % 20 === 0)
                          .map(([percent, length]) => (
                            <Stat
                              key={percent}
                              label={`N${percent}`}
                              value={`${fmt(length)} bp`}
                            />
                          ))}
                      </div>
                      <NxChart data={analysis.nx_curve} />
                    </section>
                  )}
                  {analysis.fastq && (
                    <section className="panel chart-panel length-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Per-base read quality</h2>
                          <p>Mean Phred+33 score by position across reads</p>
                        </div>
                        <span className="panel-tag">
                          {analysis.fastq.per_base_mean_phred.length} positions
                        </span>
                      </div>
                      <QualityChart data={analysis.fastq.per_base_mean_phred} />
                    </section>
                  )}
                  {analysis.fastq?.per_base_composition && (
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Per-cycle FASTQ composition</h2>
                          <p>
                            Base counts at each read position (first 30 cycles)
                          </p>
                        </div>
                      </div>
                      <div className="stat-rows">
                        {analysis.fastq.per_base_composition
                          .slice(0, 30)
                          .map((counts, index) => (
                            <Stat
                              key={index}
                              label={`Cycle ${index + 1} · A/C/G/T/N`}
                              value={`${fmt(counts.A ?? 0)} / ${fmt(counts.C ?? 0)} / ${fmt(counts.G ?? 0)} / ${fmt(counts.T ?? 0)} / ${fmt(counts.N ?? 0)}`}
                            />
                          ))}
                      </div>
                    </section>
                  )}
                  <div className="chart-grid">
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Length statistics</h2>
                          <p>Exact values across parsed records</p>
                        </div>
                      </div>
                      <div className="stat-rows">
                        <Stat
                          label="Population standard deviation"
                          value={
                            analysis.length.population_std_dev === undefined
                              ? "N/A"
                              : `${fmt(Math.round(analysis.length.population_std_dev))} bp`
                          }
                        />
                        {Object.entries(analysis.length.percentiles ?? {}).map(
                          ([label, value]) => (
                            <Stat
                              key={label}
                              label={label.toUpperCase()}
                              value={`${fmt(value)} bp`}
                            />
                          ),
                        )}
                      </div>
                    </section>
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Composition and integrity</h2>
                          <p>
                            Canonical counts, IUPAC symbols, and identifier
                            checks
                          </p>
                        </div>
                      </div>
                      <div className="stat-rows">
                        <Stat
                          label="A / C / G / T"
                          value={
                            analysis.nucleotide_counts
                              ? `${fmt(analysis.nucleotide_counts.A ?? 0)} / ${fmt(analysis.nucleotide_counts.C ?? 0)} / ${fmt(analysis.nucleotide_counts.G ?? 0)} / ${fmt(analysis.nucleotide_counts.T ?? 0)}`
                              : "N/A"
                          }
                        />
                        <Stat
                          label="Ambiguous fraction"
                          value={pct(analysis.ambiguous_percent ?? null)}
                        />
                        <Stat
                          label="Repeated sequence IDs"
                          value={
                            analysis.duplicate_identifiers === undefined
                              ? "N/A"
                              : fmt(analysis.duplicate_identifiers)
                          }
                        />
                        <Stat
                          label="Missing IDs"
                          value={
                            analysis.missing_identifiers === undefined
                              ? "N/A"
                              : fmt(analysis.missing_identifiers)
                          }
                        />
                        <Stat
                          label="Duplicate sequence rate"
                          value={
                            analysis.duplicate_rate_percent === undefined
                              ? "N/A"
                              : `${analysis.duplicate_rate_percent.toFixed(2)}%`
                          }
                        />
                        <Stat
                          label="Low-complexity regions"
                          value={
                            analysis.low_complexity_region_count === undefined
                              ? "N/A"
                              : fmt(analysis.low_complexity_region_count)
                          }
                        />
                        <Stat
                          label="Records with low complexity"
                          value={
                            analysis.low_complexity_sequence_count === undefined
                              ? "N/A"
                              : fmt(analysis.low_complexity_sequence_count)
                          }
                        />
                        <Stat
                          label="Reverse-complement duplicates"
                          value={
                            analysis.reverse_complement_duplicate_sequences ===
                            undefined
                              ? "N/A"
                              : fmt(
                                  analysis.reverse_complement_duplicate_sequences,
                                )
                          }
                        />
                      </div>
                    </section>
                  </div>
                  {analysis.fastq && (
                    <section className="panel quality-summary">
                      <div className="panel-heading">
                        <div>
                          <h2>Read quality thresholds</h2>
                          <p>
                            Base fractions from observed FASTQ quality scores
                          </p>
                        </div>
                      </div>
                      <div className="quality-metrics">
                        <Metric
                          label="Q20 BASES"
                          value={
                            analysis.fastq.q20_percent === undefined
                              ? "N/A"
                              : `${analysis.fastq.q20_percent.toFixed(2)}%`
                          }
                          sub="Phred score ≥ 20"
                          icon="✓"
                        />
                        <Metric
                          label="Q30 BASES"
                          value={
                            analysis.fastq.q30_percent === undefined
                              ? "N/A"
                              : `${analysis.fastq.q30_percent.toFixed(2)}%`
                          }
                          sub="Phred score ≥ 30"
                          icon="✓"
                        />
                        <Metric
                          label="READS WITH N"
                          value={fmt(analysis.fastq.reads_with_n)}
                          sub="Reads containing N"
                          icon="N"
                        />
                      </div>
                    </section>
                  )}
                  <div className="lower-grid">
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Most frequent {analysis.k}-mers</h2>
                          <p>
                            Canonical A/C/G/T windows, no reverse-complement
                            collapsing
                          </p>
                        </div>
                      </div>
                      <div className="kmer-list">
                        {analysis.top_kmers
                          .slice(0, 8)
                          .map(([word, count], i) => (
                            <div className="kmer-row" key={word}>
                              <span className="kmer-rank">
                                {String(i + 1).padStart(2, "0")}
                              </span>
                              <code>{word}</code>
                              <div className="kmer-track">
                                <i
                                  style={{
                                    width: `${Math.max(2, (count / Math.max(1, analysis.top_kmers[0]?.[1] ?? 1)) * 100)}%`,
                                  }}
                                />
                              </div>
                              <b>{fmt(count)}</b>
                            </div>
                          ))}
                        {analysis.top_kmers.length === 0 && (
                          <div className="empty-inline">
                            No canonical k-mers found at k={analysis.k}.
                          </div>
                        )}
                      </div>
                    </section>
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Analysis notes</h2>
                          <p>Scope and scientific interpretation</p>
                        </div>
                        <span className="note-icon">i</span>
                      </div>
                      <ul className="limitations">
                        {analysis.limitations.map((x, i) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                      <div className="provenance">
                        SOURCE{" "}
                        <b>
                          {dataset?.data_source === "arcinstitute/opengenome2"
                            ? "OpenGenome2"
                            : dataset?.data_source === "built_in_demo"
                              ? "Synthetic demo"
                              : "User upload"}
                        </b>
                        {dataset?.sampling?.source_path && (
                          <>
                            <span>·</span> FILE{" "}
                            <b>{dataset.sampling.source_path}</b>
                          </>
                        )}
                        {dataset?.source_revision && (
                          <>
                            <span>·</span> REVISION{" "}
                            <b>{dataset.source_revision.slice(0, 12)}</b>
                          </>
                        )}
                        <span>·</span> CREATED{" "}
                        <b>
                          {dataset
                            ? new Date(dataset.created_at).toLocaleDateString()
                            : "—"}
                        </b>
                      </div>
                    </section>
                  </div>
                  {Boolean(
                    analysis.kmer_spectrum?.length ||
                    analysis.kmer_gc_heatmap?.length,
                  ) && (
                    <div className="chart-grid">
                      <section className="panel chart-panel">
                        <div className="panel-heading">
                          <div>
                            <h2>Canonical k-mer spectrum</h2>
                            <p>
                              Distinct k-mers by observed multiplicity after
                              reverse-complement normalization
                            </p>
                          </div>
                          <span className="panel-tag">k={analysis.k}</span>
                        </div>
                        <KmerSpectrum data={analysis.kmer_spectrum ?? []} />
                      </section>
                      <section className="panel chart-panel">
                        <div className="panel-heading">
                          <div>
                            <h2>K-mer abundance by GC count</h2>
                            <p>
                              Color shows distinct canonical k-mers in log₂
                              abundance bins
                            </p>
                          </div>
                        </div>
                        <KmerHeatmap
                          data={analysis.kmer_gc_heatmap ?? []}
                          k={analysis.k}
                        />
                      </section>
                    </div>
                  )}
                  {taxonomy && (
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Taxonomic metadata</h2>
                          <p>{taxonomy.interpretation}</p>
                        </div>
                        <span className="panel-tag">
                          {taxonomy.source}
                          {taxonomy.release ? ` · ${taxonomy.release}` : ""}
                        </span>
                      </div>
                      <div className="stat-rows">
                        <Stat
                          label="Mapped sequences"
                          value={`${fmt(taxonomy.mapped_sequence_count)} / ${fmt(taxonomy.sequence_count)}`}
                        />
                        <Stat
                          label="Unmapped sequences"
                          value={fmt(taxonomy.unmapped_sequence_count)}
                        />
                        <Stat
                          label="Mapped nucleotide count"
                          value={fmt(taxonomy.mapped_nucleotide_count)}
                        />
                        <Stat
                          label="Unmapped nucleotide count"
                          value={fmt(taxonomy.unmapped_nucleotide_count)}
                        />
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>TAXON</th>
                              <th>RANK</th>
                              <th>SEQUENCES</th>
                              <th>NUCLEOTIDES</th>
                            </tr>
                          </thead>
                          <tbody>
                            {taxonomy.items.map((item) => (
                              <tr key={`${item.taxon_id}-${item.taxon_name}`}>
                                <td>
                                  {item.taxon_name}
                                  {item.taxon_id ? ` · ${item.taxon_id}` : ""}
                                </td>
                                <td>{item.rank ?? "—"}</td>
                                <td>{fmt(item.sequence_count)}</td>
                                <td>{fmt(item.nucleotide_count)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  )}
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Findings and alerts</h2>
                        <p>Rule-based review using configured API thresholds</p>
                      </div>
                      <span className="panel-tag">
                        {findings.filter((f) => f.status === "open").length}{" "}
                        OPEN
                      </span>
                    </div>
                    {findings.length === 0 ? (
                      <div className="empty-inline">
                        No threshold findings for this analysis.
                      </div>
                    ) : (
                      <div className="runs-list">
                        {findings.map((f) => (
                          <div className="run-row" key={f.id}>
                            <i
                              className={`dot ${f.severity === "error" ? "red" : f.severity === "warning" ? "amber" : "green"}`}
                            />
                            <span>
                              <b>{f.message}</b>
                              <small>
                                {f.code.replaceAll("_", " ")} · {f.status}
                                {f.value !== null
                                  ? ` · observed ${f.value}`
                                  : ""}
                              </small>
                            </span>
                            {f.status === "open" && (
                              <>
                                <button
                                  onClick={() =>
                                    void setFindingStatus(f.id, "acknowledged")
                                  }
                                >
                                  Acknowledge
                                </button>
                                <button
                                  onClick={() =>
                                    void setFindingStatus(f.id, "dismissed")
                                  }
                                >
                                  Dismiss
                                </button>
                              </>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                  <section className="panel sequence-panel">
                    <div className="panel-heading sequence-heading">
                      <div>
                        <h2>Sequence explorer</h2>
                        <p>
                          {fmt(analysis.sequence_count)} records · filter
                          identifiers to inspect flagged records
                        </p>
                      </div>
                      <label className="outlier-toggle">
                        <input
                          type="checkbox"
                          checked={excludeOutliers}
                          onChange={(e) => {
                            setExcludeOutliers(e.target.checked);
                            setPage(0);
                          }}
                        />{" "}
                        Exclude length outliers
                      </label>
                      <input
                        className="search-input"
                        placeholder="⌕  Filter by sequence ID"
                        value={seqFilter}
                        onChange={(e) => {
                          setSeqFilter(e.target.value);
                          setPage(0);
                        }}
                      />
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>SEQUENCE ID</th>
                            <th>LENGTH</th>
                            <th>GC CONTENT</th>
                            <th>AMBIGUOUS</th>
                            <th>MAX RUN</th>
                            <th>SHANNON ENTROPY</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filtered.map((r) => (
                            <tr key={r.id}>
                              <td>
                                <button
                                  className="seq-id"
                                  onClick={() => {
                                    setWindowStart("0");
                                    void loadSequenceWindow(r.id, 0);
                                  }}
                                >
                                  {r.id}
                                </button>
                                {r.invalid_symbols > 0 && (
                                  <span className="flag">INVALID</span>
                                )}
                                {(r.low_complexity_regions?.length ?? 0) >
                                  0 && (
                                  <span className="flag">LOW COMPLEXITY</span>
                                )}
                              </td>
                              <td>{fmt(r.length)} bp</td>
                              <td>{pct(r.gc_percent)}</td>
                              <td>{fmt(r.ambiguous_bases)}</td>
                              <td>{fmt(r.max_homopolymer)}</td>
                              <td>{r.shannon_entropy?.toFixed(3) ?? "N/A"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!filtered.length && (
                        <div className="empty-inline">
                          No records match this filter.
                        </div>
                      )}
                    </div>
                    <div className="table-footer">
                      <span>
                        Showing {sequenceTotal ? page * 12 + 1 : 0}–
                        {Math.min((page + 1) * 12, sequenceTotal)} of{" "}
                        {fmt(analysis.sequence_count)} sequences
                      </span>
                      <div>
                        <button
                          onClick={() => setPage(Math.max(0, page - 1))}
                          disabled={page === 0}
                        >
                          ←
                        </button>
                        <button
                          onClick={() => setPage(page + 1)}
                          disabled={(page + 1) * 12 >= sequenceTotal}
                        >
                          →
                        </button>
                      </div>
                    </div>
                  </section>
                  {sequenceWindow && (
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Sequence window</h2>
                          <p>
                            {sequenceWindow.record_id} ·{" "}
                            {fmt(sequenceWindow.length)} bp · coordinates{" "}
                            {fmt(sequenceWindow.start)}–
                            {fmt(sequenceWindow.end)} (zero-based)
                          </p>
                        </div>
                        <button
                          className="button secondary"
                          onClick={() => setSequenceWindow(null)}
                        >
                          Close
                        </button>
                      </div>
                      <div className="hub-path">
                        <label>
                          Start coordinate{" "}
                          <input
                            type="number"
                            min="0"
                            max={Math.max(0, sequenceWindow.length - 1)}
                            value={windowStart}
                            onChange={(e) => setWindowStart(e.target.value)}
                          />
                        </label>
                        <button
                          className="button secondary"
                          onClick={() =>
                            void loadSequenceWindow(sequenceWindow.record_id)
                          }
                        >
                          Load 1,000 bp window
                        </button>
                      </div>
                      <pre className="sequence-window">
                        {sequenceWindow.sequence.match(/.{1,80}/g)?.join("\n")}
                      </pre>
                      <small>
                        Window retrieval is capped at 10,000 bases per API
                        request.
                      </small>
                    </section>
                  )}
                  <section className="panel runs-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Analysis history</h2>
                        <p>
                          Each run stores its configuration and result
                          independently.
                        </p>
                      </div>
                    </div>
                    <div className="runs-list">
                      {runs.length === 0 ? (
                        <div className="empty-inline">
                          No analysis runs yet.
                        </div>
                      ) : (
                        runs.map((run) => (
                          <div className="run-row" key={run.id}>
                            <i
                              className={`dot ${run.status === "complete" ? "green" : run.status === "failed" ? "red" : "amber"}`}
                            />
                            <span>
                              <b>{run.status}</b>
                              <small>
                                {new Date(run.created_at).toLocaleString()} · k=
                                {run.config.k}
                              </small>
                            </span>
                            <code>{run.id.slice(0, 8)}</code>
                            {run.error && (
                              <small className="run-error">{run.error}</small>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </section>
                  {dataset && (
                    <div className="delete-row">
                      <span>Uploaded file stored in this local workspace.</span>
                      <button onClick={remove}>Delete dataset</button>
                    </div>
                  )}
                </>
              )}
            </>
          )}
          <footer>
            GENOME QUALITY INSPECTOR <span>·</span> LOCAL SCIENTIFIC ANALYSIS{" "}
            <span>·</span> v0.1
          </footer>
        </div>
      </section>
    </main>
  );
}
function Metric({
  label,
  value,
  sub,
  icon,
}: {
  label: string;
  value: string;
  sub: string;
  icon: string;
}) {
  return (
    <div className="metric-card">
      <div className="metric-top">
        <span>{label}</span>
        <i>{icon}</i>
      </div>
      <strong>{value}</strong>
      <small>{sub}</small>
    </div>
  );
}
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-row">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}
function GcChart({ data }: { data: number[] }) {
  const height = scaleLinear()
    .domain([0, Math.max(1, ...data)])
    .range([0, 100]);
  return (
    <div
      className="gc-chart"
      role="img"
      aria-label="Sequence count distribution by GC percentage"
    >
      {data.map((n, i) => (
        <i
          key={i}
          title={`${i}% GC: ${n} sequences`}
          style={{
            height: `${Math.max(n === 0 ? 1 : 3, height(n))}%`,
            opacity: n === 0 ? 0.25 : 0.55 + (n / Math.max(1, ...data)) * 0.45,
          }}
        />
      ))}
    </div>
  );
}
function LengthChart({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data).sort(
    (a, b) => Number.parseInt(a[0]) - Number.parseInt(b[0]),
  );
  const height = scaleLinear()
    .domain([0, Math.max(1, ...rows.map(([, n]) => n))])
    .range([0, 100]);
  return (
    <div
      className="length-chart"
      role="img"
      aria-label="Sequence count by length interval"
    >
      {rows.map(([bin, count]) => (
        <div key={bin} title={`${bin} bp: ${count} sequences`}>
          <i style={{ height: `${Math.max(3, height(count))}%` }} />
          <small>{Number.parseInt(bin)}</small>
        </div>
      ))}
    </div>
  );
}
function NxChart({ data }: { data: [number, number][] }) {
  const scale = scaleLinear()
    .domain([0, Math.max(1, ...data.map(([, n]) => n))])
    .range([0, 100]);
  return (
    <div className="length-chart" role="img" aria-label="Assembly Nx curve">
      {data.map(([percent, length]) => (
        <div key={percent} title={`N${percent}: ${length} bp`}>
          <i style={{ height: `${Math.max(3, scale(length))}%` }} />
          <small>{percent}%</small>
        </div>
      ))}
    </div>
  );
}
function KmerSpectrum({ data }: { data: [number, number][] }) {
  const bins = new Map<number, number>();
  for (const [abundance, distinct] of data) {
    const bucket = Math.floor(Math.log2(Math.max(1, abundance)));
    bins.set(bucket, (bins.get(bucket) ?? 0) + distinct);
  }
  const rows = [...bins.entries()].sort((a, b) => a[0] - b[0]);
  const scale = scaleLinear()
    .domain([0, Math.max(1, ...rows.map(([, count]) => count))])
    .range([0, 100]);
  return (
    <div
      className="length-chart"
      role="img"
      aria-label="Canonical k-mer spectrum by multiplicity"
    >
      {rows.map(([bucket, count]) => (
        <div
          key={bucket}
          title={`Multiplicity ${2 ** bucket}–${2 ** (bucket + 1) - 1}: ${fmt(count)} distinct k-mers`}
        >
          <i style={{ height: `${Math.max(3, scale(count))}%` }} />
          <small>{2 ** bucket}</small>
        </div>
      ))}
    </div>
  );
}
function KmerHeatmap({
  data,
  k,
}: {
  data: [number, number, number][];
  k: number;
}) {
  const cells = new Map<string, number>();
  let maxBucket = 0;
  let maxCell = 1;
  for (const [gc, abundance, count] of data) {
    const bucket = Math.floor(Math.log2(Math.max(1, abundance)));
    const key = `${gc}:${bucket}`;
    cells.set(key, (cells.get(key) ?? 0) + count);
    maxBucket = Math.max(maxBucket, bucket);
    maxCell = Math.max(maxCell, cells.get(key) ?? 0);
  }
  const columns = Math.max(1, maxBucket + 1);
  return (
    <div
      className="kmer-heatmap"
      role="img"
      aria-label="Distinct reverse-complement-canonical k-mers by GC count and logarithmic abundance"
    >
      <div className="kmer-heatmap-axis">
        GC count ↓ · abundance multiplicity →
      </div>
      {Array.from({ length: k + 1 }, (_, i) => k - i).map((gc) => (
        <div
          className="kmer-heatmap-row"
          key={gc}
          style={{
            gridTemplateColumns: `32px repeat(${columns}, minmax(6px,1fr))`,
          }}
        >
          <small>{gc}</small>
          {Array.from({ length: columns }, (_, bucket) => {
            const count = cells.get(`${gc}:${bucket}`) ?? 0;
            const opacity = count
              ? 0.12 + (0.88 * Math.log1p(count)) / Math.log1p(maxCell)
              : 0;
            return (
              <i
                key={bucket}
                title={`GC count ${gc}; multiplicity ${2 ** bucket}–${2 ** (bucket + 1) - 1}; ${fmt(count)} distinct k-mers`}
                style={{
                  backgroundColor: count
                    ? `rgba(38, 135, 109, ${opacity})`
                    : "#f0f2f0",
                }}
              />
            );
          })}
        </div>
      ))}
      <div className="kmer-heatmap-axis">
        Columns are log₂ multiplicity bins; cells count distinct canonical
        k-mers.
      </div>
    </div>
  );
}
function QualityChart({ data }: { data: number[] }) {
  const high = Math.max(40, ...data);
  const scale = scaleLinear().domain([0, high]).range([0, 100]);
  return (
    <div
      className="quality-chart"
      role="img"
      aria-label="Mean FASTQ Phred quality by base position"
    >
      {data.map((q, i) => (
        <i
          key={i}
          title={`Base ${i + 1}: mean Phred ${q.toFixed(2)}`}
          style={{
            height: `${scale(q)}%`,
            background: q >= 30 ? "#35966f" : q >= 20 ? "#cea34e" : "#c96e60",
          }}
        />
      ))}
    </div>
  );
}
