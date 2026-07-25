<!--
id: v1.0.3
version: 1.0.3
title: Apervia 1.0.3 brings a more polished and consistent workspace
published_at: 2026-07-25
category: update
button_text: Got it
enabled: true
-->

This release focuses on the details that make Apervia easier to deploy, administer, and use every day. The workspace now feels more consistent in both supported languages, Responses compatibility is more resilient, and administration is collected in one place.

### What's improved

- **One administration console**: Account access, platform data, MCP, backups, auditing, maintenance, and rate-limit status are now organized under `/admin`.
- **Complete language consistency**: Settings, activity events, system errors, file sources, administrator data, and generated titles follow the selected interface language without changing user or model content.
- **More resilient Responses conversations**: Compatible providers that reject stateful continuation fields or strict output history now fall back safely while keeping Chat Completions isolated.
- **Stable prompt-prefix caching**: Compatibility fallbacks preserve reusable request prefixes and image context instead of rebuilding unrelated request sections.
- **Refined release experience**: Version announcements now use a clearer layout, accessible motion, a confirmation celebration, and a smooth exit.
- **Updated deployment guidance**: The README and operator documentation now match the current Docker workflow, unified administration, and Sandbox image lifecycle.

### Upgrade notes

- Back up the `apervia_app3_data` volume before upgrading.
- Pin both the App and Sandbox images to `1.0.3`, then pull and recreate the services together.
- Existing accounts, conversations, files, MCP configuration, and acknowledgement history remain in the data volume.
- Chat Completions and Responses remain independent and keep their existing configuration boundaries.
- Select **Got it** to acknowledge this release for your account. Closing the announcement only hides it temporarily on the current page.
