#!/usr/bin/env python3
"""Atomically advance an enabled host-managed Codex provider to one release."""
from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path


IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$")


def update(path: Path, *, image: str) -> None:
    if not path.is_file():
        raise ValueError("The enabled provider environment is missing.")
    if not IMAGE.fullmatch(image):
        raise ValueError("The Codex gateway image must be an immutable GHCR digest reference.")
    updates = {
        "STRATEGYOS_CODEX_IMAGE": image,
        "STRATEGYOS_CODEX_MODEL": "gpt-5.6-sol",
        "STRATEGYOS_CODEX_REASONING_EFFORT": "medium",
        "STRATEGYOS_CODEX_SERVICE_TIER": "priority",
        "STRATEGYOS_CODEX_CONCURRENCY": "4",
        "STRATEGYOS_CODEX_QUEUE_TIMEOUT": "15",
    }
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    rendered: list[str] = []
    for line in lines:
        key = line.partition("=")[0] if line and not line.startswith("#") else ""
        if key in updates:
            if key not in seen:
                rendered.append(f"{key}={updates[key]}")
                seen.add(key)
        else:
            rendered.append(line)
    for key, value in updates.items():
        if key not in seen:
            rendered.append(f"{key}={value}")
    mode = path.stat().st_mode & 0o777
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join(rendered) + "\n")
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try:
        update(args.env_file, image=args.image)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
