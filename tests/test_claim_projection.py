from __future__ import annotations

from strategyos_mvp.claim_projection import (
    ClaimProjectionWorker,
    ProjectionRunResult,
    _continuous_wait_seconds,
)


class FakeRepository:
    def __init__(self, events):
        self.events = list(events)
        self.published = []
        self.failed = []
        self.hydrated = []

    def lease_projection_batch(self, *, worker_id, limit):
        self.lease = {"worker_id": worker_id, "limit": limit}
        return list(self.events)

    def projection_record(self, revision_id, *, tenant_id):
        self.hydrated.append((revision_id, tenant_id))
        return {
            "claim_revision_id": revision_id,
            "tenant_id": tenant_id,
            "metric_key": "ceo.revenue",
        }

    def mark_projection_published(self, event_id, *, worker_id):
        self.published.append((event_id, worker_id))

    def mark_projection_failed(self, event_id, **kwargs):
        self.failed.append((event_id, kwargs))
        return {"attempts": 1, "dead_lettered": kwargs["max_attempts"] == 1}


def _event(event_id="event-1", *, projection="graph", operation="upsert", attempts=1):
    return {
        "id": event_id,
        "tenant_id": "tenant-1",
        "claim_revision_id": "revision-1",
        "projection_type": projection,
        "operation": operation,
        "payload": {},
        "publish_attempts": attempts,
    }


def test_worker_hydrates_and_acknowledges_successful_projection():
    repository = FakeRepository([_event()])
    delivered = []
    worker = ClaimProjectionWorker(
        repository,
        worker_id="worker-1",
        handlers={"graph": lambda record, operation: delivered.append((record, operation))},
    )

    assert worker.run_once(limit=7) == ProjectionRunResult(1, 1, 0, 0)
    assert repository.lease == {"worker_id": "worker-1", "limit": 7}
    assert repository.hydrated == [("revision-1", "tenant-1")]
    assert delivered[0][0]["metric_key"] == "ceo.revenue"
    assert repository.published == [("event-1", "worker-1")]


def test_worker_records_bounded_retry_and_dead_letter_state():
    repository = FakeRepository([_event(attempts=4)])

    def fail(_record, _operation):
        raise RuntimeError("projection service unavailable")

    worker = ClaimProjectionWorker(
        repository,
        worker_id="worker-2",
        handlers={"graph": fail},
        max_attempts=1,
    )

    assert worker.run_once() == ProjectionRunResult(1, 0, 1, 1)
    event_id, failure = repository.failed[0]
    assert event_id == "event-1"
    assert failure["worker_id"] == "worker-2"
    assert failure["retry_delay_seconds"] == 16
    assert "projection service unavailable" in failure["error"]


def test_index_revocation_turns_stale_upsert_into_content_free_delete():
    repository = FakeRepository([_event()])
    repository.projection_record = lambda revision_id, tenant_id: {
        "tenant_id": tenant_id, "claim_revision_id": revision_id, "indexing_allowed": False,
    }
    delivered = []
    worker = ClaimProjectionWorker(repository, worker_id="rights-proof",
        handlers={"graph": lambda record, operation: delivered.append((record, operation))})
    assert worker.run_once() == ProjectionRunResult(1, 1, 0, 0)
    assert delivered[0][1] == "delete"
    assert set(delivered[0][0]) <= {"tenant_id", "claim_revision_id", "indexing_allowed"}


def test_default_projectors_fail_closed_without_pinned_embedding(monkeypatch):
    from strategyos_mvp import semantic_embeddings

    monkeypatch.setattr(semantic_embeddings, "configured", lambda: False)

    try:
        ClaimProjectionWorker(FakeRepository([]), worker_id="worker-missing-model")
    except RuntimeError as exc:
        assert "STRATEGYOS_EMBEDDING_MODEL_PATH" in str(exc)
    else:  # pragma: no cover - explicit failure without a pytest runtime dependency
        raise AssertionError("The projector accepted an unconfigured embedding model.")


def test_continuous_worker_drains_full_healthy_batches_without_idle_wait():
    assert (
        _continuous_wait_seconds(
            ProjectionRunResult(100, 100, 0, 0), limit=100, poll_seconds=5
        )
        == 0
    )
    assert (
        _continuous_wait_seconds(
            ProjectionRunResult(25, 25, 0, 0), limit=100, poll_seconds=5
        )
        == 5
    )
    assert (
        _continuous_wait_seconds(
            ProjectionRunResult(100, 99, 1, 0), limit=100, poll_seconds=5
        )
        == 5
    )


def test_delete_projection_does_not_rehydrate_deleted_claim():
    repository = FakeRepository([_event(operation="revoke")])
    delivered = []
    worker = ClaimProjectionWorker(
        repository,
        worker_id="worker-3",
        handlers={"graph": lambda record, operation: delivered.append((record, operation))},
    )

    worker.run_once()

    assert repository.hydrated == []
    assert delivered == [
        (
            {
                "tenant_id": "tenant-1",
                "claim_revision_id": "revision-1",
                "event_payload": {},
            },
            "revoke",
        )
    ]


def test_neo4j_projection_carries_source_and_calculation_lineage(monkeypatch):
    from strategyos_mvp import neo4j_store

    calls = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def run(self, statement, **params):
            calls.append((" ".join(statement.split()), params))

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def session(self):
            return Session()

    monkeypatch.setattr(neo4j_store, "_graph_driver", lambda: Driver())
    neo4j_store.project_claim_record(
        {
            "tenant_id": "tenant-1",
            "claim_revision_id": "revision-1",
            "family_key": "family-1",
            "revision": 1,
            "label": "Actual",
            "metric_key": "ceo.ebitda_margin",
            "claim_kind": "actual",
            "production_method": "calculated",
            "value": "20",
            "unit": "percent",
            "subject": {"type": "enterprise", "key": "group"},
            "period": {"start": "2026-01-01", "end": "2026-06-30"},
            "sources": [
                {
                    "source_key": "erp",
                    "origin_category": "internal_system",
                    "occurrence_key": "occurrence-1",
                }
            ],
            "formula": {"inputs": ["input-1", "input-2"]},
        },
        "upsert",
    )

    cypher = "\n".join(statement for statement, _params in calls)
    assert "ASSERTS_ABOUT" in cypher
    assert "SUPPORTED_BY" in cypher
    assert cypher.count("CALCULATED_FROM") == 2
    claim_upsert = next(params for statement, params in calls if "ASSERTS_ABOUT" in statement)
    assert claim_upsert["properties"]["projection_only"] is True


def test_qdrant_projection_is_policy_tagged_and_uses_pinned_embedding(monkeypatch):
    from types import SimpleNamespace

    from strategyos_mvp import vector_store

    requests = []
    monkeypatch.setattr(vector_store, "CONFIG", SimpleNamespace(qdrant_url="http://qdrant"))
    monkeypatch.setattr(vector_store.semantic_embeddings, "configured", lambda: True)
    monkeypatch.setattr(vector_store.semantic_embeddings, "embed", lambda _text: [0.1, 0.2])
    monkeypatch.setattr(
        vector_store,
        "_ensure_claim_projection_collection",
        lambda: requests.append(("ensure", vector_store.CLAIM_PROJECTION_COLLECTION, None)),
    )
    monkeypatch.setattr(
        vector_store,
        "_qdrant_request",
        lambda method, path, payload=None: requests.append((method, path, payload)) or {},
    )

    vector_store.project_claim_record(
        {
            "tenant_id": "tenant-1",
            "claim_revision_id": "revision-1",
            "family_key": "family-1",
            "label": "Actual",
            "metric_key": "ceo.revenue",
            "claim_kind": "actual",
            "value": "100",
            "unit": "SAR",
            "subject": {"type": "enterprise", "key": "group"},
            "period": {"start": "2026-01-01", "end": "2026-06-30"},
            "sources": [{"source_key": "erp", "origin_category": "internal_system"}],
        },
        "upsert",
    )

    upsert = next(
        payload
        for method, _path, payload in requests
        if method == "PUT" and payload and "points" in payload
    )
    point = upsert["points"][0]
    assert point["payload"]["projection_only"] is True
    assert point["payload"]["authorization_required"] is True
    assert point["payload"]["origin_categories"] == ["internal_system"]
