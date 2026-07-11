from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_branch_caddyfile_emits_hsts_for_https_public_edge() -> None:
    caddyfile = (REPO_ROOT / "deploy/caddy/Caddyfile.branch").read_text(
        encoding="utf-8"
    )

    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains"' in caddyfile

