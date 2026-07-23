---
name: slides
description: Read, inspect, create, or modify PowerPoint presentations for tasks involving PPT/PPTX files, slides, or presentation materials.
---

# slides

Use this skill for PowerPoint inspection when slide text, media, or package structure matters.

Rules:

- Simple PPTX generation should use `sandbox_create_office_file`.
- For design/layout/screenshot/chart questions, use `sandbox_analyze_file_images` after import.
- Scripts only read/write `/mnt/data`.

Scripts:

- `/opt/app3_skills/slides/scripts/pptx_outline.py <file.pptx> [--json]`
