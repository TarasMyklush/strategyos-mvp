from pathlib import Path

import pytest

from deploy.scripts.update_codex_provider_release import update


IMAGE = "ghcr.io/tarasmyklush/strategyos-mvp-codex-gateway@sha256:" + "a" * 64


def test_provider_release_update_preserves_credentials_and_pins_runtime(tmp_path: Path):
    path = tmp_path / "provider.env"
    path.write_text(
        "STRATEGYOS_CODEX_GATEWAY_TOKEN=private-token\n"
        "STRATEGYOS_CODEX_IMAGE=old-local-image\n"
        "STRATEGYOS_CODEX_MODEL=old-model\n"
        "STRATEGYOS_CODEX_CONCURRENCY=2\n"
    )
    path.chmod(0o600)

    update(path, image=IMAGE)

    values = dict(line.split("=", 1) for line in path.read_text().splitlines())
    assert values["STRATEGYOS_CODEX_GATEWAY_TOKEN"] == "private-token"
    assert values["STRATEGYOS_CODEX_IMAGE"] == IMAGE
    assert values["STRATEGYOS_CODEX_MODEL"] == "gpt-5.6-sol"
    assert values["STRATEGYOS_CODEX_REASONING_EFFORT"] == "medium"
    assert values["STRATEGYOS_CODEX_SERVICE_TIER"] == "priority"
    assert values["STRATEGYOS_CODEX_CONCURRENCY"] == "4"
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("image", ["latest", "ghcr.io/org/image:tag", "$(unsafe)"])
def test_provider_release_update_rejects_mutable_or_unsafe_images(tmp_path: Path, image: str):
    path = tmp_path / "provider.env"
    path.write_text("STRATEGYOS_CODEX_GATEWAY_TOKEN=private-token\n")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        update(path, image=image)
    assert path.read_bytes() == before
