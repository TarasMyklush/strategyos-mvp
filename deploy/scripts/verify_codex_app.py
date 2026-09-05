"""Read-only live transport checks, run inside API and worker containers."""
import json
import os
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from strategyos_mvp.config import EXTERNAL_MODE_MODEL_PROVIDER, load_config
from strategyos_mvp import llm_qa
from strategyos_mvp.twins.reasoning import _call_litellm_reasoning

config = load_config()
status = llm_qa.chat_status(config)
assert config.llm_provider == "codex_cli", "Wrong configured provider"
assert config.llm_base_url == "http://codex-gateway:8091/v1"
if not (config.llm_chat_enabled and config.model_provider_enabled
        and config.run_policy.allows(EXTERNAL_MODE_MODEL_PROVIDER)):
    # The existing worker runs deterministically with model access disabled.
    # A provider migration must not silently grant it new external authority.
    assert "--http" not in sys.argv, "Interactive API unexpectedly disabled"
    assert not status["enabled"], "Run-policy gate was bypassed"
    print(json.dumps({"provider_configuration": config.llm_provider,
                      "external_model_access": "disabled_by_existing_policy",
                      "policy_preserved": True}), flush=True)
    sys.exit(0)
assert status["enabled"] and status["provider"] == "codex_cli", status
answer = llm_qa._call_openai_compatible_chat(
    config=config,
    messages=[{"role": "system", "content": "Return JSON with answer='ok'."}, {"role": "user", "content": "Provider acceptance check"}],
    temperature=0, max_tokens=30, response_format={"type": "json_object"},
)
assert json.loads(answer)["answer"].lower() == "ok"
print(json.dumps({"transport": "hermes", "provider": status["provider"], "model_selection": status["model"], "passed": True}), flush=True)
specialist = _call_litellm_reasoning(
    config=config, stage="perception", input_context={
        "role": "cfo", "evidence_refs": [],
        "instruction": "No business evidence is provided. Return an empty items array; do not invent an issue.",
    },
)
assert isinstance(json.loads(specialist), dict)
print(json.dumps({"transport": "specialist", "structured_response": True}), flush=True)

if "--http" in sys.argv:
    credentials = urlencode({
        "grant_type": "password",
        "client_id": os.environ["STRATEGYOS_IDP_CLIENT_ID"],
        "client_secret": os.environ["STRATEGYOS_IDP_CLIENT_SECRET"],
        "username": os.environ["STRATEGYOS_IDP_OPERATOR_USERNAME"],
        "password": os.environ["STRATEGYOS_IDP_OPERATOR_PASSWORD"],
    }).encode()
    with urlopen(Request(os.environ["STRATEGYOS_IDP_TOKEN_URL"], data=credentials), timeout=15) as response:
        token = json.load(response)["access_token"]
    request = Request("http://127.0.0.1:8000/assistant/chat", data=json.dumps({
        "question": "Explain the main operating cost concern and distinguish what is evidenced from what still needs verification.",
        "persona": "ceo", "mode": "llm",
    }).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    with urlopen(request, timeout=180) as response:
        result = json.load(response)
    assert result.get("answer"), "No executive answer returned"
    assert result.get("mode") == "llm", "Expected a real model-backed response"
    assert (result.get("llm_status") or {}).get("provider") == "codex_cli", "Wrong provider"
    # Keep actual company answers and evidence out of CI logs.
    print(json.dumps({"authenticated_hermes_endpoint": True, "mode": result["mode"], "provider": "codex_cli", "answer_characters": len(result["answer"])}), flush=True)
