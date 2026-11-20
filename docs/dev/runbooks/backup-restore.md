# Backup and restore drill

Checked: 2026-11-20T19:01:32.229105+00:00

## Result

- Status: **PASS**
- Source: `data/vira.sqlite3`
- Backup: `data/backups/vira-20261120-190132.sqlite3`
- Integrity check: `ok`
- Tables/rows restored: 53 / 7968
- Missing tables: none
- Row-count mismatches: none

## Recovery objectives

- **RPO target:** 24 hours. The worker schedules a
  database backup every 24 hours (`jobs.backup_keep` controls retention).
- **Previous backup age at drill time:** none yet; this drill establishes the first restore point.
- **Measured RTO for this drill:** 0.014 seconds
  (copy + open + integrity check, excluding container startup and DNS).

## What this proves

The backup is a consistent database image and it can be copied and opened
independently of the live server. Row counts are compared with the live
database; a serving instance may have accepted writes since the backup, so
treat mismatches as informational and run the drill on an idle instance for
a strict count comparison.

It does **not** prove that the master key is backed up. Without
`data/.vira_master_key` (or `VIRA_MASTER_KEY`), encrypted fields cannot be
recovered. Back up the key separately.

