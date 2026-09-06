from __future__ import annotations

import argparse
import os
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .claim_store import ClaimRepository
from . import semantic_embeddings


ProjectionHandler = Callable[[Mapping[str, Any], str], None]


@dataclass(frozen=True)
class ProjectionRunResult:
    leased: int
    published: int
    failed: int
    dead_lettered: int


class ClaimProjectionWorker:
    """Deliver the transactional outbox to projection-only stores.

    A lease is committed before any external I/O.  Completion and retry state
    are then recorded with the worker identity, preventing one worker from
    acknowledging another worker's delivery.  Projectors receive a hydrated
    immutable claim; they never select revisions themselves.
    """

    def __init__(
        self,
        repository: ClaimRepository | None = None,
        *,
        worker_id: str | None = None,
        handlers: Mapping[str, ProjectionHandler] | None = None,
        max_attempts: int = 10,
    ) -> None:
        self.repository = repository or ClaimRepository()
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.handlers = dict(handlers or self._default_handlers())
        self.max_attempts = max(1, int(max_attempts))

    def run_once(self, *, limit: int = 50) -> ProjectionRunResult:
        events = self.repository.lease_projection_batch(
            worker_id=self.worker_id,
            limit=limit,
        )
        published = 0
        failed = 0
        dead_lettered = 0
        for event in events:
            try:
                self._deliver(event)
                self.repository.mark_projection_published(
                    event["id"], worker_id=self.worker_id
                )
                published += 1
            except Exception as exc:  # delivery failures are durable retry state
                failed += 1
                attempts = int(event.get("publish_attempts") or 1)
                result = self.repository.mark_projection_failed(
                    event["id"],
                    worker_id=self.worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_delay_seconds=min(3600, 2 ** min(attempts, 11)),
                    max_attempts=self.max_attempts,
                )
                dead_lettered += int(bool(result.get("dead_lettered")))
        return ProjectionRunResult(
            leased=len(events),
            published=published,
            failed=failed,
            dead_lettered=dead_lettered,
        )

    def _deliver(self, event: Mapping[str, Any]) -> None:
        projection_type = str(event.get("projection_type") or "")
        operation = str(event.get("operation") or "")
        handler = self.handlers.get(projection_type)
        if handler is None:
            raise ValueError(f"Unsupported projection type: {projection_type!r}")
        revision_id = str(event.get("claim_revision_id") or "")
        tenant_id = str(event.get("tenant_id") or "")
        if not revision_id or not tenant_id:
            raise ValueError("Projection event is missing its tenant or claim revision.")
        if operation == "upsert":
            record = self.repository.projection_record(
                revision_id, tenant_id=tenant_id
            )
        elif operation in {"delete", "revoke"}:
            record = {
                "tenant_id": tenant_id,
                "claim_revision_id": revision_id,
                "event_payload": dict(event.get("payload") or {}),
            }
        else:
            raise ValueError(f"Unsupported projection operation: {operation!r}")
        handler(record, operation)

    def _default_handlers(self) -> Mapping[str, ProjectionHandler]:
        from .neo4j_store import project_claim_record as project_graph_claim
        from .vector_store import project_claim_record as project_vector_claim

        if not semantic_embeddings.configured():
            raise RuntimeError(
                "The governed-claims projector requires "
                "STRATEGYOS_EMBEDDING_MODEL_PATH to reference the pinned local model."
            )
        # Validate the pinned identity and every file hash before this worker can
        # lease a transactional outbox row. Runtime downloads are prohibited.
        semantic_embeddings.model()

        def project_cache(record: Mapping[str, Any], operation: str) -> None:
            if operation == "upsert":
                self.repository.upsert_projection_cache(record)
            else:
                self.repository.delete_projection_cache(
                    str(record["claim_revision_id"]),
                    tenant_id=str(record["tenant_id"]),
                )

        return {
            "graph": project_graph_claim,
            "vector": project_vector_claim,
            "cache": project_cache,
        }


def _continuous_wait_seconds(
    result: ProjectionRunResult, *, limit: int, poll_seconds: float
) -> float:
    """Drain a healthy backlog continuously; back off only when caught up or failing."""
    if result.leased >= max(1, int(limit)) and result.failed == 0:
        return 0.0
    return max(0.25, min(float(poll_seconds), 60.0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deliver governed claim projections.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args(argv)
    if args.health:
        repository = ClaimRepository()
        health = repository.projection_health()
        if not semantic_embeddings.configured():
            health = {
                **health,
                "status": "failed",
                "configuration": "pinned_embedding_model_missing",
            }
        print(
            " ".join(f"{key}={value}" for key, value in health.items()),
            flush=True,
        )
        return 0 if health.get("status") == "ready" else 1
    worker = ClaimProjectionWorker()
    while True:
        result = worker.run_once(limit=args.limit)
        if result.leased or not args.continuous:
            print(
                f"leased={result.leased} published={result.published} "
                f"failed={result.failed} dead_lettered={result.dead_lettered}",
                flush=True,
            )
        if not args.continuous:
            return 0 if result.failed == 0 else 1
        wait_seconds = _continuous_wait_seconds(
            result,
            limit=args.limit,
            poll_seconds=args.poll_seconds,
        )
        if wait_seconds:
            time.sleep(wait_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
