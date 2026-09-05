import asyncio
import json
from pathlib import Path

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


def test_no_credentials_or_tool_authority_in_child_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "secret-db")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-api")
    monkeypatch.setenv("STRATEGYOS_CODEX_GATEWAY_TOKEN", TOKEN)
    command, environment = gateway.invocation(gateway.Settings(TOKEN), tmp_path, "Use evidence")
    assert not {"DATABASE_URL", "OPENAI_API_KEY", "STRATEGYOS_CODEX_GATEWAY_TOKEN"} & environment.keys()
    assert "--ignore-user-config" in command and "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert 'approval_policy="never"' in command and 'web_search="disabled"' in command
    assert "mcp_servers={}" in command
    for feature in gateway.DISABLED_FEATURES:
        assert command[command.index(feature) - 1] == "--disable"
    assert "--model" not in command
    assert command[-1] == "-"


def test_explicit_model_is_server_controlled(tmp_path):
    command, _ = gateway.invocation(gateway.Settings(TOKEN, model="chosen-model"), tmp_path, "")
    assert command[command.index("--model") + 1] == "chosen-model"


def test_bounded_concurrency_and_recovery():
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def runner(*args):
            started.set()
            await release.wait()
            return "done"
        transport = httpx.ASGITransport(app=gateway.create_app(gateway.Settings(TOKEN), runner))
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": "Bearer " + TOKEN}) as c:
            first = asyncio.create_task(c.post("/v1/chat/completions", json=payload()))
            await started.wait()
            busy = await c.post("/v1/chat/completions", json=payload())
            assert busy.status_code == 429
            release.set()
            assert (await first).status_code == 200
            assert (await c.post("/v1/chat/completions", json=payload())).status_code == 200
    asyncio.run(scenario())


@pytest.mark.parametrize("returncode,output,expected", [(0, "hello", None), (0, "", 502), (1, "", 502)])
def test_process_results(monkeypatch, returncode, output, expected):
    async def spawn(*command, **kwargs):
        path = Path(command[command.index("--output-last-message") + 1])
        class Process:
            async def communicate(self, prompt):
                assert b"conversation" in prompt
                path.write_text(output)
            async def wait(self):
                return returncode
        process = Process()
        process.returncode = returncode
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    if expected:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(gateway.complete(gateway.Settings(TOKEN), payload()["messages"], False))
        assert exc.value.status_code == expected
    else:
        assert asyncio.run(gateway.complete(gateway.Settings(TOKEN), payload()["messages"], False)) == output


def test_timeout_kills_process_group(monkeypatch):
    killed = []
    class Process:
        pid = 12345
        async def communicate(self, prompt):
            raise TimeoutError()
        async def wait(self):
            pass
    async def spawn(*args, **kwargs):
        return Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(gateway.os, "killpg", lambda *args: killed.append(args))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gateway.complete(gateway.Settings(TOKEN), payload()["messages"], False))
    assert exc.value.status_code == 504
    assert killed == [(12345, gateway.signal.SIGKILL)]


def test_provider_failure_does_not_leak_or_fallback():
    async def runner(*args):
        raise HTTPException(503, "Codex authentication needs administrator attention")
    result = client(runner).post("/v1/chat/completions", json=payload(), headers={"Authorization": "Bearer " + TOKEN})
    assert result.status_code == 503
    assert "DeepSeek" not in result.text


def test_short_token_is_rejected():
    with pytest.raises(ValueError):
        gateway.Settings("short")
