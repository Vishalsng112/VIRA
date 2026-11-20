# Release process and cadence

VIRA aims for a **monthly release on the first Tuesday** and patch releases as
needed for security or broken installs. The cadence is a target, not a promise
that every month needs a feature release.

## Versioning

- Semantic versioning: `MAJOR.MINOR.PATCH`.
- `vira.__version__` is the source of truth for the server version.
- Git tags are `vX.Y.Z`.
- The client has its own version in `client/pubspec.yaml`; client builds use the
  `Build VIRA Link` workflow and publish checksums.
- Breaking API/config changes require a minor or major bump and a migration note.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/):

- keep an `## [Unreleased]` section at the top;
- add user-visible changes under Added / Changed / Fixed / Security;
- move entries into `## [X.Y.Z] - YYYY-MM-DD` when tagging;
- never rewrite a released section except to correct a factual error.

## Release checklist

1. Confirm the roadmap phase and evaluation results are current.
2. Regenerate the deterministic evaluation:

   ```bash
   python3 scripts/evaluate.py --write
   ```

3. Run release-critical tests:

   ```bash
   python3 -m unittest \
     vira.tests.test_openapi_contract \
     vira.tests.test_security_phase3 \
     vira.tests.test_phase5 \
     vira.tests.test_examples \
     vira.tests.test_database_query \
     vira.tests.test_backup_drill
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

   The `Release` workflow validates the tag/version/changelog, runs
   release-critical tests, creates a source archive, attaches `checksums.txt`
   and publishes the release notes.

8. Publish client builds from the **Build VIRA Link** workflow with
   `create_release` enabled. Verify every artifact and checksum is attached.
9. Announce the release with the demo link, evaluation result and any migration
   steps.

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
