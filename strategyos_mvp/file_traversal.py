from __future__ import annotations

import os
from pathlib import Path


def iter_files(root: Path, *, ignored_names: set[str] | None = None) -> list[Path]:
    """Return deterministic file paths under root, following symlinked dirs."""
    ignored = ignored_names or set()
    files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = sorted(
            name for name in dirnames if name not in ignored and not name.startswith(".")
        )
        for filename in sorted(filenames):
            if filename in ignored or filename.startswith("."):
                continue
            path = Path(current_root) / filename
            if path.is_file():
                files.append(path)
    return files
