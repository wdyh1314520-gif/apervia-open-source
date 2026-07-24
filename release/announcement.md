<!--
id: v1.0.2
version: 1.0.2
title: Apervia 1.0.2 improves runtime compatibility and language consistency
published_at: 2026-07-24
category: update
button_text: Got it
enabled: true
-->

## Apervia 1.0.2 is ready

This maintenance release makes model conversations more reliable across compatible API providers and keeps the English and Simplified Chinese interfaces consistent throughout everyday workflows.

### What's improved

- **More reliable Responses conversations**: Multi-turn conversations now adapt when a compatible provider rejects stateful continuation fields or strict output-history formats.
- **Stable request caching**: Prompt-prefix caching and image context remain intact while compatibility fallbacks are applied.
- **Consistent language display**: Usage details, activity events, file sources, provider labels, generated titles, and confirmation dialogs now follow the language selected in Apervia.
- **Natural conversation titles**: Generated titles follow the main language of the conversation and use the interface language only when the conversation language is unclear.
- **Cleaner interface logic**: Default conversation titles now share one display rule across the sidebar, search, archived conversations, sharing, and deletion confirmation.

### Upgrade notes

- Back up the `apervia_app3_data` volume before upgrading.
- Pin both the App and Sandbox images to `1.0.2`, then pull and recreate the services together.
- Existing accounts, conversations, files, MCP configuration, and acknowledgement history remain in the data volume.
- Chat Completions and Responses remain independent and keep their existing configuration boundaries.
- Select **Got it** to acknowledge this release for your account. Closing the announcement only hides it temporarily on the current page.
