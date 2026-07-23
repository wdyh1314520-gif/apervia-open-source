# Changelog

This file records important changes that affect usage, deployment, data, or maintenance. Formal releases follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

None.

## [1.0.0] - 2026-07-23

### Added

- Docker-native App architecture with a standalone Sandbox Runner.
- Separate model configuration and tool pipelines for Chat Completions and Responses.
- A workspace for conversations, temporary chats, files, knowledge bases, web search, and generated content.
- A server-side MCP directory with encrypted credentials, OAuth + PKCE, and permission levels.
- Account approval, role-based permissions, platform data governance, backups, auditing, and storage management.
- Multi-architecture GHCR publishing workflows for App and Sandbox images.
- Signed-in user, administrator, and release guides with verified screenshots.
- Project release announcements shown after sign-in, with account-level acknowledgement receipts.
- A direct platform administration entry point for user and permission management.

### Changed

- Docker web deployments now use server-side identity sessions and account-owned data consistently.
- Sandbox tool schemas are controlled consistently by `SANDBOX_TOOLS_ENABLED`.
- Project announcement content ships with the source code and image; the runtime database stores only account acknowledgement receipts.

### Removed

- Human-verification CAPTCHA systems unused by the current Docker sign-in flow.
- Legacy mobile authentication, device approval, device trust, and email-code sign-in entry points.
- Docker socket access from the App container and host-interpreter fallback execution.
- Legacy announcement entry points in SMTP configuration, browser local storage, and the administration console.

### Security

- Sandbox Runner requests use HMAC, timestamp, and nonce validation.
- Temporary execution containers enforce disabled networking, a read-only root filesystem, minimal privileges, and task-scoped temporary volumes.
- MCP tokens are stored on the server with Fernet encryption.

[Unreleased]: https://github.com/wdyh1314520-gif/apervia-open-source/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/wdyh1314520-gif/apervia-open-source/releases/tag/v1.0.0
