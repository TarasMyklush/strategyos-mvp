"""Concurrency/lock-discipline tests for twins/store.py's JSON repositories.

_JsonRepository has real fcntl.flock + atomic temp-file-replace via
_mutate_file, but two mutators bypassed it with an unlocked
load-then-save read-modify-write: KpiRepository.update (exercised by
kpi_ingest.refresh_kpis_from_run) and InvestigationRepository.save. Under
concurrent writers this is a lost-update race -- two threads both read
the same on-disk state, both mutate their own copy, and whichever writes
last silently discards the other's write.

These tests spawn concurrent threads writing distinct keys/records to a
single shared repository and assert every write survives. They pass
trivially in serial execution (the lock discipline being tested doesn't
change the answer when there's no real contention) -- the point is to
regression-lock the routing through _mutate_file, and a version of these
tests run against the pre-fix code (bypassing _mutate_file) reliably
drops writes under this thread count/repetition.
"""

from __future__ import annotations

import threading

from strategyos_mvp.twins.store import InvestigationRepository, KpiRepository

THREAD_COUNT = 8
ITERATIONS_PER_THREAD = 20


def test_kpi_repository_update_is_lock_atomic(tmp_path):
    repo = KpiRepository(tmp_path)
    barrier = threading.Barrier(THREAD_COUNT)
    errors: list[BaseException] = []

    def _writer(thread_index: int) -> None:
        try:
            barrier.wait()
            for iteration in range(ITERATIONS_PER_THREAD):
                repo.update(
                    f"node_{thread_index}",
                    {"value": iteration, "thread": thread_index},
                )
        except BaseException as exc:  # noqa: BLE001 - surface any thread error to the test
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(THREAD_COUNT)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, f"writer thread(s) raised: {errors}"

    tree = repo.load()
    assert len(tree) == THREAD_COUNT, (
        f"expected {THREAD_COUNT} distinct kpi nodes (one per thread), got "
        f"{len(tree)} -- some concurrent writes were lost"
    )
    for thread_index in range(THREAD_COUNT):
        node = tree.get(f"node_{thread_index}")
        assert node is not None, f"node_{thread_index} is missing entirely -- write was lost"
        assert node["value"] == ITERATIONS_PER_THREAD - 1, (
            f"node_{thread_index} has value {node['value']!r}, expected the last "
            f"iteration's value {ITERATIONS_PER_THREAD - 1} -- a later write was "
            "lost to an earlier one (lost-update race)"
        )
        assert node["thread"] == thread_index


def test_investigation_repository_save_is_lock_atomic(tmp_path):
    repo = InvestigationRepository(tmp_path)
    barrier = threading.Barrier(THREAD_COUNT)
    errors: list[BaseException] = []

    def _writer(thread_index: int) -> None:
        try:
            barrier.wait()
            for iteration in range(ITERATIONS_PER_THREAD):
                repo.save(
                    "ceo",
                    {
                        "id": f"investigation_{thread_index}",
                        "iteration": iteration,
                        "thread": thread_index,
                    },
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(THREAD_COUNT)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, f"writer thread(s) raised: {errors}"

    records = repo.load("ceo")
    assert len(records) == THREAD_COUNT, (
        f"expected {THREAD_COUNT} distinct investigation records (one per "
        f"thread, deduped by id), got {len(records)} -- concurrent saves "
        "either lost records or created duplicates"
    )
    by_id = {record["id"]: record for record in records}
    for thread_index in range(THREAD_COUNT):
        record = by_id.get(f"investigation_{thread_index}")
        assert record is not None, f"investigation_{thread_index} is missing -- write was lost"
        assert record["iteration"] == ITERATIONS_PER_THREAD - 1, (
            f"investigation_{thread_index} has iteration {record['iteration']!r}, "
            f"expected the last write's value {ITERATIONS_PER_THREAD - 1} -- a "
            "later write was lost to an earlier one"
        )
