---
title: Releasing
parent: Developer Guide
nav_order: 5
description: "How ScoreSight versions, changelogs, tags and the release workflow fit together."
---

# Releasing
{: .no_toc }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

## Versioning

- The version lives in **one** place: `__version__` in `src/version.py`. The window title, About dialog, update check, PyInstaller spec, Windows installer and release workflow all read it.
- Versions follow `MAJOR.MINOR.PATCH`. Pre-releases use `X.Y.Z-beta.N` or `X.Y.Z-rc.N`. No other formats are accepted. A pre-release comes before its final version: `0.3.0-beta.1` < `0.3.0-rc.1` < `0.3.0`.
- Git tags are the bare version, **without** a `v` prefix (`0.2.0`, `0.2.0-rc.1`), matching the existing tags `0.0.1` to `0.1.0`.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Every user-visible change in a pull request adds a line to the `## [Unreleased]` section under *Added*, *Changed*, *Deprecated*, *Removed*, *Fixed* or *Security*, with the issue number where there is one. Write entries for users, not developers: the section becomes the release notes on GitHub.

## Release checklist

1. **Main is green**: CI passes on `main`, and the docs describe the new behaviour.
2. **Bump the version and changelog** on `main` with `scripts/bump_version.py`:

   ```bash
   python scripts/bump_version.py 0.2.0 --dry-run   # show the changes, write nothing
   python scripts/bump_version.py 0.2.0             # or a pre-release: X.Y.Z-beta.N / X.Y.Z-rc.N
   ```

   It sets `__version__` in `src/version.py`, renames `## [Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] - YYYY-MM-DD` (today, or the date given with `--date YYYY-MM-DD`), adds a new empty `## [Unreleased]` section above it, and updates the comparison links at the bottom. It keeps the file's line endings. If `src/version.py` already holds the new version (as it does for the first 0.2.0 release), only the changelog changes.

   **Pre-releases**: `src/version.py` holds the version in development, so its betas and release candidates can be cut directly. While it says `0.2.0`, `python scripts/bump_version.py 0.2.0-rc.1` sets it to `0.2.0-rc.1` and moves the Unreleased entries to a `## [0.2.0-rc.1]` section. Later changes go into `## [Unreleased]` as usual, and a further pre-release (`0.2.0-rc.2`) needs entries there.

   **The final release** takes over its pre-releases: `python scripts/bump_version.py 0.2.0` folds the `0.2.0` pre-release sections directly below Unreleased, and Unreleased itself (which may then be empty), into one `## [0.2.0]` section, merging their `###` subsections (newest entries first). It removes the pre-releases' comparison links and adds one from the previous final release (`0.1.0...0.2.0`). So the final section, and the release notes, list every change since the previous final release.

   The script refuses a version older than the newest release in `CHANGELOG.md`, a version older than `src/version.py` (other than a pre-release of the same `X.Y.Z`), a version that already has a section, and an empty Unreleased section (except for a final release that takes over pre-release sections).
3. **Review, commit and tag**:

   ```bash
   git commit -am "Release X.Y.Z"
   git tag -a X.Y.Z -m "ScoreSight X.Y.Z"
   git push origin main X.Y.Z
   ```

4. **The release workflow runs** (`.github/workflows/release.yml`, triggered by tags `X.Y.Z`, `X.Y.Z-beta.N` and `X.Y.Z-rc.N`). It:
   - checks that the tag equals `src/version.py` and that `CHANGELOG.md` has a `## [X.Y.Z]` section, and fails otherwise,
   - builds Windows x64, macOS arm64 and Linux x86_64 packages with `build.yml` (signing the Windows app, installer and uninstaller, and signing and notarizing the macOS app and disk images, when the secrets are configured; see [Signing](#signing)),
   - runs the frozen app's `--self-test` on every platform, and on Windows also installs, self-tests and uninstalls the installer,
   - checks that all five packages exist and writes `SHA256SUMS.txt`,
   - creates a **draft** GitHub release named "ScoreSight X.Y.Z" with the packages and `SHA256SUMS.txt` attached. Its notes are this version's section from `CHANGELOG.md`, followed by `.github/release-notes-footer.md`: a downloads table, instructions for verifying the checksums, and an invitation to ScoreSight's Discussions. Beta and rc tags are marked as pre-releases automatically.
5. **QA the draft**: download each package, install it, run through the [Quickstart](../quickstart.md) with a camera or video file, and check at least one output on each platform.
6. **Publish** the draft release on GitHub. Publishing runs `announce-release.yml`, which starts the release's discussion in the **Announcements** category of Discussions, with the release notes, and links it from the release page ("Join discussion"). For a release published before, run it by hand (Actions > Announce release > Run workflow, with the tag); a release that has its discussion keeps it.

If something is wrong, delete the draft and the tag, fix `main`, and tag again.

### Release assets

| File | Platform |
|---|---|
| `scoresight-X.Y.Z-windows-x64-setup.exe` | Windows installer |
| `scoresight-X.Y.Z-windows-x64-portable.zip` | Windows, no installation |
| `scoresight-X.Y.Z-macos-arm64.dmg` | macOS 15+, Apple Silicon |
| `scoresight-X.Y.Z-linux-x64.tar.gz` | Linux x86_64, glibc 2.35+ |
| `SHA256SUMS.txt` | Checksums of the five packages |

The README and the [installation guide](../INSTALL.md) refer to these names. If they change, update both, and `src/app_update.py` (`INSTALLER_NAME`, `SUMS_NAME`): **Update now** finds the Windows installer and its checksum in the release by these names, so a release without them can only be downloaded by hand. Update now runs the new version's installer, so its `[Code]` (the update handshake) must keep working; `scripts/ci/update_test.py` tests it in every Windows build.

## Signing

- **macOS**: signing and notarization run only for release builds, and only when the repository secrets exist: `APPLE_CERTIFICATE` (a base64-encoded Developer ID Application `.p12`), `APPLE_CERTIFICATE_PASSWORD` and `APPLE_APP_DEVELOPER_ID` (the signing identity) for signing, plus `APPLE_DEVELOPER_ID_USER`, `APPLE_DEVELOPER_ID_PASSWORD` (an app-specific password) and `APPLE_DEVELOPER_ID_TEAM` for notarization. Pull request and manual test builds are unsigned.
- **Windows**: release builds sign `scoresight.exe` (before the tests, so the installer and the portable zip contain the signed app), the installer and its uninstaller with [Azure Artifact Signing](https://learn.microsoft.com/azure/artifact-signing/) (formerly Trusted Signing). The signatures are SHA-256 and timestamped, and `scripts/ci/sign_windows.ps1` does the signing. Signing runs only when the repository has the secrets `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET` and the variables `AZURE_SIGNING_ENDPOINT`, `AZURE_SIGNING_ACCOUNT` and `AZURE_SIGNING_PROFILE`. The installer test then checks all three signatures. A release build without them is unsigned, and the run shows a warning. Pull request builds, and manual builds without **Release build** ticked, are unsigned.

### Setting up Windows signing

1. In the Azure portal, open the Artifact Signing account and note three things from it: its endpoint (the **Account URI** on its overview, e.g. `https://eus.codesigning.azure.net/`), the account name and the certificate profile name.
2. In **Microsoft Entra ID** > **App registrations**, register an app (e.g. `scoresight-signing`). Under **Certificates & secrets**, add a client secret.
3. In the Artifact Signing account (or only its certificate profile), open **Access control (IAM)** > **Add role assignment**. Give that app the **Artifact Signing Certificate Profile Signer** role.
4. Store the values in the repository. Each `gh secret set` asks for its value, so it never lands in your shell history:

   ```sh
   gh secret set AZURE_TENANT_ID      # Directory (tenant) ID of the app registration
   gh secret set AZURE_CLIENT_ID      # Application (client) ID
   gh secret set AZURE_CLIENT_SECRET  # the client secret's value
   gh variable set AZURE_SIGNING_ENDPOINT --body https://eus.codesigning.azure.net/
   gh variable set AZURE_SIGNING_ACCOUNT --body <account name>
   gh variable set AZURE_SIGNING_PROFILE --body <certificate profile name>
   ```

5. Test it: **Actions** > **Build** > **Run workflow**, with **Release build** ticked. The Windows job's *Sign the app* step and its installer test print each file's signer.

The client secret expires (after at most 24 months). Before it does, add a new one and run `gh secret set AZURE_CLIENT_SECRET` again.

To sign a file on your own machine, run `az login` with an account that has the signer role. Set the three `AZURE_SIGNING_*` environment variables, then run `pwsh scripts/ci/sign_windows.ps1 <file>`.

A signed download can still get SmartScreen's "Windows protected your PC" warning. Windows builds a publisher's reputation from downloads, and later releases signed by the same publisher benefit from it. So the first signed releases may still warn. Until releases stop warning, keep the SmartScreen instructions in the [installation guide](../INSTALL.md#windows). Releases are signed from 0.3.2 on.

## After the release

- Make sure the GitHub Pages docs (built from `docs/` on `main`) describe the released version.
- Reply on the issues fixed in the release, and close them.
