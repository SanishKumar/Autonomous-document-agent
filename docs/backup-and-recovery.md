# Backup and recovery

Use the local command from the repository root. No model, cloud service or API key is needed.
Backups contain private document content and password hashes: protect them like the live database.
They are **not encrypted**. Use an access-controlled, encrypted disk; do not commit or email them.

## Create a snapshot

Stop Uvicorn first (Ctrl+C in its terminal). The confirmation flag records your acknowledgement;
it does not detect or stop a running server. SQLite snapshots are consistent, but Word files also
need a quiet workspace while they are copied.

```powershell
.\.venv\Scripts\python.exe -m scripts.workspace_backup create --source outputs --destination backups/manual-01 --server-stopped
.\.venv\Scripts\python.exe -m scripts.workspace_backup verify backups/manual-01
```

Use a new destination name each time. If `OUTPUTS_DIR` is customized, pass that directory as
`--source`. The command snapshots SQLite, copies root Word files and versioned `exports/`, and
records SHA-256 hashes. It excludes `.env`, setup keys, test folders and screenshots. Active
sessions and pending invitations are removed from the snapshot, not from your running database.
Members, password hashes, drafts, versions, discussions and audit records remain in SQLite.

## Restore safely

```powershell
.\.venv\Scripts\python.exe -m scripts.workspace_backup restore backups/manual-01 --destination outputs-restored
```

The destination must not exist. The command validates checksums, file paths and database integrity
before publishing a complete restored directory. Your current outputs directory is untouched.

With the server stopped, set `OUTPUTS_DIR=outputs-restored` in your private `.env`, then restart.
Sign in with your existing account password; all members must sign in again and owners must
recreate any pending invitations. If no owner had been created, startup creates a fresh setup key.
Unfinished generation jobs are marked interrupted by normal startup recovery, not retried.
Model configuration and provider credentials must be supplied separately in `.env`.

Check your document library, versions, discussions and Word export before retiring old storage.
The original synchronous `/agent` Word downloads expect their original output directory; retain
the copied root Word files for those artifacts. Workspace Word exports are generated from snapshots.

## Boundaries

- Checksums detect accidental corruption; they do not authenticate an untrusted backup.
- Restore only backups you trust. Do not edit their manifest or database by hand.
- This is manual local backup, not scheduling, encryption, offsite replication or retention management.
- A backup on the same disk does not protect against loss of that disk. Copy verified backups to
  your own protected storage, outside this repository, when establishing an operational backup policy.
