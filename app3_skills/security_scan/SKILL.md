---
name: security-scan
description: Inspect archives, scripts, HTML, and suspicious files for risk in the sandbox when users request security scanning, malware analysis, or risk assessment.
---

# security_scan

Use this skill when the user asks whether an uploaded/generated file is safe, or when handling HTML/JS/ZIP/archive files that may contain active content.

Rules:

- Never execute uploaded HTML/JS/SVG or Office macros.
- ZIP/archive inspection must block path traversal, absolute paths, symlinks, huge members, huge total uncompressed size, and extreme compression ratio.
- Operate only on `/mnt/data` paths.
- Prefer a report file in `/mnt/data` for user-facing audit results.
- Do not expose internal server paths or security implementation secrets in final wording.

Scripts:

- `/opt/app3_skills/security_scan/scripts/scan_file.py <path> [--json]`

Typical flow:

1. Import the suspicious file with `sandbox_import_files`.
2. Run `python /opt/app3_skills/security_scan/scripts/scan_file.py <path> --json` inside `sandbox_run`.
3. Summarize the result. If a report is requested, write/publish it with existing sandbox tools.
