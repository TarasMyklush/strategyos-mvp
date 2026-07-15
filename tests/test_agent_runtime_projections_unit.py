"""Pure-unit tests for agent_runtime.projections status-label mapping and
module_id stability -- no Postgres required.
"""

from __future__ import annotations

from strategyos_mvp.agent_runtime.models import HandoffStatus, TaskStatus
from strategyos_mvp.agent_runtime.projections import (
    AGENT_KEY_TO_MODULE_ID,
    _handoff_status_label,
    _task_status_label,
)
from strategyos_mvp.agent_runtime.registry import AGENT_DEFINITIONS


def test_every_agent_key_maps_to_a_stable_module_id():
    for definition in AGENT_DEFINITIONS:
        assert definition.agent_key in AGENT_KEY_TO_MODULE_ID


def test_module_ids_match_the_existing_ui_card_ids():
    # Must match api.py's _agent_modules_payload() module_id values exactly
    # so the current UI's cards keep resolving once switched to this projection.
    assert AGENT_KEY_TO_MODULE_ID["cash-recovery"] == "cash-recovery-watch"
    assert AGENT_KEY_TO_MODULE_ID["evidence-closure"] == "evidence-closure-monitor"
    assert AGENT_KEY_TO_MODULE_ID["board-pack"] == "board-pack-compiler"
    assert AGENT_KEY_TO_MODULE_ID["runtime-guardrail"] == "runtime-guardrail"


def test_every_task_status_has_a_non_empty_human_readable_label():
    for task_status in TaskStatus:
        label = _task_status_label(task_status.value)
        assert label
        assert "_" not in label  # every mapped label is human-readable prose, not a raw enum value


def test_running_status_maps_to_working_label():
    assert _task_status_label(TaskStatus.RUNNING.value) == "Working"


def test_waiting_for_approval_maps_to_waiting_for_reviewer_label():
    assert _task_status_label(TaskStatus.WAITING_FOR_APPROVAL.value) == "Waiting for reviewer"


def test_succeeded_maps_to_complete_not_generic_active():
    assert _task_status_label(TaskStatus.SUCCEEDED.value) == "Complete"


def test_failed_maps_to_could_not_complete_not_a_raw_error():
    assert _task_status_label(TaskStatus.FAILED.value) == "Could not complete"


def test_every_handoff_status_has_a_label():
    for handoff_status in HandoffStatus:
        assert _handoff_status_label(handoff_status.value)


def test_unknown_status_falls_back_to_the_raw_value_not_a_crash():
    assert _task_status_label("some_future_status") == "some_future_status"
