# Release process and cadence

VIRA targets a **monthly release on the first Tuesday**, with patch releases as
needed for security or broken installs. The cadence is a target, not a promise
that every month needs a feature release.

## Versioning

- Semantic versioning: `MAJOR.MINOR.PATCH`.
- Server tags: `vX.Y.Z` (for example `v0.5.0`).
- Server prereleases: `vX.Y.Z-rc.N` (for example `v0.5.0-rc.1`).
- Client tags: `vira-link-vX.Y.Z` (for example `vira-link-v1.2.0`).
- Do not put build numbers in public tags. Rebuilds use a new patch version.
- `vira.__version__` is the server source of truth.
- `client/pubspec.yaml` is the client source of truth.
- Breaking API/config changes require a minor or major bump and a migration note.

The release workflows use different tag prefixes so a client release cannot
trigger the server workflow.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/):

- keep an `## [Unreleased]` section at the top;
- add user-visible changes under Added / Changed / Fixed / Security;
- move entries into `## [X.Y.Z] - YYYY-MM-DD` when tagging;
- never rewrite a released section except to correct a factual error.

## Release assets

Server releases:

```text
vira-X.Y.Z-source.tar.gz
vira-X.Y.Z-checksums.txt
vira-X.Y.Z-release-manifest.json
```

Client releases:

```text
vira-link-X.Y.Z-android.apk
vira-link-X.Y.Z-ios-unsigned.zip
vira-link-X.Y.Z-web.zip
vira-link-X.Y.Z-linux-x86_64.AppImage
vira-link-X.Y.Z-windows-x64.zip
vira-link-X.Y.Z-macos-arm64.zip
vira-link-X.Y.Z-checksums.txt
```

Asset names are lowercase, versioned and stable. The release workflow verifies
that every expected artifact exists before publishing.

## Release checklist

1. Confirm the roadmap phase and evaluation results are current.
2. Regenerate the deterministic evaluation:

   ```bash
   python3 scripts/evaluate.py --write
   ```

3. Run the full backend suite:

   ```bash
   python3 -m unittest discover -s vira/tests -q
   ```

4. Run `python3 -m vira doctor` against a clean install.
5. Update `CHANGELOG.md`, `vira.__version__`, docs and the security page.
6. Validate the release locally:

   ```bash
   python3 scripts/release_tools.py check vX.Y.Z
   python3 scripts/release_tools.py notes vX.Y.Z
   ```

7. Commit, tag and push:

   ```bash
   git tag -a vX.Y.Z -m "VIRA X.Y.Z"
   git push origin vX.Y.Z
   ```

   The `Release` workflow validates the tag/version/changelog, runs the full
   suite, builds the source archive and checksums, generates release notes from
   the standard template and publishes the GitHub release.

8. For VIRA Link, run **Build VIRA Link** with the client version, verify every
   platform artifact and checksums, then enable `create_release`.
9. Announce the release with the demo link, evaluation result and any migration
   steps.

## Release tool commands

```bash
# Validate a server or client tag
python3 scripts/release_tools.py check vX.Y.Z
python3 scripts/release_tools.py check vira-link-vX.Y.Z --product client

# Preview the standard release body
python3 scripts/release_tools.py notes vX.Y.Z
python3 scripts/release_tools.py notes vira-link-vX.Y.Z --product client --dist dist

# Verify assets and write the checksum file
python3 scripts/release_tools.py assets vX.Y.Z --dist dist --write-checksums

# Machine-readable release manifest
python3 scripts/release_tools.py manifest vX.Y.Z --dist dist
```

## Hotfixes

For a security or install-blocking bug:

1. branch from the released tag;
2. bump PATCH and add a `### Security` or `### Fixed` entry;
3. run the same checklist;
4. tag and publish;
5. backport to `main` if `main` has moved on.

## Decision log

Architecture and product decisions are recorded in
[the decision log](decision-log.md). A release should link any decision that
changed public behaviour.

## Response targets

- Security reports: private triage within **2 business days**.
- Bugs and install failures: initial response within **3 business days**.
- Good first issues and feature proposals: initial response within **5 business
  days**.
- Releases: monthly target, with a written note when a month is skipped.

These are targets, not contractual SLAs.
