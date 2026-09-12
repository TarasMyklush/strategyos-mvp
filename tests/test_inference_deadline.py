import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from types import SimpleNamespace
import threading
from urllib.error import URLError

import pytest
from strategyos_mvp import inference_deadline as budget, llm_qa


def test_retry_attempts_share_elapsed_allowance(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(budget.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(budget.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    timeouts = []
    def unavailable(request, *, timeout):
        timeouts.append(timeout)
        clock[0] += min(.7, timeout)
        raise URLError(TimeoutError('fixture'))
    monkeypatch.setattr(llm_qa, 'urlopen', unavailable)
    with budget.bound(1):
        with pytest.raises(budget.InferenceDeadlineExceeded):
            llm_qa._post_with_retry(request=object(), timeout_seconds=60, provider_label='fixture',
                max_attempts=5, backoff_seconds=.2, max_backoff_seconds=.2)
    assert timeouts == pytest.approx([1, .1])
    assert budget.deadline.get() is None


def test_expired_request_never_reserves_or_calls_provider(monkeypatch):
    from strategyos_mvp import inference_audit
    monkeypatch.setattr(inference_audit, 'record', lambda *a, **k: pytest.fail('Expired request reserved inference'))
    with budget.bound(-1):
        with pytest.raises(budget.InferenceDeadlineExceeded):
            llm_qa._call_openai_compatible_chat(config=SimpleNamespace(llm_timeout_seconds=60), messages=[])


def test_cancelled_caller_retains_slot_until_blocking_work_finishes(monkeypatch):
    from strategyos_mvp import api
    marker = ContextVar('test_request_marker', default=None)
    entered, finish = threading.Event(), threading.Event()
    observed = []
    executor = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr(api, '_LLM_PROVIDER_EXECUTOR', executor)
    async def run():
        monkeypatch.setattr(api, '_LLM_PROVIDER_SEMAPHORE', asyncio.Semaphore(1))
        marker.set('authorized-scope')
        def first():
            observed.append(marker.get())
            entered.set()
            assert finish.wait(2)
        task = asyncio.create_task(api._run_bounded_provider(first))
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        second = asyncio.create_task(api._run_bounded_provider(lambda: observed.append('second')))
        await asyncio.sleep(.02)
        assert observed == ['authorized-scope']
        finish.set()
        await asyncio.wait_for(second, 1)
        assert observed == ['authorized-scope', 'second']
    try:
        asyncio.run(run())
    finally:
        finish.set()
        executor.shutdown(wait=True)


def test_assistant_deadline_covers_multiple_stages_and_returns_service_status(monkeypatch):
    from strategyos_mvp import api
    from fastapi import HTTPException
    monkeypatch.setattr(api, 'CONFIG', SimpleNamespace(llm_timeout_seconds=.03))
    async def stages(request, **kwargs):
        await asyncio.sleep(.02)
        await asyncio.sleep(.02)
        pytest.fail('Overall deadline was reset between stages')
    monkeypatch.setattr(api, '_assistant_chat_response', stages)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api._assistant_chat_response_with_deadline(object()))
    assert error.value.status_code == 504
    assert 'response time limit' in error.value.detail
    assert budget.deadline.get() is None
