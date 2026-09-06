from pathlib import Path


def test_preview_deployment_preserves_other_apps_and_rollback_images():
    workflow = (Path(__file__).parents[1] / ".github/workflows/strategyos-branch-deploy.yml").read_text()
    assert "docker system prune" not in workflow
    assert "docker image prune" not in workflow
    assert "docker volume prune" not in workflow
    assert "--env-file deploy/.env.secrets down" not in workflow
    assert "COMPOSE_PROJECT_NAME=strategyos-branch" in workflow
    assert workflow.index("bash deploy/scripts/backup_preview_database.sh") < workflow.index("bash deploy/scripts/deploy_stack.sh")


def test_backup_is_preview_scoped_and_validates_the_archive():
    script = (Path(__file__).parents[1] / "deploy/scripts/backup_preview_database.sh").read_text()
    assert '"${TARGET_DIR}" != "/opt/strategyos-branch"' in script
    assert "umask 077" in script
    assert "strategyos-branch-postgres-1" in script
    assert "pg_dump" in script and "pg_restore --list" in script
    assert "sha256sum" in script


def test_preview_does_not_enable_unscoped_experimental_agent_channels():
    workflow = (Path(__file__).parents[1] / '.github/workflows/strategyos-branch-deploy.yml').read_text()
    for flag in ('STRATEGYOS_TWINS_SCHEDULER_ENABLED', 'STRATEGYOS_AGENT_CONVERSATIONS_ENABLED',
                 'STRATEGYOS_AGENT_LIVE_UI_ENABLED'):
        assert flag + ": 'false'" in workflow
        assert '"' + flag + '": os.environ["' + flag + '"]' in workflow
