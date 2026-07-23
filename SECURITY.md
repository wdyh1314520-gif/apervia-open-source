# Security Policy

## Supported versions

Apervia currently follows a rolling maintenance policy. The latest commit on `main` and the most recent formal release tag receive security fixes. Older versions may need to be upgraded before a fix can be applied.

## Reporting a vulnerability

Do not disclose unpatched vulnerabilities, exploitation methods, access tokens, or user data in public issues, pull requests, discussions, or logs.

Prefer the repository's private **Security → Report a vulnerability** feature on GitHub. A report should include at least:

- The affected version or commit SHA.
- Minimal reproducible steps.
- The actual impact and attack prerequisites.
- Any verified mitigation.
- Logs or screenshots without real credentials or personal data.

Do not continue testing against production data before the maintainers confirm the scope. After receiving a report, the maintainers will assess it as soon as possible, coordinate a disclosure timeline, and provide remediation updates.

## Deployment responsibilities

- Use complete version tags and apply security updates promptly.
- Restrict application access with HTTPS, access controls, and firewall rules.
- Protect `.env` files, GitHub tokens, MCP tokens, data volumes, and backups.
- Never mount the Docker socket into the App.
- Test backup recovery regularly and review audit records and unusual sign-in activity.
- Do not disable MCP private-network and reserved-address protections to work around DNS or proxy errors.
