"""Install/rollback an explicitly selected provider; preserve running app images.

Run as the deployment owner on the host. Credentials never leave that host.
The persistent overlay is outside app/ so normal release syncs cannot delete it.
"""
import argparse
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

TARGETS = {
    "preview": (Path("/opt/strategyos-branch"), "strategyos-branch"),
    "production": (Path("/opt/strategyos"), "strategyos"),
}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def inspect(name):
    return json.loads(run("docker", "inspect", name, capture_output=True).stdout)[0]


def save_private(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "activate", "rollback"])
    parser.add_argument("--target", choices=tuple(TARGETS), default="preview")
    parser.add_argument("--image", default="strategyos-codex-gateway:0.149.0")
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--auth-source", type=Path)
    args = parser.parse_args()
    ROOT, PROJECT = TARGETS[args.target]
    PROVIDER = ROOT / "provider-codex"
    PROVIDER.mkdir(mode=0o750, exist_ok=True)
    api = inspect(PROJECT + "-strategyos-api-1")
    config_files = api["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")
    # Provider activation pins are deliberately excluded from future app releases.
    config_files = [f for f in config_files if Path(f).is_relative_to(ROOT / "app")]
    if not config_files or any(not Path(f).is_file() for f in config_files):
        raise SystemExit("Cannot resolve the selected deployment")
    pins = {"services": {}}
    for service in ("strategyos-api", "strategyos-worker"):
        container = inspect(PROJECT + "-" + service + "-1")
        pins["services"][service] = {"image": container["Image"]}
    save_private(PROVIDER / "activation-images.json", json.dumps(pins))
    compose = ["docker", "compose", "--project-name", PROJECT, "--profile", "hatchet"]
    for file in config_files:
        compose += ["-f", file]
    compose += ["--env-file", str(ROOT / "app/deploy/.env"), "--env-file", str(ROOT / "app/deploy/.env.secrets")]
    baseline = compose + ["-f", str(PROVIDER / "activation-images.json")]
    marker = PROVIDER / "enabled"
    if args.mode == "rollback":
        run(*baseline, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180", "strategyos-api", "strategyos-worker")
        if marker.exists():
            marker.rename(PROVIDER / "disabled")
        print(f"{args.target} provider rolled back; app images and business data preserved")
        return
    if args.mode == "prepare":
        if not args.overlay or not args.overlay.is_file():
            raise SystemExit("Pass the reviewed Codex compose overlay")
        auth_dir = PROVIDER / "auth"
        auth_dir.mkdir(mode=0o700, exist_ok=True)
        os.chown(auth_dir, 10001, 10001)
        auth = auth_dir / "auth.json"
        if not auth.exists():
            if not args.auth_source or not args.auth_source.is_file():
                raise SystemExit("A valid subscription login is required; no credentials were changed")
            shutil.copyfile(args.auth_source, auth)
            os.chmod(auth, 0o600)
            os.chown(auth, 10001, 10001)
        token_path = PROVIDER / "gateway-token"
        if not token_path.exists():
            save_private(token_path, secrets.token_urlsafe(48))
            os.chown(token_path, 10001, 10001)
        shutil.copyfile(args.overlay, PROVIDER / "compose.yml")
        save_private(PROVIDER / "provider.env", "\n".join([
            "STRATEGYOS_CODEX_GATEWAY_TOKEN=" + token_path.read_text().strip(),
            "STRATEGYOS_CODEX_TOKEN_PATH=" + str(token_path),
            "STRATEGYOS_CODEX_AUTH_DIR=" + str(auth_dir),
            "STRATEGYOS_CODEX_IMAGE=" + args.image,
            "STRATEGYOS_CODEX_MODEL=",
            "",
        ]))
    configured = compose + ["--env-file", str(PROVIDER / "provider.env"), "-f", str(PROVIDER / "compose.yml"), "-f", str(PROVIDER / "activation-images.json")]
    if args.mode == "prepare":
        run(*configured, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "90", "codex-gateway")
        print("Isolated provider ready for live smoke tests; application routing unchanged")
        return
    try:
        run(*configured, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180", "strategyos-api", "strategyos-worker")
    except subprocess.CalledProcessError:
        run(*baseline, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "strategyos-api", "strategyos-worker")
        raise
    save_private(marker, "codex_cli\n")
    print(f"{args.target} API and worker now use Codex; existing app images preserved")


if __name__ == "__main__":
    main()
