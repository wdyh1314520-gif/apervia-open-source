# Changelog

This file records important changes that affect usage, deployment, data, or maintenance. Formal releases follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

None.

## [1.0.1] - 2026-07-24

### Changed

- Completed English and Simplified Chinese coverage across sign-in, settings, activity, reasoning, MCP, release announcements, and administration surfaces.
- Replaced the README product screenshots with current English interface captures.
- Updated deployment guidance for sandbox image pulling, full CI verification, and the correct cloned directory.
- Added manual version checks against the official GitHub Release feed.

### Fixed

- Removed startup URL advertising and the obsolete third-party default API endpoint.
- Ensured published authentication modules match the active password-based Docker sign-in flow.
- Corrected English environment-template comments and release documentation.

### Removed

- Obsolete SMTP runtime, invite-code, editable legal-document, local-admin-token, rate-admin, and blacklist-admin code paths.
- Unused Cloud Mist and Vector Engine voice presets.
- Internal assessment, split provenance, temporary recovery, and local tooling references from the public source tree.

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

[Unreleased]: https://github.com/wdyh1314520-gif/apervia-open-source/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/wdyh1314520-gif/apervia-open-source/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/wdyh1314520-gif/apervia-open-source/releases/tag/v1.0.0
