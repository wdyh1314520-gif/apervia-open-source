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

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def text_of(node: ET.Element) -> str:
    return ''.join(t.text or '' for t in node.findall('.//w:t', NS)).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description='Extract a lightweight DOCX outline from /mnt/data.')
    parser.add_argument('path')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    path = resolve_mnt_path(args.path)
    result = {'ok': False, 'path': rel_to_mnt(path), 'paragraph_count': 0, 'headings': [], 'tables': 0, 'media': []}
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read('word/document.xml')
            root = ET.fromstring(xml)
            paragraphs = root.findall('.//w:p', NS)
            result['paragraph_count'] = len(paragraphs)
            for p in paragraphs:
                txt = text_of(p)
                if not txt:
                    continue
                pstyle = p.find('.//w:pStyle', NS)
                style = ''
                if pstyle is not None:
                    style = str(pstyle.attrib.get('{%s}val' % NS['w']) or '')
                if style.lower().startswith('heading') or re.match(r'^\s*#{1,6}\s+', txt):
                    result['headings'].append({'style': style, 'text': txt[:240]})
            result['tables'] = len(root.findall('.//w:tbl', NS))
            result['media'] = sorted([n for n in zf.namelist() if n.startswith('word/media/')])[:200]
            result['ok'] = True
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
