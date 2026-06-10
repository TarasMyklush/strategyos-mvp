import pytest

import strategyos_mvp.agents.pipeline as pipeline_module
import strategyos_mvp.config as config_module
import strategyos_mvp.data_roles as data_roles_module
import strategyos_mvp.plugins as plugins_module
import strategyos_mvp.source_pack as source_pack_module
import strategyos_mvp.tasks as tasks_module
import strategyos_mvp.skills.finance_controls as finance_controls_module


def _restore_registries(snapshot: dict[str, object]) -> None:
    tasks_module._TASK_REGISTRY.clear()
    tasks_module._TASK_REGISTRY.update(snapshot["tasks"])
    data_roles_module._DATA_ROLE_REGISTRY.clear()
    data_roles_module._DATA_ROLE_REGISTRY.update(snapshot["data_roles"])
    pipeline_module._STAGE_REGISTRY.clear()
    pipeline_module._STAGE_REGISTRY.update(snapshot["stages"])
    finance_controls_module.DETECTOR_REGISTRY[:] = snapshot["detectors"]
    finance_controls_module.KNOWN_PATTERN_TYPES = snapshot["known_patterns"]
    source_pack_module.refresh_source_pack_role_constants()
    finance_controls_module.refresh_role_path_defaults()


@pytest.fixture()
def registry_snapshot():
    snapshot = {
        "tasks": dict(tasks_module._TASK_REGISTRY),
        "data_roles": dict(data_roles_module._DATA_ROLE_REGISTRY),
        "stages": dict(pipeline_module._STAGE_REGISTRY),
        "detectors": list(finance_controls_module.DETECTOR_REGISTRY),
        "known_patterns": finance_controls_module.KNOWN_PATTERN_TYPES,
    }
    try:
        yield
    finally:
        _restore_registries(snapshot)
        plugins_module.reset_plugin_loader_for_tests()


def test_plugin_loader_imports_module_once_and_registers_extensions(
    tmp_path,
    monkeypatch,
    registry_snapshot,
):
    module_path = tmp_path / "strategyos_test_plugin.py"
    module_path.write_text(
        """
from strategyos_mvp.agents.pipeline import AgentStage, register_stage
from strategyos_mvp.data_roles import DataRoleSpec, register_data_role
from strategyos_mvp.models import Finding
from strategyos_mvp.skills.finance_controls import register_detector
from strategyos_mvp.tasks import TaskSpec, register_task

IMPORT_COUNT = 1

register_stage(AgentStage("tax_review", "Tax Review"))
register_data_role(
    DataRoleSpec(
        role="tax_notice",
        label="Tax notice",
        kind="document",
        target_folder="09_Tax_Notices",
    )
)
register_task(
    TaskSpec(
        task_key="tax_notice_review",
        label="Tax Notice Review",
        required_roles=("ap_ledger",),
        readiness_reason="Tax notice review uses AP context.",
        missing_role_labels={"ap_ledger": "classified AP coverage"},
    )
)

@register_detector("plugin_tax_signal", ("ap_ledger",))
def detect_plugin_tax_signal(bundle):
    return []
""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    first = plugins_module.load_plugin_modules(("strategyos_test_plugin",))
    second = plugins_module.load_plugin_modules(("strategyos_test_plugin",))

    assert [record.status for record in first] == ["loaded"]
    assert [record.status for record in second] == ["already_loaded"]
    assert "tax_review" in pipeline_module._STAGE_REGISTRY
    assert "tax_notice_review" in tasks_module._TASK_REGISTRY
    assert "tax_notice" in data_roles_module._DATA_ROLE_REGISTRY
    assert "plugin_tax_signal" in finance_controls_module.KNOWN_PATTERN_TYPES


def test_plugin_task_appears_in_source_pack_readiness(
    tmp_path,
    monkeypatch,
    registry_snapshot,
):
    module_path = tmp_path / "strategyos_task_plugin.py"
    module_path.write_text(
        """
from strategyos_mvp.tasks import TaskSpec, register_task

register_task(
    TaskSpec(
        task_key="plugin_ap_check",
        label="Plugin AP Check",
        required_roles=("ap_ledger",),
        readiness_reason="Plugin AP check uses AP coverage.",
        missing_role_labels={"ap_ledger": "classified AP coverage"},
    )
)
""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    plugins_module.load_plugin_modules(("strategyos_task_plugin",))

    payload = source_pack_module.build_task_readiness(
        [
            {
                "supported": True,
                "classification": {"status": "classified", "role": "ap_ledger"},
            }
        ]
    )
    tasks_by_key = {item["task_key"]: item for item in payload["tasks"]}

    assert tasks_by_key["plugin_ap_check"]["status"] == "ready"


def test_plugin_loader_strict_and_permissive_failure_modes(registry_snapshot):
    with pytest.raises(RuntimeError, match="failed to load"):
        plugins_module.load_plugin_modules(("strategyos_missing_plugin_for_test",))

    plugins_module.reset_plugin_loader_for_tests()
    records = plugins_module.load_plugin_modules(
        ("strategyos_missing_plugin_for_test",),
        failure_mode="permissive",
    )

    assert records[0].status == "failed"
    assert "ModuleNotFoundError" in str(records[0].error)


def test_plugin_config_reads_module_list_and_failure_mode(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_PLUGIN_MODULES", "one.two, three.four")
    monkeypatch.setenv("STRATEGYOS_PLUGIN_FAILURE_MODE", "permissive")

    config = config_module.load_config()

    assert config.plugin_modules == ("one.two", "three.four")
    assert config.plugin_failure_mode == "permissive"
