---
name: sandbox
description: Run code, test programs, process real files, and generate downloadable artifacts in an isolated sandbox for tasks that require execution or file operations.
---

# sandbox

Core execution contract aligned with ChatGPT Code Interpreter style. Use this guide before domain-specific skills.

Rules:

- Default Python execution is `sandbox_run` with `language="python"` and `code`. Do not use heredoc wrappers or long `python3 -c` strings for Python programs.
- Do not create and run ad-hoc Python files just to execute a normal one-off script. Keep code in the `code` field and let the backend run it through stdin.
- If a helper script is truly necessary, write it under `_webai_tasks/` and use a unique task name such as `_webai_tasks/webai_task_excel_optimize.py`.
- Never name temporary Python files after standard-library or common package modules, including `inspect.py`, `json.py`, `copy.py`, `typing.py`, `email.py`, `random.py`, `datetime.py`, `openpyxl.py`, `pandas.py`, or `numpy.py`.
- Use `sandbox_write_file` for ordinary non-code text/config files, not generated source-code deliverables or temporary execution wrappers.
- Generate `.py`, `.js`, `.ts`, `.c`, `.cpp`, and other source-code deliverables with `sandbox_run`, using `language="python"` and `code` that writes the requested target directly under `/mnt/data`. This preserves the real code/stdout/stderr trace. Publish the resulting output path with `sandbox_publish_files`.
- Creating a source file does not prove that the source itself runs. If the user asks for tested/runnable code, run or compile the generated target in a separate `sandbox_run` call before publishing.
- Use shell `command` / `argv` only for simple commands (`ls`, `find`, `grep`, `rm`) or for real project entrypoints.
- Generated user artifacts must be written under `/mnt/data` and published with `sandbox_publish_files`.

Typical Python flow:

1. `sandbox_import_files` when user/history files need reading.
2. `sandbox_read_file` or domain skill scripts for inspection.
3. `sandbox_run` with `language="python"` and `code` for Python processing.
4. `sandbox_publish_files` for generated outputs.
