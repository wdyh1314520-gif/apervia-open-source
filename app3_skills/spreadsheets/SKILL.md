---
name: spreadsheets
description: Read, inspect, create, or analyze Excel/CSV workbooks for tasks involving formulas, charts, data processing, or spreadsheet formatting.
---

# spreadsheets

Use this skill for Excel/CSV workbook inspection when formulas, sheets, dimensions, or package structure matter.

Rules:

- Simple spreadsheet creation should use `sandbox_create_office_file`.
- Do not use LibreOffice or heavy conversion unless the user needs rendered layout.
- For visual chart/layout questions, pair with `sandbox_analyze_file_images`.
- Scripts only read/write `/mnt/data`.

Scripts:

- `/opt/app3_skills/spreadsheets/scripts/xlsx_probe.py <file.xlsx> [--json]`
