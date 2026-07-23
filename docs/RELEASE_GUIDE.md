# Apervia Update and Release Guide

This guide explains how to change the code, write update notes, publish to GitHub, build images, and upgrade a deployment.

## 1. Change categories

Choose one primary category for each change:

- **Feature**: Users receive a new capability or workflow.
- **Fix**: Incorrect behavior is corrected.
- **Adjustment**: Existing behavior, interface, or defaults change.
- **Security**: Permissions, credentials, isolation, dependency vulnerabilities, or exposure change.
- **Documentation**: Only guides, screenshots, or explanations change.
- **Dependency**: A base image, Python package, or GitHub Actions version changes.

Keep one pull request focused on one clear topic. Do not mix unrelated formatting, refactoring, and features.

## 2. Writing update notes

Update `[Unreleased]` in `CHANGELOG.md` first. Describe outcomes that users can understand:

```markdown
### Added

- Add an administrator backup page for creating and verifying platform-state backups.

### Fixed

- Correct the SearXNG host-access instructions for Docker containers.

### Security

- Add nonce replay protection to Sandbox Runner requests.
```

Do not describe internal processes such as changing a variable or spending time debugging. Explain who is affected, how behavior changes, whether configuration must change, and whether migration or restart is required.

The pull request's release notes should include at least:

- Change type.
- User impact.
- Upgrade notes.
- Rollback procedure.

## 3. Creating a branch and commit

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/short-description
```

After implementing and verifying the change, stage only the related files:

```bash
git status -sb
git diff --check
git add -- path/to/file1 path/to/file2
git commit -m "Describe the update concisely"
git push -u origin feature/short-description
```

Do not use `git add -A` if it might include `.env`, databases, logs, uploads, or local work records.

## 4. Creating a pull request

```bash
gh pr create --draft --base main --fill
```

Complete the change summary, release notes, verification results, data impact, and screenshots. After `verify` succeeds:

```bash
gh pr ready
gh pr merge --squash --delete-branch
```

If branch protection is enabled, satisfy all required checks and reviews. If the current private-repository plan does not support branch protection, continue using pull requests instead of pushing feature changes directly to `main`.

## 5. GitHub Actions behavior

Pull requests and pushes to `main` run only:

- Action workflow syntax checks.
- Docker and identity contract tests.
- Both Compose profile checks.
- Syntax checks for every frontend JavaScript file.

Formal version tags build and publish in parallel:

- `ghcr.io/wdyh1314520-gif/apervia-open-source` for amd64 and arm64.
- `ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox` for amd64 and arm64.

The App is started and checked for health, non-root execution, Playwright, LibreOffice, and data-volume recreation. The Sandbox runs its quick probe with networking disabled, a read-only root filesystem, and minimal privileges. Multi-architecture manifests are created only after all four platform builds succeed.

Keeping image publication on formal tags prevents the same App and Sandbox images from being built once for `main` and again for the version tag. To run an explicit image build outside a formal release, use `workflow_dispatch` from the Actions page.

## 6. Publishing a formal version

Before preparing a release:

1. Update the root `VERSION` file. The current formal version is `1.0.0`.
2. Move `[Unreleased]` content into `## [1.0.0] - 2026-07-23`.
3. Update `release/announcement.md`; its `id` must be `v1.0.0` and its `version` must be `1.0.0`.
4. Run the tests and confirm that the version file, changelog, and project announcement agree.
5. Merge the change and wait for `main` verification, then create an annotated tag:

```bash
git switch main
git pull --ff-only origin main
git tag -a v1.0.0 -m "Apervia 1.0.0"
git push origin v1.0.0
```

The tag publishes these image tags:

```text
ghcr.io/wdyh1314520-gif/apervia-open-source:latest
ghcr.io/wdyh1314520-gif/apervia-open-source:1.0.0
ghcr.io/wdyh1314520-gif/apervia-open-source:1.0
ghcr.io/wdyh1314520-gif/apervia-open-source:sha-<commit>
ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox:latest
ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox:1.0.0
ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox:1.0
ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox:sha-<commit>
```

After the image workflow succeeds, create the GitHub Release:

```bash
gh release create v1.0.0 --title "Apervia 1.0.0" --notes-file release/announcement.md
```

`VERSION` is the single source of truth for the project version. Git tags include the `v` prefix, while Docker image tags use the bare version. Before publishing, verify `VERSION`, `CHANGELOG.md`, `release/announcement.md`, and the tag again.

## 7. Publishing update content inside the website

The website announcement is a project release asset, not content edited manually by an instance administrator. Its single source is `release/announcement.md`, which is included in the App image. After a deployment upgrades to the new image, users see the corresponding announcement after sign-in.

Recommended structure:

```markdown
## What's new

- **Added**: Describe the new capability and entry point.
- **Improved**: Describe a user-visible change to an existing workflow.
- **Fixed**: Describe the problem and the corrected result.

## Usage notes

- Closing the announcement does not mark it as read. The acknowledgement is saved only after selecting **Got it**.
```

Writing rules:

- **Announcement ID**: `v` plus `VERSION`; currently `v1.0.0`.
- **Version**: Exactly match the root `VERSION`; currently `1.0.0`.
- **Category**: Use `update`, or `security` for a security release.
- **Publication date**: Use the actual public release date.
- **Title**: Describe the outcome, not internal function names, debugging steps, or commit hashes.
- **Body**: Prioritize additions, improvements, fixes, and any action required from users.

The announcement body is not written to the runtime database. The database stores only `user_id`, `release_id`, and the acknowledgement time. To change a formal announcement, publish a new version through a pull request, tests, tag, GitHub Release, and image workflow. Never replace announcement content silently under an existing version number.

## 8. Updating a deployment

Pin complete versions in production instead of following `latest` indefinitely:

```dotenv
APP_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source:1.0.0
SANDBOX_DOCKER_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox:1.0.0
```

Back up the data volume before upgrading, and then run:

```bash
docker compose --profile sandbox pull app sandbox-runner
docker compose --profile sandbox up -d --force-recreate app sandbox-runner
docker compose ps
curl --fail http://127.0.0.1:8002/api3/health/ready
```

Confirm the version and SHA from the health endpoint, and then verify sign-in, conversations, files, knowledge bases, MCP, and sandbox execution.

## 9. Rollback

1. Change both App and Sandbox references in `.env` to the previous complete version.
2. Pull the images and force-recreate the containers.
3. If the new version included a data migration, restore the pre-upgrade data-volume backup according to the release notes.

Rolling back an image does not roll back the database format. Do not roll back only the App while continuing to use a mismatched Sandbox version.

## 10. Emergency fixes

Create a dedicated branch from the latest `main` even for an emergency. Include only the minimum fix and its regression test. After merging, verify the `sha-<commit>` image before deciding whether to publish a patch version, such as `1.0.1` after `1.0.0`. Never overwrite an existing release tag.
