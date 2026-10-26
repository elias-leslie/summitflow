# Cold recovery from Google Drive

Use this when the SummitFlow API and database, GitHub and the original host are
all unavailable and you need files back from the Drive backup. It needs only
`restic` and `rclone`; nothing here calls SummitFlow. It never restores over a
live path. For a whole replacement host, continue with the
[hard-loss runbook](disaster-recovery.md). When SummitFlow is running, `st backup
restore PROJECT --to DIR` does the same restore in one command.

## What the Drive repository holds

One restic repository, written once a day. Every snapshot has the tag `offsite`
and a `job:` tag:

| Job | What it holds | Paths in the snapshot |
| --- | --- | --- |
| `workspaces` | `/srv/workspaces`, also tagged `project:<name>` for every folder under `projects/` | real paths, like `/srv/workspaces/projects/aico` |
| `home` | `/home` | real paths |
| `root` | `/etc`, `/root`, `/opt`, `/usr/local`, `/var/spool` | real paths |
| `postgres` | a full `pg_dumpall` | one file, `/postgres-dumpall.sql` |
| `redis` | the Redis RDB | one file, `/redis-dump.rdb` |
| `pve-*` and similar | Proxmox guests and files | named by the job |

The subvolume jobs also carry `btrbk:<run>`, the btrbk run whose snapshots were
read. Dependencies, build output and caches are left out (see
`backend/app/tasks/backup_offsite.excludes`). Snapshots older than the
7 daily, 4 weekly and 3 monthly ones are removed. A project comes back by its
real path, and a restored project is the folder as it was on that day, `.git`
included.

## Required material

- The repository locator, like `rclone:<remote>:<folder>`. While SummitFlow runs,
  `st backup status --json` shows it as `offsite.repository`; keep a copy with
  the other recovery material.
- The restic repository password file and the dedicated rclone configuration.
  Take them from the owner's offline custody. A copy inside the backup does not
  help: it is encrypted with that same password. Both must be regular files owned by the recovery user, mode
  `0600`, at absolute paths without symlinks. Put file paths on the command
  line, never their contents.
- Linux with `restic` 0.19.1 and `rclone` 1.75.1, verified against the published
  checksums and signatures. Git, only to inspect a recovered project.
- A private, empty destination with room for what you restore.

Drive sign-in through the desktop (GOA/GVfs) does not work here. If Google
rejects the saved rclone authorization, run `scripts/authorize-backup-drive.sh`
and complete consent privately.

```bash
export RESTIC_REPOSITORY='rclone:<remote>:<folder>'
export RESTIC_PASSWORD_FILE=/secure/offline/restic-drive.password
export RCLONE_CONFIG=/secure/offline/restic-rclone.conf
```

## Pick a snapshot

```bash
restic snapshots --tag offsite,job:workspaces
restic snapshots --tag offsite,job:workspaces,project:aico
restic snapshots --tag offsite,job:postgres
```

Take the newest snapshot of the job unless you need an older day, and write down
its full ID, time and paths. Snapshots from before the daily job (tag
`source:<name>`, no `offsite`) are old per-project backups that age out on their
own; leave them unless you need data only they hold (`st backup old list`).

A structure check does not read every pack:

```bash
restic check
restic check --read-data-subset 500M
```

The weekly verify job (`python -m app.tasks.backup_verify`) reads a random 500 MB
sample each Sunday, within a time limit. A full `restic check --read-data` downloads everything;
run it only when you must.

## Restore a project or path

Restore into a new empty directory. Restic rebuilds the snapshot's real paths
below it, so `--include` takes the original path:

```bash
umask 077
mkdir -m 700 -p /srv/recovery/aico
restic restore <snapshot-id> --target /srv/recovery/aico \
  --include /srv/workspaces/projects/aico --verify
```

The project is then at `/srv/recovery/aico/srv/workspaces/projects/aico`.
`--verify` reads the restored files back. Inspect before using them:

```bash
git -C /srv/recovery/aico/srv/workspaces/projects/aico fsck --full
git -C /srv/recovery/aico/srv/workspaces/projects/aico status --short --branch
```

The snapshot was taken from a frozen btrbk snapshot, so the tree is consistent
as of that moment, including unpublished commits, staged changes and untracked
work. Nothing here resets, cleans or commits it.

## Restore the databases

```bash
restic dump <postgres-snapshot-id> /postgres-dumpall.sql > /srv/recovery/postgres-dumpall.sql
restic dump <redis-snapshot-id> /redis-dump.rdb > /srv/recovery/redis-dump.rdb
tail -n 3 /srv/recovery/postgres-dumpall.sql   # ends with "PostgreSQL database cluster dump complete"
head -c 5 /srv/recovery/redis-dump.rdb          # REDIS
```

A dump without its trailer is a failed restore, not a smaller one. Loading either
dump into a fresh volume is in sections 5 and 6 of the
[hard-loss runbook](disaster-recovery.md#5-restore-postgresql-into-a-provably-new-pg16-volume);
the commands above only get the files back.

## Record what you did

Note the snapshot IDs and times, the `restic check` result, restored byte counts,
and the Git checks. File extraction alone does not prove that an application
recovers: that needs the PostgreSQL and Redis loads and the rebuild in the
hard-loss runbook. Leave plaintext cleanup (`/srv/recovery`) for after a new
backup cycle has run on the replacement.
