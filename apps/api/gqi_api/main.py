from __future__ import annotations

import asyncio
import csv
import gzip
import http.client
import io
import ipaddress
import json
import math
import os
import random
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from html.parser import HTMLParser
from itertools import islice
from pathlib import Path
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
    urlopen,
)

from Bio import SeqIO
from Bio.SeqRecord import SeqRecord
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from huggingface_hub import HfApi, hf_hub_download
from pydantic import BaseModel, Field
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")
DATA_DIR = Path(os.environ.get("GQI_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'gqi.sqlite3'}")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    filename: Mapped[str] = mapped_column(String(500))
    path: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(20))
    dataset_type: Mapped[str] = mapped_column(String(40))
    data_source: Mapped[str] = mapped_column(String(80), default="user_upload")
    source_revision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sampling_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20))
    config_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Comparison(Base):
    __tablename__ = "comparisons"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), default="Saved comparison")
    dataset_ids_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    value_json: Mapped[str] = mapped_column(Text, default="null")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class TaxonomyMapping(Base):
    __tablename__ = "taxonomy_mappings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    sequence_id: Mapped[str] = mapped_column(String(500), index=True)
    taxon_name: Mapped[str] = mapped_column(String(500))
    taxon_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rank: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[str] = mapped_column(String(120), default="user_metadata")
    release: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ToolRun(Base):
    __tablename__ = "tool_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BoundedTextReader:
    def __init__(self, handle, max_bytes: int):
        self.handle = handle
        self.max_bytes = max_bytes
        self.bytes_read = 0

    def _check(self, content: str) -> str:
        self.bytes_read += len(content.encode("utf-8"))
        if self.bytes_read > self.max_bytes:
            raise HTTPException(
                413, detail="Expanded FASTA data exceeded the configured import limit"
            )
        return content

    def read(self, size: int = -1) -> str:
        return self._check(self.handle.read(size))

    def readline(self, size: int = -1) -> str:
        return self._check(self.handle.readline(size))

    def __iter__(self):
        return self

    def __next__(self) -> str:
        line = self.readline()
        if not line:
            raise StopIteration
        return line


def register_external_sequence_file(
    stored: Path, filename: str, dataset_type: str | None, tags: list[str], source: str
) -> dict:
    lower = filename.lower()
    base = lower.removesuffix(".gz")
    suffix = Path(base).suffix
    if suffix not in SUPPORTED:
        raise HTTPException(415, detail="Source must be FASTA or FASTQ, optionally gzip compressed")
    fmt = "fastq" if suffix in {".fq", ".fastq"} else "fasta"
    dtype = dataset_type or ("raw_reads" if fmt == "fastq" else "sequence_collection")
    if dtype not in TYPES:
        raise HTTPException(422, detail=f"dataset_type must be one of {', '.join(sorted(TYPES))}")
    dataset = Dataset(id=stored.parent.name, name=Path(base).stem[:300], description=f"Imported from {source}", filename=filename, path=str(stored), format=fmt + (".gz" if lower.endswith(".gz") else ""), dataset_type=dtype, data_source=source[:80], tags_json=json.dumps(sorted({tag.strip()[:60] for tag in tags if tag.strip()})), bytes=stored.stat().st_size)
    with Session() as db:
        db.add(dataset)
        db.commit()
        return public(dataset)


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, new_url):
        return None


def validate_public_https_host(host: str) -> str:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = {ipaddress.ip_address(answer[4][0]) for answer in answers}
    except (OSError, ValueError) as exc:
        raise HTTPException(422, detail="Source host could not be resolved") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise HTTPException(403, detail="Source host resolves to a non-public network address")
    return min(addresses, key=lambda address: address.version).compressed


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, pinned_ip: str, **kwargs) -> None:
        self._pinned_ip = pinned_ip
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, getattr(self, "source_address", None)
        )
        context = getattr(self, "_context", None)
        if context is not None:
            self.sock = context.wrap_socket(self.sock, server_hostname=self.host)


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, pinned_ip: str) -> None:
        super().__init__()
        self.pinned_ip = pinned_ip

    def https_open(self, request):
        return self.do_open(
            lambda host, **kwargs: _PinnedHTTPSConnection(
                host, self.pinned_ip, **kwargs
            ),
            request,
        )


app = FastAPI(
    title="Genome Quality Inspector API",
    version="0.1.0",
    description="Local nucleotide dataset auditing API",
)
cors_origins = [
    o.strip()
    for o in os.environ.get(
        "GQI_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3008,http://127.0.0.1:3008",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=os.environ.get(
        "GQI_CORS_REGEX", r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$"
    ),
    allow_methods=["*"],
    allow_headers=["*"],
)

TYPES = {
    "sequence_collection",
    "raw_reads",
    "genome_assembly",
    "reference_genome",
    "training_corpus",
    "unknown",
}
SUPPORTED = {".fa", ".fasta", ".fna", ".ffn", ".fq", ".fastq"}


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=30)


class AnalysisRequest(BaseModel):
    k: int = Field(default=21, ge=1, le=31)


class ComparisonRequest(BaseModel):
    dataset_ids: list[str] = Field(min_length=2, max_length=4)
    name: str = Field(default="Saved comparison", min_length=1, max_length=300)


class OpenGenomeImportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    revision: str = Field(min_length=4, max_length=64)
    dataset_type: str = Field(default="sequence_collection", max_length=40)
    max_bytes: int = Field(default=1024**3, ge=1, le=5 * 1024**3)
    sample_size: int = Field(default=10000, ge=0, le=100000)
    sample_seed: int = Field(default=42, ge=0, le=2**32 - 1)


class OpenGenomeJsonlImportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    revision: str = Field(min_length=4, max_length=64)
    max_bytes: int = Field(default=16 * 1024**2, ge=1024, le=64 * 1024**2)
    sample_size: int = Field(default=10000, ge=1, le=100000)
    sample_seed: int = Field(default=42, ge=0, le=2**32 - 1)


class LocalPathImportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    dataset_type: str | None = Field(default=None, max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=30)


class SourceUrlImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=3000)
    dataset_type: str | None = Field(default=None, max_length=40)
    max_bytes: int = Field(default=1024**3, ge=1, le=5 * 1024**3)
    tags: list[str] = Field(default_factory=list, max_length=30)


class TaxonomyMappingRequest(BaseModel):
    source: str = Field(default="user_metadata", min_length=1, max_length=120)
    release: str | None = Field(default=None, max_length=120)


def public_run(run: AnalysisRun, include_result: bool = True) -> dict:
    return {
        "id": run.id,
        "dataset_id": run.dataset_id,
        "status": run.status,
        "config": json.loads(run.config_json),
        "analysis": json.loads(run.result_json)
        if include_result and run.result_json
        else None,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def public(d: Dataset) -> dict:
    result = json.loads(d.analysis_json) if d.analysis_json else None
    if result is not None:
        result.pop("records", None)
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "tags": json.loads(d.tags_json or "[]"),
        "filename": d.filename,
        "format": d.format,
        "dataset_type": d.dataset_type,
        "data_source": d.data_source,
        "source_revision": d.source_revision,
        "sampling": json.loads(d.sampling_json) if d.sampling_json else None,
        "bytes": d.bytes,
        "status": d.status,
        "error": d.error,
        "created_at": d.created_at.isoformat(),
        "analysis": result,
    }


def run_analysis(dataset_id: str, run_id: str, k: int) -> None:
    with Session() as db:
        d = db.get(Dataset, dataset_id)
        run = db.get(AnalysisRun, run_id)
        if d is None or run is None:
            return
        d.status = "running"
        d.error = None
        run.status = "running"
        db.commit()
        data_path = d.path
        dtype = d.dataset_type
    try:
        binary = os.environ.get("GQI_ENGINE")
        if binary:
            cmd = [binary, data_path, "--dataset-type", dtype, "--k", str(k)]
        else:
            cmd = [
                "cargo",
                "run",
                "--release",
                "--locked",
                "--manifest-path",
                str(ROOT / "crates/gqi-engine/Cargo.toml"),
                "--",
                data_path,
                "--dataset-type",
                dtype,
                "--k",
                str(k),
            ]
        proc = subprocess.run(
            cmd,
            check=False,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("GQI_ANALYSIS_TIMEOUT", "3600")),
        )
        if proc.returncode:
            raise RuntimeError(proc.stderr[-4000:] or "Analysis engine failed")
        result = json.loads(proc.stdout)
        with Session() as db:
            d = db.get(Dataset, dataset_id)
            run = db.get(AnalysisRun, run_id)
            if d and run:
                d.analysis_json = json.dumps(result)
                d.status = "complete"
                run.status = "complete"
                run.result_json = json.dumps(result)
                run.completed_at = datetime.now(UTC)
                create_findings(db, d.id, result)
                db.commit()
    except Exception as exc:  # noqa: BLE001 - capture worker failures in the dataset row
        with Session() as db:
            d = db.get(Dataset, dataset_id)
            run = db.get(AnalysisRun, run_id)
            if d and run:
                d.status = "failed"
                d.error = str(exc)[:4000]
                run.status = "failed"
                run.error = str(exc)[:4000]
                run.completed_at = datetime.now(UTC)
                db.commit()


def start_analysis(dataset_id: str, run_id: str, k: int) -> None:
    redis_url = os.environ.get("GQI_REDIS_URL")
    if redis_url:
        from redis import Redis
        from rq import Queue

        Queue("gqi-analysis", connection=Redis.from_url(redis_url)).enqueue(
            run_analysis,
            dataset_id,
            run_id,
            k,
            job_timeout=int(os.environ.get("GQI_ANALYSIS_TIMEOUT", "3600")),
            job_id=f"analysis-{dataset_id}-{uuid.uuid4()}",
        )
    else:
        # Convenient single-process mode for a local first run; set GQI_REDIS_URL
        # and run `rq worker gqi-analysis` for durable queue processing.
        threading.Thread(
            target=run_analysis,
            args=(dataset_id, run_id, k),
            daemon=True,
            name=f"analysis-{dataset_id[:8]}",
        ).start()


def run_quast(dataset_id: str, run_id: str) -> None:
    started_at = time.monotonic()
    with Session() as db:
        dataset = db.get(Dataset, dataset_id)
        run = db.get(ToolRun, run_id)
        if dataset is None or run is None:
            return
        run.status = "running"
        db.commit()
        source_path = dataset.path
    try:
        executable = shutil.which("quast.py")
        if executable is None:
            raise RuntimeError("QUAST is not installed; install QUAST and ensure quast.py is on PATH")
        with tempfile.TemporaryDirectory(prefix="gqi-quast-") as output_dir:
            proc = subprocess.run(
                [executable, source_path, "-o", output_dir, "--no-html", "--no-icarus"],
                check=False,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("GQI_SPECIALIZED_TOOL_TIMEOUT", "7200")),
            )
            if proc.returncode:
                raise RuntimeError((proc.stderr or proc.stdout)[-4000:] or "QUAST failed")
            report_path = Path(output_dir) / "report.tsv"
            with report_path.open(encoding="utf-8") as handle:
                rows = list(csv.reader(handle, delimiter="\t"))
            metrics = {row[0]: row[1] for row in rows if len(row) >= 2}
            version_proc = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=15, check=False
            )
            result = {
                "tool": "QUAST",
                "version": (version_proc.stdout or version_proc.stderr).strip()[:200] or None,
                "runtime_seconds": round(time.monotonic() - started_at, 3),
                "metrics": metrics,
                "raw_report_tsv": report_path.read_text(encoding="utf-8")[:1_000_000],
            }
        with Session() as db:
            run = db.get(ToolRun, run_id)
            if run:
                run.status = "complete"
                run.result_json = json.dumps(result)
                run.completed_at = datetime.now(UTC)
                db.commit()
    except Exception as exc:  # noqa: BLE001 - persist optional integration failures
        with Session() as db:
            run = db.get(ToolRun, run_id)
            if run:
                run.status = "failed"
                run.error = str(exc)[:4000]
                run.completed_at = datetime.now(UTC)
                db.commit()


def start_quast(dataset_id: str, run_id: str) -> None:
    redis_url = os.environ.get("GQI_REDIS_URL")
    if redis_url:
        from redis import Redis
        from rq import Queue

        Queue("gqi-analysis", connection=Redis.from_url(redis_url)).enqueue(
            run_quast,
            dataset_id,
            run_id,
            job_timeout=int(os.environ.get("GQI_SPECIALIZED_TOOL_TIMEOUT", "7200")),
            job_id=f"quast-{dataset_id}-{run_id}",
        )
    else:
        threading.Thread(target=run_quast, args=(dataset_id, run_id), daemon=True, name=f"quast-{dataset_id[:8]}").start()


def create_findings(db, dataset_id: str, analysis: dict) -> None:
    """Refresh deterministic rule-based findings from a completed result."""
    db.query(Finding).filter(Finding.dataset_id == dataset_id).delete()
    thresholds = {
        "gc_min": float(os.environ.get("GQI_GC_MIN_PERCENT", "20")),
        "gc_max": float(os.environ.get("GQI_GC_MAX_PERCENT", "80")),
        "ambiguous_max": float(os.environ.get("GQI_AMBIGUOUS_MAX_PERCENT", "5")),
        "invalid_max": int(os.environ.get("GQI_INVALID_SYMBOL_MAX", "0")),
        "duplicate_max": float(os.environ.get("GQI_DUPLICATE_MAX_PERCENT", "10")),
        "low_complexity_max": float(os.environ.get("GQI_LOW_COMPLEXITY_MAX_PERCENT", "15")),
    }
    checks = [
        ("gc_low", analysis.get("gc_percent") is not None and analysis["gc_percent"] < thresholds["gc_min"], "warning", f"GC content is below {thresholds['gc_min']}%", analysis.get("gc_percent")),
        ("gc_high", analysis.get("gc_percent") is not None and analysis["gc_percent"] > thresholds["gc_max"], "warning", f"GC content is above {thresholds['gc_max']}%", analysis.get("gc_percent")),
        ("ambiguous_bases", (analysis.get("ambiguous_percent") or 0) > thresholds["ambiguous_max"], "warning", f"Ambiguous bases exceed {thresholds['ambiguous_max']}%", analysis.get("ambiguous_percent")),
        ("invalid_symbols", analysis.get("invalid_symbols", 0) > thresholds["invalid_max"], "error", f"Invalid symbols exceed {thresholds['invalid_max']}", analysis.get("invalid_symbols")),
        ("duplicate_sequences", (analysis.get("duplicate_rate_percent") or 0) > thresholds["duplicate_max"], "info", f"Exact duplicate rate exceeds {thresholds['duplicate_max']}%", analysis.get("duplicate_rate_percent")),
        ("low_complexity", analysis.get("sequence_count", 0) > 0 and analysis.get("low_complexity_sequence_count", 0) / analysis["sequence_count"] * 100 > thresholds["low_complexity_max"], "warning", f"Low-complexity regions occur in more than {thresholds['low_complexity_max']}% of records", analysis.get("low_complexity_sequence_count")),
    ]
    for code, triggered, severity, message, value in checks:
        if triggered:
            db.add(Finding(id=str(uuid.uuid4()), dataset_id=dataset_id, code=code, severity=severity, message=message, value_json=json.dumps(value)))


@app.get("/api/health")
@app.get("/api/v1/health")
def health() -> dict:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {
            "status": "ok",
            "database": "ok",
            "engine": os.environ.get("GQI_ENGINE", "cargo run"),
        }
    except Exception as exc:
        raise HTTPException(503, detail=f"database unavailable: {exc}") from exc


@app.get("/api/v1/ready")
def ready() -> dict:
    health()
    return {"ready": True}


@app.get("/api/v1/capabilities")
def capabilities() -> dict:
    tools = {
        name: shutil.which(name) is not None
        for name in ("quast.py", "busco", "checkm2", "gtdbtk", "minimap2", "datasets")
    }
    return {
        "formats": ["fasta", "fastq", "fasta.gz", "fastq.gz"],
        "dataset_types": sorted(TYPES),
        "analysis": [
            "sequence_statistics",
            "low_complexity_entropy_regions",
            "kmer_counts",
            "canonical_kmer_spectrum",
            "kmer_gc_abundance_heatmap",
            "exact_duplicates",
            "reverse_complement_duplicate_equivalence",
            "fastq_quality",
            "assembly_nx_curve",
            "assembly_n90_l90",
            "user_metadata_taxonomy_aggregation",
        ],
        "queue": "rq" if os.environ.get("GQI_REDIS_URL") else "in_process",
        "optional_tools": tools,
    }


@app.get("/api/v1/integrations")
def integrations() -> dict:
    return {
        "items": [
            {"id": "opengenome2", "status": "available", "source": "Hugging Face Hub"},
            {"id": "gtdb", "status": "release_discovery_available_user_taxonomy_metadata"},
            {"id": "ncbi_refseq", "status": "available" if shutil.which("datasets") else "datasets_cli_not_installed"},
            {
                "id": "quast",
                "status": "detected" if shutil.which("quast.py") else "not_installed",
            },
            {
                "id": "busco",
                "status": "detected" if shutil.which("busco") else "not_installed",
            },
            {
                "id": "checkm2",
                "status": "detected" if shutil.which("checkm2") else "not_installed",
            },
        ]
    }


@app.post("/api/v1/datasets/{dataset_id}/integrations/quast", status_code=202)
def submit_quast(dataset_id: str) -> dict:
    run_id = str(uuid.uuid4())
    with Session() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            raise HTTPException(404, detail="dataset not found")
        if dataset.dataset_type != "genome_assembly" or dataset.format not in {"fasta", "fasta.gz"}:
            raise HTTPException(422, detail="QUAST requires a genome_assembly dataset in FASTA format")
        if not shutil.which("quast.py"):
            raise HTTPException(503, detail="QUAST is not installed; install it and ensure quast.py is on PATH")
        db.add(ToolRun(id=run_id, dataset_id=dataset_id, tool="quast", status="queued", config_json="{}"))
        db.commit()
    try:
        start_quast(dataset_id, run_id)
    except Exception as exc:
        with Session() as db:
            run = db.get(ToolRun, run_id)
            if run:
                run.status = "failed"
                run.error = str(exc)[:4000]
                run.completed_at = datetime.now(UTC)
                db.commit()
        raise HTTPException(503, detail="QUAST could not be queued; check Redis and the worker") from exc
    return {"run_id": run_id, "dataset_id": dataset_id, "tool": "quast", "status": "queued"}


@app.get("/api/v1/tool-runs/{run_id}")
def get_tool_run(run_id: str) -> dict:
    with Session() as db:
        run = db.get(ToolRun, run_id)
        if run is None:
            raise HTTPException(404, detail="tool run not found")
        return {
            "run_id": run.id,
            "dataset_id": run.dataset_id,
            "tool": run.tool,
            "status": run.status,
            "result": json.loads(run.result_json) if run.result_json else None,
            "error": run.error,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }


@app.get("/api/v1/integrations/ncbi/search")
def ncbi_genome_search(q: str, kind: str = "taxon", limit: int = 25) -> dict:
    """Search NCBI genome metadata without downloading sequence packages."""
    query = q.strip()
    if not query or len(query) > 200 or any(ord(char) < 32 for char in query):
        raise HTTPException(422, detail="q must contain 1–200 printable characters")
    if kind not in {"taxon", "accession"}:
        raise HTTPException(422, detail="kind must be taxon or accession")
    if not 1 <= limit <= 100:
        raise HTTPException(422, detail="limit must be between 1 and 100")
    binary = shutil.which("datasets")
    if not binary:
        raise HTTPException(503, detail="NCBI metadata search requires the optional NCBI Datasets CLI; install it and retry")
    cmd = [binary, "summary", "genome", kind, query, "--limit", str(limit), "--as-json-lines"]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, detail="NCBI genome metadata search timed out") from exc
    if proc.returncode:
        raise HTTPException(502, detail=f"NCBI Datasets search failed: {proc.stderr[-1500:] or 'unknown CLI error'}")
    if len(proc.stdout.encode("utf-8")) > 10 * 1024**2:
        raise HTTPException(502, detail="NCBI metadata response exceeded 10 MiB")
    try:
        records = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise HTTPException(502, detail="NCBI Datasets returned invalid JSON Lines") from exc
    return {"source": "NCBI Datasets", "query": query, "kind": kind, "items": records[:limit], "returned": min(len(records), limit), "limit": limit, "sequence_data_downloaded": False}


class _GTDBReleaseLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        match = re.fullmatch(r"(r\d{1,4})/?", href)
        if match:
            self.links.add(match.group(1))


@app.get("/api/v1/integrations/gtdb/releases")
def gtdb_releases(limit: int = 50) -> dict:
    if not 1 <= limit <= 100:
        raise HTTPException(422, detail="limit must be between 1 and 100")
    source_url = "https://data.gtdb.ecogenomic.org/releases/"
    try:
        request = Request(source_url, headers={"User-Agent": "GenomeQualityInspector/0.1"})
        with urlopen(request, timeout=20) as response:
            host = (urlparse(response.geturl()).hostname or "").lower()
            if not host.endswith(".ecogenomic.org"):
                raise HTTPException(502, detail="GTDB release index redirected outside its official domain")
            body = response.read(2 * 1024**2 + 1)
        if len(body) > 2 * 1024**2:
            raise HTTPException(502, detail="GTDB release index exceeded 2 MiB")
        parser = _GTDBReleaseLinks()
        parser.feed(body.decode("utf-8", errors="replace"))
        releases = sorted(parser.links, key=lambda release: int(release[1:]), reverse=True)[:limit]
        if not releases:
            raise HTTPException(502, detail="GTDB release index contained no release links")
        return {"source": "GTDB official release directory", "releases": [{"id": release, "metadata_directory": f"https://data.gtdb.ecogenomic.org/releases/{release}/"} for release in releases], "limit": limit, "sequence_data_downloaded": False}
    except HTTPException:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise HTTPException(502, detail=f"Could not read the GTDB release index: {exc}") from exc


@app.post("/api/v1/demo/seed", status_code=201)
def seed_demo() -> dict:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "demo"
    definitions = [
        ("Synthetic assembly demo", "assembly.fasta", "fasta", "genome_assembly"),
        ("Synthetic FASTQ reads demo", "reads.fastq", "fastq", "raw_reads"),
        (
            "Synthetic sequence collection demo",
            "sequence-collection.fasta",
            "fasta",
            "sequence_collection",
        ),
    ]
    identifiers = []
    with Session() as db:
        for name, filename, fmt, dataset_type in definitions:
            existing = db.scalar(
                select(Dataset).where(
                    Dataset.data_source == "built_in_demo",
                    Dataset.filename == filename,
                )
            )
            if existing:
                identifiers.append(existing.id)
                result = json.loads(existing.analysis_json or "{}")
                analysis_is_stale = existing.status == "complete" and (
                    "nucleotide_counts" not in result
                    or "percentiles" not in result.get("length", {})
                )
                if analysis_is_stale:
                    existing.status = "uploaded"
                    existing.error = None
                continue
            source = fixtures / filename
            if not source.is_file():
                raise HTTPException(500, detail=f"Demo fixture is missing: {filename}")
            identifier = str(uuid.uuid4())
            dest = DATA_DIR / "uploads" / identifier
            dest.mkdir(parents=True, exist_ok=True)
            stored = dest / filename
            shutil.copyfile(source, stored)
            dataset = Dataset(
                id=identifier,
                name=name,
                description="Synthetic demonstration data. Metrics are computed from the included sequence records.",
                filename=filename,
                path=str(stored),
                format=fmt,
                dataset_type=dataset_type,
                data_source="built_in_demo",
                sampling_json=json.dumps({"sampled": False, "method": "all_records"}),
                bytes=stored.stat().st_size,
            )
            db.add(dataset)
            identifiers.append(identifier)
        db.commit()
        pending = [
            dataset.id
            for dataset in (db.get(Dataset, identifier) for identifier in identifiers)
            if dataset and dataset.status in {"uploaded", "failed"}
        ]
    for identifier in pending:
        analyze_dataset(identifier, AnalysisRequest(k=21))
    with Session() as db:
        items = [db.get(Dataset, identifier) for identifier in identifiers]
        return {"items": [public(item) for item in items if item]}


@app.get("/api/v1/integrations/opengenome2/files")
def opengenome2_files(
    category: str = "fasta",
    subpath: str = "",
    revision: str = "main",
    limit: int = 100,
) -> dict:
    if category not in {"fasta", "jsonl", "metadata"}:
        raise HTTPException(422, detail="category must be fasta, jsonl, or metadata")
    if not 1 <= limit <= 1000:
        raise HTTPException(422, detail="limit must be between 1 and 1000")
    if subpath and (
        not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", subpath)
        or ".." in subpath.split("/")
    ):
        raise HTTPException(
            422, detail="subpath must contain safe repository path segments"
        )
    repo_id = "arcinstitute/opengenome2"
    token = os.environ.get("HF_TOKEN")
    try:
        hub = HfApi(token=token)
        info = hub.repo_info(repo_id, repo_type="dataset", revision=revision)
        resolved_revision = info.sha
        if category == "metadata":
            path_in_repo = None
        else:
            path_in_repo = category + (f"/{subpath}" if subpath else "")
        tree = hub.list_repo_tree(
            repo_id,
            path_in_repo=path_in_repo,
            recursive=category != "metadata",
            revision=resolved_revision,
            repo_type="dataset",
        )
        records: list[dict[str, object]] = []
        has_more = False
        for item in tree:
            path = getattr(item, "path", "")
            if category == "metadata":
                if path != "species_metadata.csv":
                    continue
            elif not hasattr(item, "size"):
                continue
            if len(records) >= limit:
                has_more = True
                break
            records.append(
                {
                    "path": path,
                    "size_bytes": getattr(item, "size", None),
                    "revision": resolved_revision,
                    "oid": getattr(item, "blob_id", None),
                    "format": Path(path).suffix.lstrip(".").lower(),
                }
            )
        return {
            "repository": repo_id,
            "revision": resolved_revision,
            "category": category,
            "license": "apache-2.0",
            "license_url": "https://huggingface.co/datasets/arcinstitute/opengenome2",
            "files": records,
            "limit": limit,
            "has_more": has_more,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502, detail=f"OpenGenome2 Hub request failed: {exc}"
        ) from exc


@app.get("/api/v1/integrations/opengenome2/metadata")
def opengenome2_metadata(revision: str = "main", limit: int = 50) -> dict:
    if not 1 <= limit <= 200:
        raise HTTPException(422, detail="limit must be between 1 and 200")
    repo_id = "arcinstitute/opengenome2"
    token = os.environ.get("HF_TOKEN")
    max_bytes = int(os.environ.get("GQI_METADATA_MAX_BYTES", str(10 * 1024**2)))
    try:
        hub = HfApi(token=token)
        info = hub.repo_info(repo_id, repo_type="dataset", revision=revision)
        resolved_revision = info.sha
        files = hub.get_paths_info(
            repo_id,
            paths=["species_metadata.csv"],
            revision=resolved_revision,
            repo_type="dataset",
            token=token,
        )
        if not files:
            raise HTTPException(
                404, detail="OpenGenome2 species_metadata.csv was not found"
            )
        metadata_size = getattr(files[0], "size", None)
        if metadata_size is None:
            raise HTTPException(
                404, detail="OpenGenome2 species_metadata.csv was not found"
            )
        if metadata_size > max_bytes:
            raise HTTPException(
                413,
                detail=f"Metadata preview is {metadata_size} bytes; configured limit is {max_bytes} bytes",
            )
        cached = hf_hub_download(
            repo_id,
            filename="species_metadata.csv",
            repo_type="dataset",
            revision=resolved_revision,
            token=token,
        )
        source_bytes = Path(cached).stat().st_size
        if source_bytes > max_bytes:
            raise HTTPException(
                413, detail="Downloaded metadata exceeded the configured limit"
            )
        with Path(cached).open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            rows = list(islice(reader, limit))
        return {
            "repository": repo_id,
            "revision": resolved_revision,
            "filename": "species_metadata.csv",
            "columns": columns,
            "rows": rows,
            "limit": limit,
            "truncated": len(rows) == limit,
            "source_bytes": source_bytes,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502, detail=f"OpenGenome2 metadata preview failed: {exc}"
        ) from exc


@app.post("/api/v1/integrations/opengenome2/import", status_code=201)
def import_opengenome2_file(body: OpenGenomeImportRequest) -> dict:
    if body.dataset_type not in TYPES:
        raise HTTPException(
            422, detail=f"dataset_type must be one of {', '.join(sorted(TYPES))}"
        )
    path = body.path
    if ".." in path.split("/") or not path.startswith("fasta/"):
        raise HTTPException(
            422,
            detail="Only selected FASTA shards from the fasta/ category can be imported",
        )
    lower = path.lower()
    base = lower.removesuffix(".gz")
    suffix = Path(base).suffix
    if suffix not in SUPPORTED - {".fq", ".fastq"}:
        raise HTTPException(
            415, detail="OpenGenome2 imports currently require a FASTA shard"
        )
    server_limit = min(
        int(os.environ.get("GQI_IMPORT_MAX_BYTES", str(1024**3))),
        int(os.environ.get("GQI_MAX_UPLOAD_BYTES", str(5 * 1024**3))),
        body.max_bytes,
    )
    repo_id = "arcinstitute/opengenome2"
    token = os.environ.get("HF_TOKEN")
    identifier = str(uuid.uuid4())
    dest = DATA_DIR / "uploads" / identifier
    dest.mkdir(parents=True, exist_ok=True)
    try:
        hub = HfApi(token=token)
        resolved = hub.repo_info(repo_id, repo_type="dataset", revision=body.revision)
        revision = resolved.sha
        infos = hub.get_paths_info(
            repo_id, paths=[path], revision=revision, repo_type="dataset", token=token
        )
        if not infos or not hasattr(infos[0], "size"):
            raise HTTPException(404, detail="Selected OpenGenome2 shard was not found")
        size = infos[0].size
        if size is None:
            raise HTTPException(
                502,
                detail="Hub did not provide the shard size; refusing an unbounded import",
            )
        if size > server_limit:
            raise HTTPException(
                413,
                detail=f"Shard is {size} bytes; configured import limit is {server_limit} bytes",
            )
        cached = hf_hub_download(
            repo_id,
            filename=path,
            repo_type="dataset",
            revision=revision,
            token=token,
        )
        actual_source_size = Path(cached).stat().st_size
        if actual_source_size > server_limit:
            raise HTTPException(
                413, detail="Downloaded shard exceeded the configured import limit"
            )
        filename = Path(path).name
        stored_name = filename.removesuffix(".gz")
        stored = dest / stored_name
        reservoir: list[SeqRecord] = []
        rng = random.Random(body.sample_seed)
        source_record_count = 0
        sequence_bases = 0
        try:
            with (
                (
                    gzip.open(cached, "rt", encoding="utf-8")
                    if lower.endswith(".gz")
                    else Path(cached).open(encoding="utf-8")
                ) as source,
                stored.open("w", encoding="utf-8") as output,
            ):
                bounded_source = BoundedTextReader(source, server_limit)
                for record in SeqIO.parse(bounded_source, "fasta"):
                    source_record_count += 1
                    sequence_bases += len(record.seq)
                    if sequence_bases > server_limit:
                        raise HTTPException(
                            413,
                            detail="Expanded FASTA data exceeded the configured import limit",
                        )
                    if body.sample_size == 0:
                        SeqIO.write(record, output, "fasta")
                    elif len(reservoir) < body.sample_size:
                        reservoir.append(record)
                    else:
                        replacement = rng.randrange(source_record_count)
                        if replacement < body.sample_size:
                            reservoir[replacement] = record
                if body.sample_size:
                    SeqIO.write(reservoir, output, "fasta")
        except HTTPException:
            raise
        except (OSError, UnicodeError, ValueError) as exc:
            raise HTTPException(
                422, detail=f"Could not parse selected FASTA shard: {exc}"
            ) from exc
        if source_record_count == 0:
            raise HTTPException(422, detail="Selected shard contains no FASTA records")
        actual_size = stored.stat().st_size
        if actual_size > server_limit:
            raise HTTPException(
                413, detail="Processed shard exceeded the configured import limit"
            )
        selected_count = (
            source_record_count
            if body.sample_size == 0
            else min(source_record_count, body.sample_size)
        )
        did_sample = selected_count < source_record_count
        sampling = {
            "sampled": did_sample,
            "sample_size": selected_count,
            "source_record_count": source_record_count,
            "method": "reservoir" if did_sample else "all_records",
            "seed": body.sample_seed if did_sample else None,
            "source_file_size_bytes": actual_source_size,
            "source_path": path,
            "source_oid": getattr(infos[0], "blob_id", None),
        }
        d = Dataset(
            id=identifier,
            name=Path(
                filename[:-3] if filename.lower().endswith(".gz") else filename
            ).stem,
            description=f"Imported from OpenGenome2 at revision {revision}; "
            + (
                f"reservoir sample of {selected_count:,} records."
                if did_sample
                else f"all {selected_count:,} records included."
            ),
            filename=filename,
            path=str(stored),
            format="fasta" + (".gz" if lower.endswith(".gz") else ""),
            dataset_type=body.dataset_type,
            data_source=repo_id,
            source_revision=revision,
            sampling_json=json.dumps(sampling),
            bytes=actual_size,
        )
        with Session() as db:
            db.add(d)
            db.commit()
            return public(d)
    except HTTPException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(502, detail=f"OpenGenome2 import failed: {exc}") from exc


@app.post("/api/v1/integrations/opengenome2/import-jsonl", status_code=201)
def import_opengenome2_jsonl(body: OpenGenomeJsonlImportRequest) -> dict:
    path = body.path
    if not path.startswith("jsonl/") or ".." in path.split("/") or path.lower().endswith(".gz"):
        raise HTTPException(422, detail="Select a plain JSONL shard under jsonl/; compressed shards are not range-readable")
    repo_id = "arcinstitute/opengenome2"
    token = os.environ.get("HF_TOKEN")
    try:
        info = HfApi(token=token).repo_info(repo_id, repo_type="dataset", revision=body.revision)
        revision = info.sha
        paths = HfApi(token=token).get_paths_info(repo_id, paths=[path], revision=revision, repo_type="dataset", token=token)
        source_size_value = getattr(paths[0], "size", None) if paths else None
        if not isinstance(source_size_value, int):
            raise HTTPException(404, detail="Selected JSONL shard was not found or has no known size")
        source_size = source_size_value
        byte_limit = min(body.max_bytes, int(os.environ.get("GQI_JSONL_PORTION_MAX_BYTES", str(16 * 1024**2))))
        if source_size <= 0:
            raise HTTPException(422, detail="Selected JSONL shard is empty")
        endpoint = f"https://huggingface.co/datasets/{repo_id}/resolve/{revision}/{quote(path, safe='/')}"
        headers = {"Range": f"bytes=0-{byte_limit - 1}"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with urlopen(Request(endpoint, headers=headers), timeout=45) as response:
            data = response.read(byte_limit + 1)
        if len(data) > byte_limit:
            data = data[:byte_limit]
        lines = data.splitlines()
        # A bounded range can end in the middle of a JSON object. Keep only complete lines.
        if data and not data.endswith((b"\n", b"\r")):
            lines = lines[:-1]
        rng = random.Random(body.sample_seed)
        reservoir: list[tuple[str, str, list[str]]] = []
        seen = 0
        token_counts: dict[str, int] = {}
        candidate_keys = {"sequence", "dna", "nucleotide_sequence", "sequence_text", "text", "content"}
        special_token = re.compile(r"<[^>]{1,120}>")
        for line_number, raw_line in enumerate(lines, 1):
            if not raw_line.strip():
                continue
            if len(raw_line) > 1024 * 1024:
                continue
            try:
                payload = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            candidates: list[str] = []
            tags: set[str] = set()
            def visit(value, found_candidates: list[str], found_tags: set[str]) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key.lower() in {"tag", "tags", "special_tokens", "tokens", "label"}:
                            values = child if isinstance(child, list) else [child]
                            for entry in values:
                                if isinstance(entry, (str, int, float)):
                                    found_tags.add(str(entry)[:120])
                        if key.lower() in candidate_keys and isinstance(child, str):
                            found_candidates.append(child)
                        else:
                            visit(child, found_candidates, found_tags)
                elif isinstance(value, list):
                    for child in value:
                        visit(child, found_candidates, found_tags)
            visit(payload, candidates, tags)
            chosen = None
            for candidate in sorted(candidates, key=len, reverse=True):
                found_tokens = special_token.findall(candidate)
                tags.update(found_tokens)
                sequence = special_token.sub("", candidate)
                sequence = re.sub(r"\s+", "", sequence).upper()
                if sequence and re.fullmatch(r"[ACGTUNRYSWKMBDHV]+", sequence):
                    chosen = sequence
                    break
            if not chosen:
                continue
            seen += 1
            for tag in tags:
                token_counts[tag] = token_counts.get(tag, 0) + 1
            item = (f"portion_record_{line_number}", chosen, sorted(tags))
            if len(reservoir) < body.sample_size:
                reservoir.append(item)
            else:
                replacement = rng.randrange(seen)
                if replacement < body.sample_size:
                    reservoir[replacement] = item
        if not reservoir:
            raise HTTPException(422, detail="No sequence-bearing JSONL examples were found in the bounded prefix")
        identifier = str(uuid.uuid4())
        dest = DATA_DIR / "uploads" / identifier
        dest.mkdir(parents=True, exist_ok=True)
        stored = dest / (Path(path).stem + ".fasta")
        with stored.open("w", encoding="utf-8") as output:
            for record_id, sequence, record_tags in reservoir:
                header = record_id + (" tags=" + ",".join(tag.replace(" ", "_") for tag in record_tags) if record_tags else "")
                output.write(f">{header}\n")
                for offset in range(0, len(sequence), 80):
                    output.write(sequence[offset:offset + 80] + "\n")
        sampling = {"sampled": True, "portion_limited": True, "sample_size": len(reservoir), "source_record_count": seen, "method": "reservoir_within_byte_range", "seed": body.sample_seed, "source_path": path, "source_file_size_bytes": source_size, "bytes_read": min(len(data), byte_limit), "portion_start": 0, "training_tag_counts": token_counts}
        dataset = Dataset(id=identifier, name=Path(path).stem, description=f"OpenGenome2 JSONL prefix portion ({sampling['bytes_read']:,} bytes); sequence examples are sampled from complete lines only.", filename=stored.name, path=str(stored), format="fasta", dataset_type="training_corpus", data_source=repo_id, source_revision=revision, sampling_json=json.dumps(sampling), bytes=stored.stat().st_size)
        with Session() as db:
            db.add(dataset)
            db.commit()
            return public(dataset)
    except HTTPException:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeError) as exc:
        raise HTTPException(502, detail=f"OpenGenome2 JSONL portion request failed: {exc}") from exc


@app.get("/api/datasets")
@app.get("/api/v1/datasets")
def list_datasets(q: str = "", offset: int = 0, limit: int = 50) -> dict:
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(
            422, detail="offset must be nonnegative and limit must be between 1 and 100"
        )
    with Session() as db:
        rows = db.scalars(select(Dataset).order_by(Dataset.created_at.desc())).all()
        rows = [
            d
            for d in rows
            if q.lower() in (d.name + " " + d.filename + " " + d.dataset_type).lower()
        ]
        return {
            "items": [public(d) for d in rows[offset : offset + limit]],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
        }


@app.post("/api/datasets", status_code=201)
@app.post("/api/v1/datasets", status_code=201)
async def upload_dataset(
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form()] = None,
    dataset_type: Annotated[str | None, Form()] = None,
    description: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
) -> dict:
    filename = Path(file.filename or "upload").name
    lower = filename.lower()
    gz = lower.endswith(".gz")
    base = lower[:-3] if gz else lower
    suffix = Path(base).suffix
    if suffix not in SUPPORTED:
        raise HTTPException(
            415,
            detail="Supported formats: FASTA (.fa/.fasta/.fna/.ffn) and FASTQ (.fq/.fastq), optionally gzip-compressed",
        )
    fmt = "fastq" if suffix in {".fq", ".fastq"} else "fasta"
    inferred = "raw_reads" if fmt == "fastq" else "sequence_collection"
    dtype = dataset_type or inferred
    if dtype not in TYPES:
        raise HTTPException(
            422, detail=f"dataset_type must be one of {', '.join(sorted(TYPES))}"
        )
    max_bytes = int(os.environ.get("GQI_MAX_UPLOAD_BYTES", str(5 * 1024**3)))
    identifier = str(uuid.uuid4())
    dest = DATA_DIR / "uploads" / identifier
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / filename
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        413, detail=f"Upload exceeds configured {max_bytes} byte limit"
                    )
                out.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(422, detail="Uploaded file is empty")
    d = Dataset(
        id=identifier,
        name=(name or Path(filename).stem)[:300],
        description=description[:4000],
        filename=filename,
        path=str(path),
        format=(fmt + (".gz" if gz else "")),
        dataset_type=dtype,
        tags_json=json.dumps(sorted({tag.strip()[:60] for tag in tags.split(",") if tag.strip()})),
        bytes=size,
    )
    with Session() as db:
        db.add(d)
        db.commit()
        return public(d)


@app.post("/api/v1/datasets/batch", status_code=201)
async def upload_datasets_batch(
    files: Annotated[list[UploadFile], File()],
    dataset_type: Annotated[str | None, Form()] = None,
    tags: Annotated[str, Form()] = "",
) -> dict:
    if not files or len(files) > 20:
        raise HTTPException(422, detail="batch upload accepts between 1 and 20 files")
    items = []
    for item in files:
        items.append(await upload_dataset(item, None, dataset_type, "", tags))
    return {"items": items}


@app.post("/api/v1/datasets/import-local", status_code=201)
def import_local_path(body: LocalPathImportRequest) -> dict:
    roots = [Path(value).expanduser().resolve() for value in os.environ.get("GQI_LOCAL_IMPORT_DIRS", "").split(os.pathsep) if value.strip()]
    if not roots:
        raise HTTPException(403, detail="Local path imports are disabled; configure GQI_LOCAL_IMPORT_DIRS")
    source = Path(body.path).expanduser().resolve()
    if not any(source == root or root in source.parents for root in roots):
        raise HTTPException(403, detail="Path must be inside a configured GQI_LOCAL_IMPORT_DIRS directory")
    if not source.is_file():
        raise HTTPException(404, detail="Local source file not found")
    filename = source.name
    if Path(filename.removesuffix(".gz")).suffix.lower() not in SUPPORTED:
        raise HTTPException(415, detail="Source must be FASTA or FASTQ, optionally gzip compressed")
    max_bytes = int(os.environ.get("GQI_MAX_UPLOAD_BYTES", str(5 * 1024**3)))
    if source.stat().st_size > max_bytes:
        raise HTTPException(413, detail=f"Local source exceeds configured {max_bytes} byte limit")
    identifier = str(uuid.uuid4())
    dest = DATA_DIR / "uploads" / identifier
    dest.mkdir(parents=True, exist_ok=True)
    stored = dest / filename
    shutil.copyfile(source, stored)
    return register_external_sequence_file(stored, filename, body.dataset_type, body.tags, "local_path")


@app.post("/api/v1/datasets/import-url", status_code=201)
def import_source_url(body: SourceUrlImportRequest) -> dict:
    parsed = urlparse(body.url)
    allowed_hosts = {host.strip().lower() for host in os.environ.get("GQI_SOURCE_URL_HOSTS", "").split(",") if host.strip()}
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in allowed_hosts or parsed.port not in {None, 443} or parsed.username or parsed.password:
        raise HTTPException(403, detail="Source URLs require HTTPS and a host listed in GQI_SOURCE_URL_HOSTS")
    pinned_ip = validate_public_https_host(parsed.hostname)
    filename = Path(parsed.path).name
    if not filename or Path(filename.removesuffix(".gz")).suffix.lower() not in SUPPORTED:
        raise HTTPException(415, detail="Source URL must point to FASTA or FASTQ, optionally gzip compressed")
    byte_limit = min(body.max_bytes, int(os.environ.get("GQI_URL_IMPORT_MAX_BYTES", str(256 * 1024**2))))
    identifier = str(uuid.uuid4())
    dest = DATA_DIR / "uploads" / identifier
    dest.mkdir(parents=True, exist_ok=True)
    stored = dest / filename
    try:
        request = Request(body.url, headers={"User-Agent": "GenomeQualityInspector/0.1"})
        opener = build_opener(
            ProxyHandler({}), NoRedirectHandler(), _PinnedHTTPSHandler(pinned_ip)
        )
        with opener.open(request, timeout=45) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or not final.hostname or final.hostname.lower() not in allowed_hosts:
                raise HTTPException(403, detail="Redirect target is not an allowed HTTPS source host")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > byte_limit:
                raise HTTPException(413, detail=f"Source exceeds configured {byte_limit} byte limit")
            size = 0
            with stored.open("wb") as output:
                while chunk := response.read(min(1024 * 1024, byte_limit + 1 - size)):
                    size += len(chunk)
                    if size > byte_limit:
                        raise HTTPException(413, detail=f"Source exceeds configured {byte_limit} byte limit")
                    output.write(chunk)
        return register_external_sequence_file(stored, filename, body.dataset_type, body.tags, "source_url")
    except HTTPException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(502, detail=f"Could not import sequence URL: {exc}") from exc


@app.get("/api/datasets/{dataset_id}")
@app.get("/api/v1/datasets/{dataset_id}")
def get_dataset(dataset_id: str) -> dict:
    with Session() as db:
        d = db.get(Dataset, dataset_id)
        if not d:
            raise HTTPException(404, detail="dataset not found")
        return public(d)


@app.post("/api/v1/datasets/{dataset_id}/metadata", status_code=201)
async def upload_taxonomy_metadata(
    dataset_id: str,
    file: Annotated[UploadFile, File()],
    source: Annotated[str, Form()] = "user_metadata",
    release: Annotated[str | None, Form()] = None,
) -> dict:
    filename = Path(file.filename or "metadata.csv").name.lower()
    if Path(filename).suffix not in {".csv", ".tsv", ".txt"}:
        raise HTTPException(415, detail="Metadata mapping must be CSV or TSV")
    content = await file.read(20 * 1024**2 + 1)
    if len(content) > 20 * 1024**2:
        raise HTTPException(413, detail="Metadata file exceeds 20 MiB")
    delimiter = "\t" if Path(filename).suffix == ".tsv" else ","
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=delimiter)
        columns = {column.strip().lower(): column for column in (reader.fieldnames or [])}
        sequence_column = next((columns[name] for name in ("sequence_id", "sequence", "seq_id", "record_id", "accession", "genome_accession") if name in columns), None)
        taxon_column = next((columns[name] for name in ("taxon_name", "taxon", "species", "organism", "scientific_name") if name in columns), None)
        if not sequence_column or not taxon_column:
            raise HTTPException(422, detail="Metadata needs an identifier column (sequence_id/accession) and a taxon column (taxon_name/species/organism)")
        taxon_id_column = next((columns[name] for name in ("taxon_id", "taxid", "ncbi_taxid", "gtdb_taxid") if name in columns), None)
        rank_column = next((columns[name] for name in ("rank", "taxon_rank") if name in columns), None)
        mappings = []
        for line_number, row in enumerate(reader, start=2):
            sequence_id = (row.get(sequence_column) or "").strip().split()[0] if (row.get(sequence_column) or "").strip() else ""
            taxon_name = (row.get(taxon_column) or "").strip()
            if not sequence_id or not taxon_name:
                continue
            mappings.append(TaxonomyMapping(id=str(uuid.uuid4()), dataset_id=dataset_id, sequence_id=sequence_id[:500], taxon_name=taxon_name[:500], taxon_id=((row.get(taxon_id_column) or "").strip()[:80] or None) if taxon_id_column else None, rank=((row.get(rank_column) or "").strip()[:80] or None) if rank_column else None, source=source[:120], release=release[:120] if release else None))
            if len(mappings) > 250000:
                raise HTTPException(413, detail="Metadata file exceeds 250,000 mapping rows")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, detail="Metadata file must be UTF-8 encoded") from exc
    except csv.Error as exc:
        raise HTTPException(422, detail=f"Could not parse metadata table: {exc}") from exc
    if not mappings:
        raise HTTPException(422, detail="Metadata table contains no usable sequence-to-taxon mappings")
    with Session() as db:
        if not db.get(Dataset, dataset_id):
            raise HTTPException(404, detail="dataset not found")
        db.query(TaxonomyMapping).filter(TaxonomyMapping.dataset_id == dataset_id).delete()
        db.add_all(mappings)
        db.commit()
    return {"dataset_id": dataset_id, "mapping_count": len(mappings), "source": source, "release": release, "sequence_column": sequence_column, "taxon_column": taxon_column}


@app.get("/api/v1/datasets/{dataset_id}/taxonomy")
def dataset_taxonomy(dataset_id: str, rank: str | None = None) -> dict:
    with Session() as db:
        dataset = db.get(Dataset, dataset_id)
        if not dataset:
            raise HTTPException(404, detail="dataset not found")
        if not dataset.analysis_json:
            raise HTTPException(409, detail="analysis is not complete")
        analysis = json.loads(dataset.analysis_json)
        records = analysis.get("records", [])
        mappings = db.scalars(select(TaxonomyMapping).where(TaxonomyMapping.dataset_id == dataset_id)).all()
        if rank:
            mappings = [mapping for mapping in mappings if (mapping.rank or "").lower() == rank.lower()]
        by_sequence = {mapping.sequence_id: mapping for mapping in mappings}
        aggregates: dict[tuple[str, str | None, str | None], dict[str, int]] = {}
        mapped_sequences = 0
        mapped_bases = 0
        for record in records:
            sequence_key = record["id"].split()[0] if record["id"].split() else ""
            mapping = by_sequence.get(sequence_key)
            if not mapping:
                continue
            mapped_sequences += 1
            mapped_bases += record["length"]
            key = (mapping.taxon_name, mapping.taxon_id, mapping.rank)
            item = aggregates.setdefault(key, {"sequence_count": 0, "nucleotide_count": 0})
            item["sequence_count"] += 1
            item["nucleotide_count"] += record["length"]
        items = [{"taxon_name": key[0], "taxon_id": key[1], "rank": key[2], **values} for key, values in aggregates.items()]
        items.sort(key=lambda item: (-int(str(item["sequence_count"])), str(item["taxon_name"] or "").casefold()))
        return {"dataset_id": dataset_id, "source": mappings[0].source if mappings else None, "release": mappings[0].release if mappings else None, "rank_filter": rank, "items": items, "sequence_count": len(records), "mapped_sequence_count": mapped_sequences, "unmapped_sequence_count": len(records) - mapped_sequences, "mapped_nucleotide_count": mapped_bases, "unmapped_nucleotide_count": analysis.get("total_bases", 0) - mapped_bases, "interpretation": "Imported source metadata aggregation; this is not a sequence-based taxonomic classification."}


@app.patch("/api/datasets/{dataset_id}")
@app.patch("/api/v1/datasets/{dataset_id}")
def rename_dataset(dataset_id: str, body: RenameRequest) -> dict:
    with Session() as db:
        d = db.get(Dataset, dataset_id)
        if not d:
            raise HTTPException(404, detail="dataset not found")
        d.name = body.name
        d.description = body.description
        d.tags_json = json.dumps(sorted({tag.strip()[:60] for tag in body.tags if tag.strip()}))
        db.commit()
        return public(d)


@app.post("/api/datasets/{dataset_id}/analysis", status_code=202)
@app.post("/api/v1/datasets/{dataset_id}/analyze", status_code=202)
def analyze_dataset(dataset_id: str, request: AnalysisRequest | None = None) -> dict:
    config = request or AnalysisRequest()
    run_id = str(uuid.uuid4())
    with Session() as db:
        d = db.get(Dataset, dataset_id)
        if not d:
            raise HTTPException(404, detail="dataset not found")
        if d.status in {"running", "queued"}:
            raise HTTPException(409, detail="analysis is already running")
        d.status = "queued"
        d.error = None
        db.add(
            AnalysisRun(
                id=run_id,
                dataset_id=dataset_id,
                status="queued",
                config_json=json.dumps({"k": config.k, "dataset_type": d.dataset_type}),
            )
        )
        db.commit()
    try:
        start_analysis(dataset_id, run_id, config.k)
    except Exception as exc:
        with Session() as db:
            d = db.get(Dataset, dataset_id)
            run = db.get(AnalysisRun, run_id)
            if d:
                d.status = "failed"
                d.error = f"Could not enqueue analysis: {exc}"[:4000]
            if run:
                run.status = "failed"
                run.error = d.error if d else "Could not enqueue analysis"
                run.completed_at = datetime.now(UTC)
            if d or run:
                db.commit()
        raise HTTPException(
            503,
            detail="Analysis queue is unavailable; check the Redis connection and worker",
        ) from exc
    return {
        "dataset_id": dataset_id,
        "analysis_id": run_id,
        "status": "queued",
        "config": {"k": config.k},
    }


@app.get("/api/datasets/{dataset_id}/analyses")
@app.get("/api/v1/datasets/{dataset_id}/analyses")
def list_analyses(dataset_id: str, offset: int = 0, limit: int = 50) -> dict:
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, detail="invalid analysis pagination")
    with Session() as db:
        if not db.get(Dataset, dataset_id):
            raise HTTPException(404, detail="dataset not found")
        query = (
            select(AnalysisRun)
            .where(AnalysisRun.dataset_id == dataset_id)
            .order_by(AnalysisRun.created_at.desc())
        )
        rows = db.scalars(query).all()
        return {
            "items": [
                public_run(run, include_result=False)
                for run in rows[offset : offset + limit]
            ],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
        }


@app.get("/api/analyses/{analysis_id}")
@app.get("/api/v1/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    with Session() as db:
        run = db.get(AnalysisRun, analysis_id)
        if not run:
            raise HTTPException(404, detail="analysis not found")
        return public_run(run)


@app.get("/api/analyses/{analysis_id}/events")
@app.get("/api/v1/analyses/{analysis_id}/events")
async def analysis_events(analysis_id: str):
    with Session() as db:
        if not db.get(AnalysisRun, analysis_id):
            raise HTTPException(404, detail="analysis not found")

    async def events():
        while True:
            with Session() as db:
                run = db.get(AnalysisRun, analysis_id)
                if run is None:
                    return
                snapshot = {"id": run.id, "status": run.status, "error": run.error}
            yield f"event: status\ndata: {json.dumps(snapshot)}\n\n"
            if snapshot["status"] in {"complete", "failed"}:
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/datasets/{dataset_id}/sequences")
@app.get("/api/v1/datasets/{dataset_id}/sequences")
def sequences(
    dataset_id: str,
    q: str = "",
    min_length: int = 0,
    max_length: int | None = None,
    offset: int = 0,
    limit: int = 100,
    exclude_outliers: bool = False,
) -> dict:
    with Session() as db:
        d = db.get(Dataset, dataset_id)
        if not d:
            raise HTTPException(404, detail="dataset not found")
        if not d.analysis_json:
            raise HTTPException(409, detail="analysis is not complete")
        if min_length < 0 or offset < 0 or not 1 <= limit <= 500:
            raise HTTPException(422, detail="invalid sequence filter or pagination")
        records = json.loads(d.analysis_json)["records"]
        outlier_count = 0
        if exclude_outliers and records:
            ordered_lengths = sorted(record["length"] for record in records)
            q1 = ordered_lengths[(len(ordered_lengths) - 1) // 4]
            q3 = ordered_lengths[((len(ordered_lengths) - 1) * 3) // 4]
            lower_fence, upper_fence = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
            kept = [record for record in records if lower_fence <= record["length"] <= upper_fence]
            outlier_count = len(records) - len(kept)
            records = kept
        rows = [
            r
            for r in records
            if min_length <= r["length"]
            and (max_length is None or r["length"] <= max_length)
            and q.lower() in r["id"].lower()
        ]
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "outliers_excluded": outlier_count,
        }


@app.get("/api/v1/datasets/{dataset_id}/sequence-window")
@app.get("/api/v1/datasets/{dataset_id}/sequences/{sequence_id}/window")
def sequence_window(
    dataset_id: str,
    record_id: str | None = None,
    start: int = 0,
    end: int = 1000,
    sequence_id: str | None = None,
) -> dict:
    """Return a bounded, zero-based half-open sequence window for one record."""
    if start < 0 or end <= start or end - start > 10000:
        raise HTTPException(422, detail="window must be 1..10000 bases with nonnegative coordinates")
    requested_id = sequence_id or record_id
    if not requested_id:
        raise HTTPException(422, detail="sequence identifier is required")
    with Session() as db:
        d = db.get(Dataset, dataset_id)
        if not d:
            raise HTTPException(404, detail="dataset not found")
        if not Path(d.path).is_file():
            raise HTTPException(404, detail="dataset file is unavailable")
        opener = gzip.open if d.path.lower().endswith(".gz") else open
        fmt = "fastq" if d.format.startswith("fastq") else "fasta"
        with opener(d.path, "rt", encoding="utf-8") as handle:
            for record in SeqIO.parse(handle, fmt):
                if record.id == requested_id or record.description == requested_id:
                    sequence = str(record.seq).upper()
                    left, right = min(start, len(sequence)), min(end, len(sequence))
                    window = sequence[left:right]
                    gc_track = []
                    ambiguous_track = []
                    entropy_track = []
                    for offset in range(0, len(window), 100):
                        chunk = window[offset : offset + 100]
                        canonical = sum(base in "ACGT" for base in chunk)
                        gc_count = chunk.count("G") + chunk.count("C")
                        frequencies = [chunk.count(base) for base in set(chunk)]
                        entropy_bits = -sum((count / len(chunk)) * math.log2(count / len(chunk)) for count in frequencies) if chunk else None
                        gc_track.append({"start": left + offset, "end": left + offset + len(chunk), "value": gc_count / canonical * 100 if canonical else None})
                        ambiguous_track.append({"start": left + offset, "end": left + offset + len(chunk), "value": sum(base not in "ACGT" for base in chunk)})
                        entropy_track.append({"start": left + offset, "end": left + offset + len(chunk), "value": entropy_bits})
                    return {"record_id": record.id, "length": len(sequence), "start": left, "end": right, "sequence": window, "tracks": {"gc_percent_100bp": gc_track, "noncanonical_bases_100bp": ambiguous_track, "shannon_entropy_100bp": entropy_track}}
        raise HTTPException(404, detail="sequence identifier not found")


@app.get("/api/v1/datasets/{dataset_id}/sequences/{sequence_id}")
def sequence_detail(dataset_id: str, sequence_id: str) -> dict:
    with Session() as db:
        d = db.get(Dataset, dataset_id)
        if not d:
            raise HTTPException(404, detail="dataset not found")
        if not d.analysis_json:
            raise HTTPException(409, detail="analysis is not complete")
        row = next((r for r in json.loads(d.analysis_json).get("records", []) if r["id"] == sequence_id), None)
        if row is None:
            raise HTTPException(404, detail="sequence identifier not found")
        return row


@app.get("/api/v1/datasets/{dataset_id}/sequences/{sequence_id}/regions")
def sequence_regions(dataset_id: str, sequence_id: str) -> dict:
    detail = sequence_detail(dataset_id, sequence_id)
    return {"sequence_id": sequence_id, "coordinate_system": "zero-based-half-open", "low_complexity_regions": detail.get("low_complexity_regions", [])}


@app.get("/api/v1/datasets/{dataset_id}/findings")
def list_findings(dataset_id: str, status: str = "all") -> dict:
    with Session() as db:
        if not db.get(Dataset, dataset_id):
            raise HTTPException(404, detail="dataset not found")
        query = select(Finding).where(Finding.dataset_id == dataset_id)
        if status in {"open", "acknowledged", "dismissed"}:
            query = query.where(Finding.status == status)
        elif status != "all":
            raise HTTPException(422, detail="status must be all, open, acknowledged, or dismissed")
        rows = db.scalars(query.order_by(Finding.created_at.desc())).all()
        return {"items": [{"id": f.id, "code": f.code, "severity": f.severity, "message": f.message, "status": f.status, "value": json.loads(f.value_json), "created_at": f.created_at.isoformat()} for f in rows]}


@app.patch("/api/v1/findings/{finding_id}")
def update_finding(finding_id: str, body: dict) -> dict:
    status = body.get("status")
    if status not in {"acknowledged", "dismissed", "open"}:
        raise HTTPException(422, detail="status must be acknowledged, dismissed, or open")
    with Session() as db:
        finding = db.get(Finding, finding_id)
        if not finding:
            raise HTTPException(404, detail="finding not found")
        finding.status = status
        db.commit()
        return {"id": finding.id, "status": finding.status}


@app.delete("/api/datasets/{dataset_id}", status_code=204)
@app.delete("/api/v1/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str) -> None:
    with Session() as db:
        d = db.get(Dataset, dataset_id)
        if not d:
            raise HTTPException(404, detail="dataset not found")
        path = Path(d.path)
        db.query(AnalysisRun).filter(AnalysisRun.dataset_id == dataset_id).delete()
        db.query(ToolRun).filter(ToolRun.dataset_id == dataset_id).delete()
        db.query(Finding).filter(Finding.dataset_id == dataset_id).delete()
        db.delete(d)
        db.commit()
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass


@app.get("/api/datasets/{dataset_id}/report")
@app.get("/api/v1/datasets/{dataset_id}/report")
def report(dataset_id: str) -> dict:
    with Session() as db:
        d = db.get(Dataset, dataset_id)
        if not d:
            raise HTTPException(404, detail="dataset not found")
        if not d.analysis_json:
            raise HTTPException(409, detail="analysis is not complete")
        return {
            "dataset": {k: v for k, v in public(d).items() if k != "analysis"},
            "analysis": json.loads(d.analysis_json),
            "generated_at": datetime.now(UTC).isoformat(),
        }


@app.post("/api/v1/comparisons")
def compare_datasets(body: ComparisonRequest) -> dict:
    if len(set(body.dataset_ids)) != len(body.dataset_ids):
        raise HTTPException(422, detail="dataset_ids must be unique")
    with Session() as db:
        datasets = [db.get(Dataset, identifier) for identifier in body.dataset_ids]
        if any(dataset is None for dataset in datasets):
            raise HTTPException(404, detail="one or more datasets were not found")
        concrete = [dataset for dataset in datasets if dataset is not None]
        if any(
            dataset.status != "complete" or not dataset.analysis_json
            for dataset in concrete
        ):
            raise HTTPException(
                409, detail="all compared datasets must have completed analyses"
            )
        items = []
        for dataset in concrete:
            analysis = json.loads(dataset.analysis_json or "{}")
            length = analysis.get("length", {})
            items.append(
                {
                    "id": dataset.id,
                    "name": dataset.name,
                    "dataset_type": dataset.dataset_type,
                    "data_source": dataset.data_source,
                    "source_revision": dataset.source_revision,
                    "sequence_count": analysis.get("sequence_count"),
                    "total_bases": analysis.get("total_bases"),
                    "gc_percent": analysis.get("gc_percent"),
                    "ambiguous_percent": analysis.get("ambiguous_percent"),
                    "duplicate_rate_percent": analysis.get("duplicate_rate_percent"),
                    "length_mean": length.get("mean"),
                    "length_median": length.get("median"),
                    "n50": analysis.get("n50"),
                    "sampled": bool(
                        json.loads(dataset.sampling_json or "{}").get("sampled")
                    ),
                }
            )
        baseline = items[0]
        delta_metrics = (
            "sequence_count",
            "total_bases",
            "gc_percent",
            "ambiguous_percent",
            "duplicate_rate_percent",
            "length_mean",
            "length_median",
            "n50",
        )
        comparisons = []
        for item in items[1:]:
            deltas = {}
            for metric in delta_metrics:
                left, right = baseline[metric], item[metric]
                deltas[metric] = (
                    right - left if left is not None and right is not None else None
                )
            comparisons.append(
                {
                    "baseline_id": baseline["id"],
                    "dataset_id": item["id"],
                    "deltas": deltas,
                }
            )
        different_types = len({item["dataset_type"] for item in items}) > 1
        result = {
            "items": items,
            "baseline_id": baseline["id"],
            "comparisons": comparisons,
            "warnings": [
                "These datasets have different declared input types; interpret comparisons with care."
            ]
            if different_types
            else [],
            "generated_at": datetime.now(UTC).isoformat(),
        }
        saved = Comparison(id=str(uuid.uuid4()), name=body.name, dataset_ids_json=json.dumps(body.dataset_ids), result_json=json.dumps(result))
        db.add(saved)
        db.commit()
        result["comparison_id"] = saved.id
        return result


@app.get("/api/v1/comparisons")
def list_comparisons(offset: int = 0, limit: int = 50) -> dict:
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, detail="invalid pagination")
    with Session() as db:
        rows = db.scalars(select(Comparison).order_by(Comparison.created_at.desc()).offset(offset).limit(limit)).all()
        return {"items": [{"id": row.id, "name": row.name, "dataset_ids": json.loads(row.dataset_ids_json), "result": json.loads(row.result_json), "created_at": row.created_at.isoformat()} for row in rows]}


@app.get("/api/v1/comparisons/{comparison_id}")
def get_comparison(comparison_id: str) -> dict:
    with Session() as db:
        row = db.get(Comparison, comparison_id)
        if not row:
            raise HTTPException(404, detail="comparison not found")
        return {"id": row.id, "name": row.name, "dataset_ids": json.loads(row.dataset_ids_json), "result": json.loads(row.result_json), "created_at": row.created_at.isoformat()}


@app.delete("/api/v1/comparisons/{comparison_id}", status_code=204)
def delete_comparison(comparison_id: str) -> None:
    with Session() as db:
        row = db.get(Comparison, comparison_id)
        if not row:
            raise HTTPException(404, detail="comparison not found")
        db.delete(row)
        db.commit()
