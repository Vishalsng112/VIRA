# Security policy

## Supported versions

Security fixes are applied to the latest published release and the `main` branch.
Older tags may not receive backports.

## Reporting a vulnerability

Please **do not open a public issue** for a security vulnerability.

Use GitHub’s private vulnerability reporting for this repository:

1. Open the repository’s **Security** tab.
2. Select **Advisories** → **Report a vulnerability**.
3. Include:
   - affected version or commit;
   - deployment mode (Docker, source, OS);
   - reproduction steps or a proof of concept;
   - impact and any known mitigations.

If private reporting is unavailable, contact the maintainer through the GitHub
profile listed on the repository before disclosing publicly.

## What to report

- authentication or session bypass;
- cross-user or cross-device data access;
- credential, token or encryption-key exposure;
- prompt-injection paths that execute tools or exfiltrate data;
- sandbox escape or container misconfiguration;
- SQL injection or read-only database bypass;
- plugin/MCP supply-chain issues;
- backup, restore or update integrity issues.

## What not to report as a vulnerability

- missing features or roadmap items;
- default local-development settings (`auth.https_only: false`) when the server is
  not exposed;
- the documented limits of the Bubblewrap sandbox;
- self-XSS requiring the victim to paste attacker code into their own browser;
- findings that require an already-compromised host or admin account.

## Disclosure

Please allow a reasonable window to investigate and ship a fix before public
disclosure. Credit will be given if requested and if coordinated disclosure is
followed.

## Security documentation

See [the security overview](docs/user/security.md) for implemented controls and
known limitations, the [threat model](docs/dev/security/threat-model.md) for the
engineering analysis, and the
[backup/restore drill](docs/dev/runbooks/backup-restore.md) for recovery evidence.
