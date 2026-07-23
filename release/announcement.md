<!--
id: v1.0.0
version: 1.0.0
title: Apervia 1.0.0 is now available
published_at: 2026-07-23
category: update
button_text: Got it
enabled: true
-->

## Welcome to Apervia 1.0.0

This is the first formal release of Apervia. It brings conversations, files, knowledge bases, web search, MCP tools, and an isolated sandbox into one workspace, with a complete account and operations model for Docker deployments.

### Included in this release

- **Unified workspace**: Manage regular conversations, temporary chats, attachments, generated files, and long-term knowledge bases in one place.
- **Separate API modes**: Configure and run Chat Completions and Responses independently so the protocols do not interfere with each other.
- **MCP integration**: Use a server-side MCP directory, OAuth authorization, encrypted credentials, and permission levels.
- **Secure sandbox**: Run code and document tasks through the standalone Sandbox Runner with networking disabled, a read-only root filesystem, and minimal privileges by default.
- **Account and data management**: Manage registration approval, roles, sessions, backups, auditing, and storage governance.
- **Production container delivery**: Deploy matching multi-architecture App and Sandbox images with fixed-version upgrade and rollback support.

### Getting started

- After your first sign-in, open **Settings** and configure the required API key, API type, and model for each mode.
- When using search or model services running on the host, enter an address that the container can reach; do not use the container's own `127.0.0.1`.
- Select **Got it** to acknowledge this release for your account. Closing the announcement only hides it temporarily on the current page.
