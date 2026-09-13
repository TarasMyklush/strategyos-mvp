import asyncio

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from strategyos_mvp import codex_gateway as gateway


TOKEN = "gateway-test-token-" + "x" * 32


def payload(**changes):
    return {"model": "codex-subscription", "messages": [{"role": "user", "content": "Explain the evidence"}], **changes}


def client(runner=None):
    async def answer(settings, messages, json_mode):
        return '{"answer":"Grounded answer"}' if json_mode else "Grounded answer"
    return TestClient(gateway.create_app(gateway.Settings(TOKEN), runner or answer))


def test_private_auth_and_compatible_contract():
    c = client()
    assert c.post("/v1/chat/completions", json=payload()).status_code == 401
    result = c.post("/v1/chat/completions", json=payload(), headers={"Authorization": "Bearer " + TOKEN})
    assert result.status_code == 200
    assert result.json()["choices"][0]["message"]["content"] == "Grounded answer"
    assert result.json()["model"] == "codex-subscription"
    assert TOKEN not in result.text


@pytest.mark.parametrize("value", [
    [], {"stream": True}, {"model": "unapproved-model"}, {"tools": [{"type": "function"}]},
    {"messages": [{"role": "tool", "content": "bad"}]}, {"messages": []},
    {"messages": [{"role": "user", "content": {"text": "unsupported"}}]},
    {"response_format": "json"},
])
def test_invalid_requests_fail_closed(value):
    data = payload(**value) if isinstance(value, dict) else value
    assert client().post("/v1/chat/completions", json=data, headers={"Authorization": "Bearer " + TOKEN}).status_code == 400


def test_packet_limit():
    assert client().post("/v1/chat/completions", content=b"x" * (gateway.MAX_BODY + 1), headers={"Authorization": "Bearer " + TOKEN}).status_code == 413


def test_roles_and_history_are_preserved():
    seen = []
    async def runner(settings, messages, json_mode):
        seen.extend(messages)
        assert json_mode
        return '{"answer":"yes"}'
    messages = [{"role": role, "content": role} for role in ("system", "user", "assistant", "user")]
    result = client(runner).post("/v1/chat/completions", json=payload(messages=messages, response_format={"type": "json_object"}), headers={"Authorization": "Bearer " + TOKEN})
    assert result.status_code == 200
    assert seen == messages


def test_no_credentials_or_tool_authority_in_child_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "secret-db")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-api")
    monkeypatch.setenv("STRATEGYOS_CODEX_GATEWAY_TOKEN", TOKEN)
    server = gateway.CodexAppServer(gateway.Settings(TOKEN))
    command, environment = server.command(), server.environment()
    assert not {"DATABASE_URL", "OPENAI_API_KEY", "STRATEGYOS_CODEX_GATEWAY_TOKEN"} & environment.keys()
    assert 'approval_policy="never"' in command and 'web_search="disabled"' in command
    assert "mcp_servers={}" in command
    for feature in gateway.DISABLED_FEATURES:
        assert f"features.{feature}=false" in command
    assert command[-1] == "app-server"
    assert environment["HOME"] == server.settings.home
    assert environment["CODEX_HOME"] == server.settings.home


class FakeAppServer(gateway.CodexAppServer):
    def __init__(self, settings, *, answer='{"answer":"Grounded"}', complete=True):
        super().__init__(settings)
        self.workspace = "/tmp/isolated"
        self.calls = []
        self.fake_answer = answer
        self.complete = complete

    async def start(self):
        self.workspace = "/tmp/isolated"

    async def _request_raw(self, method, params=None, *, timeout=15.0):
        self.calls.append((method, params, timeout))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            queue = self.notifications["thread-1"]
            turn = {"id": "turn-1"}
            if self.complete:
                queue.put_nowait({
                    "method": "item/completed",
                    "params": {"threadId": "thread-1", "turnId": "turn-1", "item": {
                        "type": "agentMessage", "phase": "final_answer", "text": self.fake_answer,
                    }},
                })
                queue.put_nowait({
                    "method": "turn/completed",
                    "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}},
                })
            return {"turn": turn}
        return {}


def test_model_reasoning_and_sandbox_are_server_controlled():
    server = FakeAppServer(gateway.Settings(TOKEN, model="gpt-5.6-sol", reasoning_effort="medium"))
    answer = asyncio.run(server.answer(payload()["messages"], True))
    assert answer == '{"answer":"Grounded"}'
    thread_params = next(params for method, params, _ in server.calls if method == "thread/start")
    turn_params = next(params for method, params, _ in server.calls if method == "turn/start")
    assert thread_params["model"] == "gpt-5.6-sol"
    assert thread_params["ephemeral"] is True
    assert thread_params["approvalPolicy"] == "never"
    assert thread_params["sandbox"] == "read-only"
    assert turn_params["model"] == "gpt-5.6-sol"
    assert turn_params["effort"] == "medium"
    assert turn_params["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}
    assert [method for method, _, _ in server.calls][-1] == "thread/unsubscribe"


def test_text_mode_returns_plain_text():
    server = FakeAppServer(gateway.Settings(TOKEN), answer="Grounded")
    assert asyncio.run(server.answer(payload()["messages"], False)) == "Grounded"


def test_invalid_reasoning_effort_is_rejected():
    with pytest.raises(ValueError):
        gateway.Settings(TOKEN, reasoning_effort="unbounded")


def test_bounded_concurrency_and_recovery():
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def runner(*args):
            started.set()
            await release.wait()
            return "done"
        transport = httpx.ASGITransport(
            app=gateway.create_app(
                gateway.Settings(TOKEN, concurrency=1, queue_timeout=0.05),
                runner,
            )
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": "Bearer " + TOKEN}) as c:
            first = asyncio.create_task(c.post("/v1/chat/completions", json=payload()))
            await started.wait()
            busy = await c.post("/v1/chat/completions", json=payload())
            assert busy.status_code == 429
            release.set()
            assert (await first).status_code == 200
            assert (await c.post("/v1/chat/completions", json=payload())).status_code == 200
    asyncio.run(scenario())


def test_timeout_interrupts_turn_and_unsubscribes():
    server = FakeAppServer(gateway.Settings(TOKEN, timeout=1), complete=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.answer(payload()["messages"], False))
    assert exc.value.status_code == 504
    assert [method for method, _, _ in server.calls][-2:] == ["turn/interrupt", "thread/unsubscribe"]


def test_request_cancellation_interrupts_turn_and_unsubscribes():
    async def scenario():
        server = FakeAppServer(gateway.Settings(TOKEN), complete=False)
        task = asyncio.create_task(server.answer(payload()["messages"], False))
        while not any(method == "turn/start" for method, _, _ in server.calls):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert [method for method, _, _ in server.calls][-2:] == ["turn/interrupt", "thread/unsubscribe"]

    asyncio.run(scenario())


def test_invalid_structured_answer_fails_closed():
    server = FakeAppServer(gateway.Settings(TOKEN), answer="not json")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.answer(payload()["messages"], True))
    assert exc.value.status_code == 502


def test_provider_failure_does_not_leak_or_fallback():
    async def runner(*args):
        raise HTTPException(503, "Codex authentication needs administrator attention")
    result = client(runner).post("/v1/chat/completions", json=payload(), headers={"Authorization": "Bearer " + TOKEN})
    assert result.status_code == 503
    assert "DeepSeek" not in result.text


def test_short_token_is_rejected():
    with pytest.raises(ValueError):
        gateway.Settings("short")
