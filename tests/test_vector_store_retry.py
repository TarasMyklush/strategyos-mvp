from __future__ import annotations

import io
from types import SimpleNamespace
from urllib import error

import pytest

from strategyos_mvp import vector_store


class _Response:
    def __init__(self, body: bytes = b'{"result":{"status":"ok"}}') -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


def _configure(monkeypatch) -> list[float]:
    delays: list[float] = []
    monkeypatch.setattr(
        vector_store,
        "CONFIG",
        SimpleNamespace(qdrant_url="http://qdrant:6333"),
    )
    monkeypatch.setattr(vector_store.random, "uniform", lambda _start, _end: 0.0)
    monkeypatch.setattr(vector_store.time, "sleep", delays.append)
    return delays


def test_qdrant_request_retries_transient_transport_then_succeeds(monkeypatch):
    delays = _configure(monkeypatch)
    outcomes = iter([error.URLError("connection reset"), _Response()])
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req, timeout))
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(vector_store.request, "urlopen", fake_urlopen)

    result = vector_store._qdrant_request(
        "PUT", "/collections/example/points?wait=true", {"points": []}
    )

    assert result == {"result": {"status": "ok"}}
    assert len(calls) == 2
    assert calls[0][0] is not calls[1][0]
    assert delays == [0.25]


def test_qdrant_request_exhausts_transient_failures(monkeypatch):
    delays = _configure(monkeypatch)
    calls = []

    def unavailable(_req, timeout):
        del timeout
        calls.append(True)
        raise error.URLError("service restarting")

    monkeypatch.setattr(vector_store.request, "urlopen", unavailable)

    with pytest.raises(RuntimeError, match="after 4 attempts:.*service restarting"):
        vector_store._qdrant_request("POST", "/collections/example/points/scroll", {})

    assert len(calls) == 4
    assert delays == [0.25, 0.5, 1.0]


def test_qdrant_request_retries_only_retryable_http_statuses(monkeypatch):
    delays = _configure(monkeypatch)
    calls = []

    def invalid_request(req, timeout):
        del timeout
        calls.append(req)
        raise error.HTTPError(
            req.full_url, 400, "Bad Request", {}, io.BytesIO(b"invalid filter")
        )

    monkeypatch.setattr(vector_store.request, "urlopen", invalid_request)

    with pytest.raises(RuntimeError, match=r"failed \(400\).*invalid filter"):
        vector_store._qdrant_request("POST", "/collections/example/points/scroll", {})

    assert len(calls) == 1
    assert delays == []


def test_qdrant_request_retries_retryable_http_status(monkeypatch):
    delays = _configure(monkeypatch)
    outcomes = iter([503, 502, 200])

    def recovering(req, timeout):
        del timeout
        status = next(outcomes)
        if status != 200:
            raise error.HTTPError(
                req.full_url,
                status,
                "Unavailable",
                {},
                io.BytesIO(b"restarting"),
            )
        return _Response()

    monkeypatch.setattr(vector_store.request, "urlopen", recovering)

    assert vector_store._qdrant_request("GET", "/collections") == {
        "result": {"status": "ok"}
    }
    assert delays == [0.25, 0.5]
