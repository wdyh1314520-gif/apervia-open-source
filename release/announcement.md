<!--
id: v1.0.1
version: 1.0.1
title: Apervia 1.0.1 improves clarity and consistency
published_at: 2026-07-24
category: update
button_text: Got it
enabled: true
-->

## Apervia 1.0.1 is ready

This update makes the public release match the current Docker experience more closely, with more complete language coverage, a leaner authentication runtime, and clearer deployment guidance.

### What's improved

- **Complete language switching**: Sign-in, settings, activity, reasoning, MCP, release information, and administration now follow the language selected in the app.
- **Cleaner authentication runtime**: Obsolete SMTP, invite-code, editable legal-document, local-token, and legacy administration paths have been removed from the published application.
- **Clearer deployment**: The setup guide now covers the correct clone directory, explicit Sandbox image pulling, complete CI checks, and current English screenshots.
- **Quieter defaults**: Startup URL advertising, the obsolete third-party API default, and unused voice presets have been removed.
- **Version awareness**: Account settings can check the official GitHub Release feed for a newer Apervia version.

### Upgrade notes

- Back up the `apervia_app3_data` volume before upgrading.
- Update both the App and Sandbox image references to `1.0.1`, then pull and recreate the services together.
- Chat Completions and Responses remain independent and keep their existing configuration boundaries.
- Select **Got it** to acknowledge this release for your account. Closing the announcement only hides it temporarily on the current page.
