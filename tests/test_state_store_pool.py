"""Tests for the Postgres connection pool in state_store.database_connection().

database_connection() used to call psycopg.connect(CONFIG.database_url) on
every invocation -- no reuse, full connect/auth/teardown per call across 23+
call sites. It now checks connections out of a process-wide psycopg_pool
ConnectionPool via pool.getconn(), wrapped in _PooledConnectionHandle so the
existing `connection, skipped = database_connection()` / `with connection as
conn:` contract at every call site is preserved unchanged -- verified
empirically that plain psycopg3 Connection.__exit__ does NOT call
pool.putconn() for a pool-owned connection (it only skips close()), so
without the wrapper a bare getconn() + `with conn:` loop depletes the pool
after max_size calls.

Two kinds of coverage:
- Pure-unit tests (this file, no real Postgres needed, run on CI): assert
  database_connection() goes through the pool (not a bare psycopg.connect)
  and that the pool is memoized as a process-wide singleton.
- A real-Postgres integration test (@pytest.mark.integration, skips without
  STRATEGYOS_POSTGRES_E2E_DATABASE_URL, same guard as
  test_governed_review_flow_postgres_e2e.py): proves connections are
  actually reused/returned across more calls than max_size, and that the
  existing with-block contract still commits/rolls back correctly.
"""

from __future__ import annotations

import os

import pytest

import strategyos_mvp.state_store as state_store
from strategyos_mvp.config import load_config


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    state_store.CONFIG = config
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    state_store.CONFIG = load_config()


@pytest.fixture(autouse=True)
def _reset_pool_singleton():
    """Ensure each test starts with a clean pool singleton and does not leak
    a pool (or its background threads) into other tests."""
    original_pool = state_store._PG_POOL
    original_url = state_store._PG_POOL_DATABASE_URL
    state_store._PG_POOL = None
    state_store._PG_POOL_DATABASE_URL = None
    try:
        yield
    finally:
        if state_store._PG_POOL is not None and state_store._PG_POOL is not original_pool:
            try:
                state_store._PG_POOL.close()
            except Exception:
                pass
        state_store._PG_POOL = original_pool
        state_store._PG_POOL_DATABASE_URL = original_url


class _FakeConnection:
    """Stand-in for a psycopg.Connection returned by pool.getconn()."""

    def __init__(self):
        self.entered = False
        self.exited = False
        self.exit_exc = None

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exited = True
        self.exit_exc = exc_type
        return False


class _FakePool:
    """Stand-in for psycopg_pool.ConnectionPool that records getconn/putconn
    calls so tests can assert database_connection() uses pool semantics
    (checkout + return) rather than a bare connect-per-call."""

    def __init__(self, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs
        self.getconn_calls = 0
        self.putconn_calls = 0
        self.connections: list[_FakeConnection] = []
        self.closed = False

    def getconn(self, timeout=None):
        self.getconn_calls += 1
        conn = _FakeConnection()
        self.connections.append(conn)
        return conn

    def putconn(self, conn):
        self.putconn_calls += 1

    def close(self):
        self.closed = True


def test_database_connection_uses_the_pool_not_a_bare_connect(monkeypatch, tmp_path):
    original = _apply_env(
        {"DATABASE_URL": "postgresql://fake:fake@localhost:5/fake_db_never_contacted"}
    )
    try:
        fake_pool_instances: list[_FakePool] = []

        def _fake_connection_pool(*args, **kwargs):
            pool = _FakePool(*args, **kwargs)
            fake_pool_instances.append(pool)
            return pool

        import psycopg_pool

        monkeypatch.setattr(psycopg_pool, "ConnectionPool", _fake_connection_pool)

        connection, skipped = state_store.database_connection()
        assert skipped is None
        assert len(fake_pool_instances) == 1
        assert fake_pool_instances[0].getconn_calls == 1

        with connection as conn:
            assert conn.entered is True
        assert fake_pool_instances[0].putconn_calls == 1, (
            "database_connection()'s with-block contract must call "
            "pool.putconn() on exit -- a bare psycopg Connection.__exit__ "
            "does not do this for pool-owned connections and would "
            "silently deplete the pool."
        )
    finally:
        _restore_env(original)


def test_pool_is_memoized_as_a_process_wide_singleton(monkeypatch):
    original = _apply_env(
        {"DATABASE_URL": "postgresql://fake:fake@localhost:5/fake_db_never_contacted"}
    )
    try:
        fake_pool_instances: list[_FakePool] = []

        def _fake_connection_pool(*args, **kwargs):
            pool = _FakePool(*args, **kwargs)
            fake_pool_instances.append(pool)
            return pool

        import psycopg_pool

        monkeypatch.setattr(psycopg_pool, "ConnectionPool", _fake_connection_pool)

        for _ in range(5):
            connection, skipped = state_store.database_connection()
            assert skipped is None
            with connection:
                pass

        assert len(fake_pool_instances) == 1, (
            "ConnectionPool() should be constructed exactly once and reused "
            "across calls -- constructing a new pool per call would defeat "
            "the entire point of pooling."
        )
        assert fake_pool_instances[0].getconn_calls == 5
        assert fake_pool_instances[0].putconn_calls == 5
    finally:
        _restore_env(original)


def test_pool_reopens_when_database_url_changes(monkeypatch):
    """Memoization is keyed on CONFIG.database_url so a config reload
    pointed at a different database (as tests that swap CONFIG do) opens a
    fresh pool instead of silently reusing one connected to a stale URL."""
    fake_pool_instances: list[_FakePool] = []

    def _fake_connection_pool(*args, **kwargs):
        pool = _FakePool(*args, **kwargs)
        fake_pool_instances.append(pool)
        return pool

    import psycopg_pool

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", _fake_connection_pool)

    original = _apply_env({"DATABASE_URL": "postgresql://fake/db_one"})
    try:
        connection, skipped = state_store.database_connection()
        assert skipped is None
        with connection:
            pass
        assert len(fake_pool_instances) == 1

        _apply_env({"DATABASE_URL": "postgresql://fake/db_two"})
        connection, skipped = state_store.database_connection()
        assert skipped is None
        with connection:
            pass
        assert len(fake_pool_instances) == 2, "changing DATABASE_URL must open a new pool"
        assert fake_pool_instances[1].init_args[0] == "postgresql://fake/db_two"
    finally:
        _restore_env(original)


def test_database_connection_skips_cleanly_without_database_url():
    original = _apply_env({"DATABASE_URL": None, "STRATEGYOS_DATABASE_URL": None})
    try:
        connection, skipped = state_store.database_connection()
        assert connection is None
        assert skipped == {"status": "skipped", "reason": "DATABASE_URL is not configured."}
    finally:
        _restore_env(original)


@pytest.mark.integration
def test_pool_reuses_connections_across_more_calls_than_max_size():
    """Proves the real fix against a real Postgres: a bare pool.getconn() +
    `with conn:` loop (the naive approach) raises PoolTimeout on the
    (max_size + 1)-th call, because psycopg3's Connection.__exit__ never
    calls putconn() for a pool-owned connection. database_connection()'s
    _PooledConnectionHandle must not have this problem."""
    database_url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the connection-pool proof."
        )

    original = _apply_env(
        {
            "DATABASE_URL": database_url,
            "STRATEGYOS_PG_POOL_MAX_SIZE": "2",
            "STRATEGYOS_PG_POOL_MIN_SIZE": "1",
            "STRATEGYOS_PG_POOL_TIMEOUT_SECONDS": "5",
        }
    )
    try:
        # More iterations than max_size -- would PoolTimeout without proper
        # putconn()/return-to-pool behavior.
        for i in range(6):
            connection, skipped = state_store.database_connection()
            assert skipped is None, skipped
            with connection as conn:
                with conn.cursor() as cur:
                    cur.execute("select 1")
                    assert cur.fetchone() == (1,)

        pool = state_store._get_pool()
        stats = pool.get_stats()
        assert stats["connections_num"] <= 2, (
            f"expected at most 2 physical connections opened (max_size=2), got "
            f"{stats['connections_num']} -- connections are not being reused"
        )
        assert stats["pool_available"] >= 1, "connections were not returned to the pool"
    finally:
        _restore_env(original)
