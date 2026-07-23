#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from sandbox_paths import resolve_mnt_path, rel_to_mnt  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description='Probe basic PDF metadata/text layer from /mnt/data.')
    parser.add_argument('path')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    path = resolve_mnt_path(args.path)
    result = {'ok': False, 'path': rel_to_mnt(path), 'pages': None, 'text_chars_sampled': 0, 'text_layer_likely': False}
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        result['pages'] = len(reader.pages)
        total = 0
        for page in reader.pages[:10]:
            try:
                total += len(page.extract_text() or '')
            except Exception:
                pass
        result['text_chars_sampled'] = total
        result['text_layer_likely'] = total > 80
        result['ok'] = True
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
