---
name: docx
description: Read, inspect, create, or modify Word documents for tasks involving DOC/DOCX files, contracts, reports, papers, resumes, or document formatting.
---

# docx

Use this skill for complex Word document inspection, validation, or extraction when `sandbox_create_office_file` is not enough.

Rules:

- Simple Word generation should still use `sandbox_create_office_file`.
- For existing DOCX review, first use `sandbox_read_file`; if structure, tables, embedded media, or formulas matter, combine with rendered evidence from `sandbox_analyze_file_images`.
- Scripts only read/write `/mnt/data`.
- Do not use host shell fallback.

Scripts:

- `/opt/app3_skills/docx/scripts/docx_outline.py <file.docx> [--json]`

Typical flow:

1. Import file.
2. Read text with `sandbox_read_file`.
3. Run the outline script only when headings/tables/media/package structure matter.
4. Publish generated outputs only through `sandbox_publish_files`.
