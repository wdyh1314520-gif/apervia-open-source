from __future__ import annotations

import os
from pathlib import Path

SANDBOX_ROOT = Path('/mnt/data').resolve()


def resolve_mnt_path(raw: str) -> Path:
    value = str(raw or '').strip()
    if not value:
        raise ValueError('empty path')
    if value.startswith('/mnt/data/') or value == '/mnt/data':
        path = Path(value)
    elif value.startswith('/'):
        raise ValueError('absolute paths outside /mnt/data are not allowed')
    else:
        path = SANDBOX_ROOT / value
    resolved = path.resolve()
    if resolved != SANDBOX_ROOT and SANDBOX_ROOT not in resolved.parents:
        raise ValueError('path escapes /mnt/data')
    return resolved


def rel_to_mnt(path: Path) -> str:
    return str(path.resolve().relative_to(SANDBOX_ROOT))
