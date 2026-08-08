from pathlib import Path


STATIC = Path("strategyos_mvp/static")


def _js() -> str:
    return (STATIC / "executive.js").read_text(encoding="utf-8")


def _css() -> str:
    return (STATIC / "executive.css").read_text(encoding="utf-8")


def _html() -> str:
    return (STATIC / "executive.html").read_text(encoding="utf-8")


def test_r3_developments_have_distinct_contracts_and_anchored_learn_more() -> None:
    js = _js()
    assert "function developmentWhat(item)" in js
    assert "function developmentWhy(item)" in js
    assert "Cause is not yet established" in js
    assert "data-development-learn-more" in js
    assert '":development:" + itemId' in js
    assert 'entrypoint: "development_learn_more"' in js


def test_r3_assistant_readiness_is_permission_aware_and_not_duplicated() -> None:
    js = _js()
    assert "function canSeeTeamReadiness()" in js
    assert "authorityRight('persona:' + state.activePersona, 'assistant_team')" in js
    assert "assistant-readiness-ring" in js
    assert "Your assistant" in js
    assert "AI assistants by executive role" not in js


def test_r3_authority_matrix_is_visible_and_drives_behavior() -> None:
    html = _html()
    js = _js()
    assert 'data-view-target="authority"' in html
    assert 'id="authority-matrix-panel"' in html
    assert "function defaultAuthorityMatrix()" in js
    assert "act-with-approval" in js
    assert "data-authority-subject" in js
    assert "renderAgentsDiscovery();" in js
    assert "putJson('/authority-matrix'" in js
    assert 'fetchJson("/authority-matrix")' in js


def test_r3_backend_enforces_and_caches_the_final_interactions() -> None:
    api = (Path("strategyos_mvp") / "api.py").read_text(encoding="utf-8")
    enrichment = (Path("strategyos_mvp") / "source_strategy_enrichment.py").read_text(encoding="utf-8")
    tools = (Path("strategyos_mvp") / "agent_runtime" / "tools.py").read_text(encoding="utf-8")
    assert '@app.put("/authority-matrix")' in api
    assert "_assistant_authority_refusal" in api
    assert "synthesize_strategy_enrichment(payload)" in enrichment
    assert "authority_subject_id" in tools


def test_r3_a2a_is_summary_first_with_modal_log() -> None:
    html = _html()
    js = _js()
    assert "function a2aSummary(thread)" in js
    assert "Open complete conversation log" in js
    assert 'id="conversation-log-modal"' in html
    assert "completedCycles" not in js


def test_r3_agents_are_objective_first_and_self_contained() -> None:
    js = _js()
    block = js.split("function renderFunctionsWorkspace()", 1)[1].split(
        "function renderLeadershipStatus", 1
    )[0]
    assert "Completed" in block and "Pending" in block and "Queued" in block
    assert "Mission and objective" in block
    assert "Open full audit log" in block
    assert "View AI Assistants" not in block
    assert "Ask Hermes for CEO brief" not in block


def test_r3_chat_is_document_style_threaded_and_expandable() -> None:
    html = _html()
    css = _css()
    js = _js()
    assert 'id="assistant-thread-list"' in html
    assert 'id="assistant-maximize"' in html
    assert "ASSISTANT_EXPANDED_STORAGE_KEY" in js
    assert ".assistant-drawer.is-maximized" in css
    message_block = css.split(".assistant-message {", 1)[1].split("}", 1)[0]
    assert "width: 100%" in message_block
    assert "max-width: none" in message_block


def test_r3_regression_strings_are_absent() -> None:
    source = "\n".join(
        [
            _js(),
            (Path("strategyos_mvp") / "executive_presentation.py").read_text(encoding="utf-8"),
            (Path("strategyos_mvp") / "api.py").read_text(encoding="utf-8"),
        ]
    )
    assert "GOOD MORNING, EXECUTIVE" not in source
    assert "no governed milestone is available" not in source
