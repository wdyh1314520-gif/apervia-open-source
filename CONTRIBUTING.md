# Contributing Guide

Thank you for helping maintain Apervia. Before submitting a change, confirm that the issue belongs within the current Docker project boundaries and keep the implementation unified, removable, and testable.

## Design principles

- Chat Completions and Responses must retain separate protocol, streaming, and tool-calling boundaries.
- Legacy and replacement implementations must not coexist indefinitely. When a legacy entry point cannot be reused, remove its configuration, routes, state, and tests together.
- Extract shared capabilities into clearly defined services or classes instead of duplicating business logic.
- The App must never mount the Docker socket. Sandbox execution must go through the standalone Runner.
- User interface copy should focus on user tasks and benefits. Put migration notes and implementation details in maintenance documentation.
- Never commit `.env` files, tokens, databases, uploads, logs, backups, or runtime data.

## Development workflow

1. Create a clearly named `feature/<description>`, `fix/<description>`, or documentation branch from the latest `main`.
2. Locate the existing entry points, callers, and tests before deciding whether to modify, migrate, or remove behavior.
3. Keep directory names in English and encode all source files and comments as UTF-8.
4. Add regression coverage for behavioral changes and update the README, guides, or runbook as needed.
5. Keep each change focused on a single purpose and merge it through a pull request.

## Local verification

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q app3.py app3_parts sandbox_runner mcp_client tests
docker compose --profile sandbox config --quiet
docker compose --profile sandbox-build config --quiet
```

Run `node --check` for every affected frontend JavaScript file. Changes involving images, security parameters, data recovery, or the Sandbox Runner require real Docker smoke tests in addition to static assertions.

## Pull requests

A pull request description should include:

- The change and its user impact.
- The root cause or design motivation.
- Legacy entry points that were removed or migrated.
- Verification commands and results.
- Data, deployment, security, and rollback impact.
- Verified screenshots for user interface changes.

Do not mix unrelated formatting or unauthorized refactoring into the same pull request.
