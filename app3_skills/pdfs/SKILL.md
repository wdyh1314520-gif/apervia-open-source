---
name: pdfs
description: Read, render, extract, split, merge, or create PDFs for tasks involving pages, scans, layout, or visual evidence.
---

# pdfs

Use this skill for PDF inspection or validation when text extraction alone is not enough.

Rules:

- For visual/layout/scanned-page questions, always pair `sandbox_read_file` with `sandbox_analyze_file_images`.
- Simple PDF creation can use `sandbox_create_office_file`.
- Scripts must operate only on `/mnt/data`.
- Avoid OCR unless no text/visual alternative is enough.

Scripts:

- `/opt/app3_skills/pdfs/scripts/pdf_probe.py <file.pdf> [--json]`

Typical flow:

1. Import PDF.
2. Use `sandbox_read_file` for text layer.
3. Use `sandbox_analyze_file_images` for pages/figures/tables/layout/scans.
4. Use `pdf_probe.py` for page count and text-layer diagnostics.
