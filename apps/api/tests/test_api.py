import gzip
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

# Keep API tests isolated from a developer's actual local data database.
test_data_dir = tempfile.mkdtemp(prefix="gqi-api-tests-")
os.environ.setdefault("GQI_DATA_DIR", os.path.join(test_data_dir, "data"))
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + os.path.join(test_data_dir, "test.sqlite3")
)

from gqi_api.main import Base, app, engine

Base.metadata.create_all(engine)
client = TestClient(app)


def test_health_reports_database():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert client.get("/api/v1/ready").json() == {"ready": True}
    assert client.get("/api/v1/capabilities").status_code == 200


def test_cors_headers_for_local_origins():
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:3008",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:3008"


def test_upload_fasta_registers_real_file():
    response = client.post(
        "/api/datasets",
        files={"file": ("fixture.fasta", b">one\nACGT\n", "text/plain")},
        data={"name": "fixture"},
    )
    assert response.status_code == 201
    dataset = response.json()
    assert dataset["name"] == "fixture"
    assert dataset["format"] == "fasta"
    assert dataset["dataset_type"] == "sequence_collection"
    assert dataset["bytes"] == 10
    assert dataset["status"] == "uploaded"
    assert (
        client.get(f"/api/datasets/{dataset['id']}").json()["filename"]
        == "fixture.fasta"
    )
    assert client.delete(f"/api/datasets/{dataset['id']}").status_code == 204


def test_upload_rejects_unsupported_files():
    response = client.post(
        "/api/datasets", files={"file": ("protein.faa", b">x\nMKWV\n")}
    )
    assert response.status_code == 415


def test_upload_honors_explicit_dataset_type():
    response = client.post(
        "/api/datasets",
        files={"file": ("assembly.fa", b">ctg\nACGT\n")},
        data={"dataset_type": "genome_assembly"},
    )
    assert response.status_code == 201
    dataset = response.json()
    assert dataset["dataset_type"] == "genome_assembly"
    assert client.delete(f"/api/datasets/{dataset['id']}").status_code == 204


def test_quast_requires_an_assembly_dataset(monkeypatch):
    from gqi_api import main

    uploaded = client.post(
        "/api/v1/datasets",
        files={"file": ("reads.fa", b">read\nACGT\n")},
    )
    identifier = uploaded.json()["id"]
    monkeypatch.setattr(main.shutil, "which", lambda _name: "/usr/bin/quast.py")
    response = client.post(f"/api/v1/datasets/{identifier}/integrations/quast")
    assert response.status_code == 422
    assert "genome_assembly" in response.json()["detail"]
    assert client.delete(f"/api/v1/datasets/{identifier}").status_code == 204


def test_pagination_bounds_are_validated():
    assert client.get("/api/datasets?limit=101").status_code == 422


def test_queue_error_is_saved_and_returned_as_service_unavailable(monkeypatch):
    from gqi_api import main

    uploaded = client.post("/api/datasets", files={"file": ("queue.fa", b">x\nACGT\n")})
    identifier = uploaded.json()["id"]

    def unavailable(_dataset_id, _run_id, _k):
        raise RuntimeError("redis refused connection")

    monkeypatch.setattr(main, "start_analysis", unavailable)
    response = client.post(f"/api/datasets/{identifier}/analysis")
    assert response.status_code == 503
    assert "Redis connection" in response.json()["detail"]
    assert client.get(f"/api/datasets/{identifier}").json()["status"] == "failed"
    assert client.delete(f"/api/datasets/{identifier}").status_code == 204


def test_versioned_analysis_saves_config_and_run_history(monkeypatch):
    from gqi_api import main

    uploaded = client.post(
        "/api/v1/datasets", files={"file": ("history.fa", b">x\nACGT\n")}
    )
    identifier = uploaded.json()["id"]
    captured = []
    monkeypatch.setattr(
        main,
        "start_analysis",
        lambda dataset_id, run_id, k: captured.append((dataset_id, run_id, k)),
    )
    response = client.post(f"/api/v1/datasets/{identifier}/analyze", json={"k": 15})
    assert response.status_code == 202
    payload = response.json()
    assert payload["config"] == {"k": 15}
    assert captured == [(identifier, payload["analysis_id"], 15)]
    history = client.get(f"/api/v1/datasets/{identifier}/analyses").json()
    assert history["total"] == 1
    assert history["items"][0]["config"]["k"] == 15
    assert (
        client.get(f"/api/v1/analyses/{payload['analysis_id']}").json()["status"]
        == "queued"
    )
    assert client.delete(f"/api/v1/datasets/{identifier}").status_code == 204


def test_opengenome2_catalog_uses_repository_revision_and_limits(monkeypatch):
    from gqi_api import main

    class FakeHub:
        def __init__(self, token=None):
            pass

        def repo_info(self, repo_id, repo_type, revision):
            assert repo_id == "arcinstitute/opengenome2"
            return SimpleNamespace(sha="a" * 40)

        def list_repo_tree(self, repo_id, path_in_repo, recursive, revision, repo_type):
            assert revision == "a" * 40
            assert path_in_repo in {"fasta", "jsonl"}
            prefix = path_in_repo
            first = (
                f"{prefix}/bacteria/one.fasta.gz"
                if prefix == "fasta"
                else f"{prefix}/example.jsonl"
            )
            second = (
                f"{prefix}/bacteria/two.fasta.gz"
                if prefix == "fasta"
                else f"{prefix}/second.jsonl"
            )
            return [
                SimpleNamespace(path=first, size=100, blob_id="blob1"),
                SimpleNamespace(path=second, size=200, blob_id="blob2"),
            ]

    monkeypatch.setattr(main, "HfApi", FakeHub)
    response = client.get(
        "/api/v1/integrations/opengenome2/files?category=fasta&limit=1"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["revision"] == "a" * 40
    assert payload["files"][0]["path"] == "fasta/bacteria/one.fasta.gz"
    assert payload["files"][0]["size_bytes"] == 100
    assert payload["has_more"] is True
    jsonl = client.get("/api/v1/integrations/opengenome2/files?category=jsonl").json()
    assert jsonl["files"][0]["path"] == "jsonl/example.jsonl"


def test_opengenome2_import_pins_revision_and_source(monkeypatch, tmp_path):
    from gqi_api import main

    downloaded = tmp_path / "remote.fasta.gz"
    with gzip.open(downloaded, "wb") as handle:
        handle.write(b">seq1\nACGT\n>seq2\nGGCC\n>seq3\nTTAA\n")

    class FakeHub:
        def __init__(self, token=None):
            pass

        def repo_info(self, repo_id, repo_type, revision):
            return SimpleNamespace(sha="b" * 40)

        def get_paths_info(self, repo_id, paths, revision, repo_type, token):
            assert paths == ["fasta/bacteria/shard.fasta.gz"]
            assert revision == "b" * 40
            return [SimpleNamespace(size=downloaded.stat().st_size)]

    monkeypatch.setattr(main, "HfApi", FakeHub)
    monkeypatch.setattr(
        main, "hf_hub_download", lambda *args, **kwargs: str(downloaded)
    )
    response = client.post(
        "/api/v1/integrations/opengenome2/import",
        json={
            "path": "fasta/bacteria/shard.fasta.gz",
            "revision": "main",
            "sample_size": 2,
            "sample_seed": 7,
        },
    )
    assert response.status_code == 201, response.text
    dataset = response.json()
    assert dataset["data_source"] == "arcinstitute/opengenome2"
    assert dataset["source_revision"] == "b" * 40
    assert dataset["filename"] == "shard.fasta.gz"
    assert dataset["sampling"] == {
        "sampled": True,
        "sample_size": 2,
        "source_record_count": 3,
        "method": "reservoir",
        "seed": 7,
        "source_file_size_bytes": downloaded.stat().st_size,
        "source_path": "fasta/bacteria/shard.fasta.gz",
        "source_oid": None,
    }
    with main.Session() as db:
        stored_path = db.get(main.Dataset, dataset["id"]).path
    assert Path(stored_path).read_text(encoding="utf-8") == ">seq1\nACGT\n>seq3\nTTAA\n"
    assert client.delete(f"/api/v1/datasets/{dataset['id']}").status_code == 204


def test_opengenome2_metadata_preview_uses_real_columns_and_revision(
    monkeypatch, tmp_path
):
    from gqi_api import main

    metadata = tmp_path / "species_metadata.csv"
    metadata.write_text(
        "accession,taxid,species\nGCF_1,2,Example species\n", encoding="utf-8"
    )

    class FakeHub:
        def __init__(self, token=None):
            pass

        def repo_info(self, repo_id, repo_type, revision):
            return SimpleNamespace(sha="c" * 40)

        def get_paths_info(self, repo_id, paths, revision, repo_type, token):
            assert paths == ["species_metadata.csv"]
            assert revision == "c" * 40
            return [SimpleNamespace(size=metadata.stat().st_size)]

    monkeypatch.setattr(main, "HfApi", FakeHub)
    monkeypatch.setattr(main, "hf_hub_download", lambda *args, **kwargs: str(metadata))
    response = client.get(
        "/api/v1/integrations/opengenome2/metadata?revision=main&limit=1"
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == "c" * 40
    assert response.json()["columns"] == ["accession", "taxid", "species"]
    assert response.json()["rows"] == [
        {"accession": "GCF_1", "taxid": "2", "species": "Example species"}
    ]


def test_dataset_comparison_returns_metric_deltas_and_type_warning():
    from gqi_api import main

    ids = []
    for name, dataset_type, sequences, total_bases, gc in [
        ("compare-a", "sequence_collection", 10, 1000, 50.0),
        ("compare-b", "genome_assembly", 5, 1200, 55.0),
    ]:
        uploaded = client.post(
            "/api/v1/datasets",
            files={"file": (f"{name}.fa", b">x\nACGT\n")},
            data={"name": name, "dataset_type": dataset_type},
        )
        identifier = uploaded.json()["id"]
        ids.append(identifier)
        analysis = {
            "sequence_count": sequences,
            "total_bases": total_bases,
            "gc_percent": gc,
            "ambiguous_percent": 0.0,
            "duplicate_rate_percent": 0.0,
            "length": {"mean": 100.0, "median": 90.0},
            "n50": 80,
        }
        with main.Session() as db:
            dataset = db.get(main.Dataset, identifier)
            dataset.status = "complete"
            dataset.analysis_json = json.dumps(analysis)
            db.commit()

    response = client.post("/api/v1/comparisons", json={"dataset_ids": ids})
    assert response.status_code == 200
    payload = response.json()
    assert payload["comparisons"][0]["deltas"]["sequence_count"] == -5
    assert payload["comparisons"][0]["deltas"]["total_bases"] == 200
    assert payload["comparisons"][0]["deltas"]["gc_percent"] == 5.0
    assert payload["warnings"]
    assert (
        client.post(
            "/api/v1/comparisons", json={"dataset_ids": [ids[0], ids[0]]}
        ).status_code
        == 422
    )
    for identifier in ids:
        assert client.delete(f"/api/v1/datasets/{identifier}").status_code == 204


def test_metadata_taxonomy_and_bounded_sequence_window():
    from gqi_api import main

    uploaded = client.post(
        "/api/v1/datasets",
        files={"file": ("mapped.fa", b">seqA description\nAACCGGTT\n>seqB\nTTTTAAAA\n")},
    )
    assert uploaded.status_code == 201
    dataset_id = uploaded.json()["id"]
    with main.Session() as db:
        dataset = db.get(main.Dataset, dataset_id)
        dataset.status = "complete"
        dataset.analysis_json = json.dumps({
            "sequence_count": 2,
            "total_bases": 16,
            "records": [
                {"id": "seqA description", "length": 8},
                {"id": "seqB", "length": 8},
            ],
        })
        db.commit()
    metadata = client.post(
        f"/api/v1/datasets/{dataset_id}/metadata",
        files={"file": ("taxonomy.csv", b"accession,species,taxid,rank\nseqA,Example species,42,species\n", "text/csv")},
    )
    assert metadata.status_code == 201, metadata.text
    summary = client.get(f"/api/v1/datasets/{dataset_id}/taxonomy").json()
    assert summary["mapped_sequence_count"] == 1
    assert summary["unmapped_sequence_count"] == 1
    assert summary["items"][0]["nucleotide_count"] == 8
    window = client.get(
        f"/api/v1/datasets/{dataset_id}/sequence-window",
        params={"record_id": "seqA", "start": 1, "end": 5},
    )
    assert window.status_code == 200, window.text
    assert window.json()["sequence"] == "ACCG"
    assert window.json()["tracks"]["gc_percent_100bp"][0]["start"] == 1
    assert client.delete(f"/api/v1/datasets/{dataset_id}").status_code == 204


def test_ncbi_search_uses_bounded_metadata_only_cli(monkeypatch):
    from gqi_api import main

    calls = []
    monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/datasets" if name == "datasets" else None)
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0, stdout='{"accession":"GCF_000005845.2"}\n', stderr=""),
    )
    response = client.get("/api/v1/integrations/ncbi/search?q=GCF_000005845.2&kind=accession&limit=1")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["sequence_data_downloaded"] is False
    assert payload["items"][0]["accession"] == "GCF_000005845.2"
    assert calls[0][0][-3:] == ["--limit", "1", "--as-json-lines"]


def test_gtdb_release_discovery_parses_official_release_index(monkeypatch):
    from gqi_api import main

    class FakeResponse:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "https://data.gtdb.ecogenomic.org/releases/"

        def read(self, _limit):
            return b'<a href="r220/">r220</a><a href="r95/">r95</a>'

    monkeypatch.setattr(main, "urlopen", lambda *args, **kwargs: FakeResponse())
    response = client.get("/api/v1/integrations/gtdb/releases?limit=2")
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["releases"]] == ["r220", "r95"]


def test_demo_seed_registers_real_fixtures_and_is_idempotent(monkeypatch):
    from gqi_api import main

    started = []
    monkeypatch.setattr(
        main,
        "start_analysis",
        lambda dataset_id, run_id, k: started.append((dataset_id, run_id, k)),
    )
    first = client.post("/api/v1/demo/seed")
    assert first.status_code == 201
    items = first.json()["items"]
    assert len(items) == 3
    assert {item["dataset_type"] for item in items} == {
        "sequence_collection",
        "raw_reads",
        "genome_assembly",
    }
    assert all(item["data_source"] == "built_in_demo" for item in items)
    assert all(item["status"] == "queued" for item in items)
    assert len(started) == 3
    again = client.post("/api/v1/demo/seed")
    assert {item["id"] for item in again.json()["items"]} == {
        item["id"] for item in items
    }
    assert len(started) == 3
    with main.Session() as db:
        stale = db.get(main.Dataset, items[0]["id"])
        stale.status = "complete"
        stale.analysis_json = json.dumps({"length": {}})
        db.commit()
    refreshed = client.post("/api/v1/demo/seed")
    assert refreshed.status_code == 201
    assert len(started) == 4
    for item in items:
        assert client.delete(f"/api/v1/datasets/{item['id']}").status_code == 204
