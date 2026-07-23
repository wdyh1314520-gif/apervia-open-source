#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from sandbox_paths import resolve_mnt_path, rel_to_mnt  # noqa: E402

NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}


def main() -> int:
    parser = argparse.ArgumentParser(description='Extract lightweight PPTX slide text from /mnt/data.')
    parser.add_argument('path')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    path = resolve_mnt_path(args.path)
    result = {'ok': False, 'path': rel_to_mnt(path), 'slides': [], 'media': []}
    try:
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted([n for n in zf.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)], key=lambda n: int(re.search(r'(\d+)', n).group(1)))
            for name in slide_names:
                root = ET.fromstring(zf.read(name))
                texts = [t.text or '' for t in root.findall('.//a:t', NS)]
                result['slides'].append({'name': name, 'text': ' '.join(x.strip() for x in texts if x.strip())[:1200]})
            result['media'] = sorted([n for n in zf.namelist() if n.startswith('ppt/media/')])[:200]
            result['ok'] = True
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
