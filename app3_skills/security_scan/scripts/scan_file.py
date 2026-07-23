#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from sandbox_paths import resolve_mnt_path, rel_to_mnt  # noqa: E402

ACTIVE_EXTS = {'.html', '.htm', '.js', '.mjs', '.svg'}
ARCHIVE_EXTS = {'.zip'}
SCRIPT_PATTERNS = [
    (re.compile(rb'<script\b', re.I), 'html_script_tag'),
    (re.compile(rb'\bon\w+\s*=', re.I), 'inline_event_handler'),
    (re.compile(rb'\bfetch\s*\(', re.I), 'fetch_call'),
    (re.compile(rb'\bXMLHttpRequest\b', re.I), 'xhr_usage'),
    (re.compile(rb'\beval\s*\(', re.I), 'eval_call'),
    (re.compile(rb'\bdocument\.cookie\b', re.I), 'cookie_access'),
    (re.compile(rb'\blocalStorage\b', re.I), 'local_storage_access'),
]


def scan_bytes(path: Path, max_read: int = 2_000_000) -> list[dict]:
    findings = []
    data = path.read_bytes()[:max_read]
    for pattern, code in SCRIPT_PATTERNS:
        if pattern.search(data):
            findings.append({'severity': 'medium', 'code': code})
    if path.suffix.lower() in ACTIVE_EXTS:
        findings.append({'severity': 'medium', 'code': 'active_content_extension'})
    return findings


def scan_zip(path: Path) -> tuple[list[dict], dict]:
    findings = []
    meta = {'entries': 0, 'total_uncompressed': 0, 'max_ratio': 0.0}
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            meta['entries'] += 1
            name = str(info.filename or '').replace('\\', '/')
            if not name or name.startswith('/') or '\x00' in name:
                findings.append({'severity': 'high', 'code': 'unsafe_zip_member_name', 'member': name})
            parts = [p for p in name.split('/') if p]
            if '..' in parts:
                findings.append({'severity': 'high', 'code': 'zip_slip_path_traversal', 'member': name})
            mode = (int(getattr(info, 'external_attr', 0) or 0) >> 16) & 0o170000
            if mode == 0o120000:
                findings.append({'severity': 'high', 'code': 'zip_symlink_member', 'member': name})
            size = max(0, int(getattr(info, 'file_size', 0) or 0))
            compressed = max(1, int(getattr(info, 'compress_size', 0) or 0))
            ratio = float(size) / float(compressed)
            meta['total_uncompressed'] += size
            meta['max_ratio'] = max(float(meta['max_ratio']), ratio)
            if size > 80 * 1024 * 1024:
                findings.append({'severity': 'high', 'code': 'zip_member_too_large', 'member': name, 'bytes': size})
            if meta['total_uncompressed'] > 256 * 1024 * 1024:
                findings.append({'severity': 'high', 'code': 'zip_total_uncompressed_too_large', 'bytes': meta['total_uncompressed']})
            if size > 1024 * 1024 and ratio > 120:
                findings.append({'severity': 'high', 'code': 'zip_compression_ratio_too_high', 'member': name, 'ratio': round(ratio, 2)})
            if Path(name).suffix.lower() in ACTIVE_EXTS:
                findings.append({'severity': 'medium', 'code': 'active_content_inside_zip', 'member': name})
    return findings, meta


def main() -> int:
    parser = argparse.ArgumentParser(description='Scan a /mnt/data file for common active-content/archive risks.')
    parser.add_argument('path')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    path = resolve_mnt_path(args.path)
    result = {
        'ok': True,
        'path': rel_to_mnt(path),
        'exists': path.exists(),
        'size': path.stat().st_size if path.exists() else 0,
        'findings': [],
        'summary': 'no obvious risk found',
    }
    if not path.exists() or not path.is_file():
        result.update({'ok': False, 'summary': 'file not found or not a regular file'})
    else:
        suffix = path.suffix.lower()
        try:
            if suffix in ARCHIVE_EXTS:
                findings, meta = scan_zip(path)
                result['archive'] = meta
                result['findings'].extend(findings)
            if suffix in ACTIVE_EXTS or path.stat().st_size <= 5_000_000:
                result['findings'].extend(scan_bytes(path))
        except zipfile.BadZipFile:
            result['findings'].append({'severity': 'high', 'code': 'bad_zip_file'})
        except Exception as exc:
            result.update({'ok': False, 'error': f'{type(exc).__name__}: {exc}'})
        severities = [str(f.get('severity') or '') for f in result['findings'] if isinstance(f, dict)]
        if 'high' in severities:
            result['summary'] = 'high risk findings present'
        elif 'medium' in severities:
            result['summary'] = 'active content or suspicious behavior found'
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result['summary'])
        for finding in result.get('findings') or []:
            print('-', finding)
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
