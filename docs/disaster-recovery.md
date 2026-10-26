# SummitFlow hard-loss recovery

Use this runbook when the original computer and its disks are unavailable. It
recovers SummitFlow from the daily restic repository in Google Drive, using the
repository password and rclone configuration the owner holds separately. The T7
btrbk points are local only; they are gone with the host, and the
[host recovery guide](native-host-recovery.md) covers them. Getting individual
files back without a replacement host is in [cold recovery from
Drive](local-first-recovery.md).

This is not an operating-system image. It does not recreate Linux packages,
users, groups, device configuration, Google Online Accounts, package caches, or
container-image caches. It also does not make an existing database safe to
overwrite. The database procedure below deliberately refuses to use an existing
Docker volume.

## What must still exist

- The restic repository locator (`rclone:<remote>:<folder>`), the repository
  password file and the dedicated rclone configuration, in the owner's offline
  custody. A copy inside the backup is encrypted with the same password and
  cannot open it.
- The Google account behind the Drive remote, with its OAuth client. If Google
  rejects the saved authorization, run `scripts/authorize-backup-drive.sh` and
  complete consent privately. Desktop Online Accounts sign-in is not used.
- A compatible Linux host with `restic` 0.19.1, `rclone` 1.75.1, Git, Python 3.13
  or newer, `uv`, Docker Engine with Compose v2, and Node/corepack/pnpm for
  application rebuilds; plus private disk space for the restored trees and
  database volumes.

The restored source needs no GitHub account. Rebuilding still needs the public
Linux, Python, npm, and container registries named by the lockfiles and Compose
configuration unless their artifacts are already cached.

## 1. Open the repository and choose snapshots

Work on a private local disk, with credentials only as file references:

```bash
umask 077
mkdir -p /srv/recovery/restored /srv/recovery/dumps
export RESTIC_REPOSITORY='rclone:<remote>:<folder>'
export RESTIC_PASSWORD_FILE=/secure/offline/restic-drive.password
export RCLONE_CONFIG=/secure/offline/restic-rclone.conf
restic snapshots --tag offsite
restic check
```

Pick the newest snapshot of each job you need: `workspaces`, `home`, `root`,
`postgres`, `redis`, and any `pve-*` job. Record each full ID, time and the
`btrbk:` tag. A job whose newest snapshot is old is a recovery limitation to
write down, not to ignore. The tags and the 7 daily, 4 weekly and 3 monthly
retention are described in [cold recovery](local-first-recovery.md). Do not edit
or delete anything in the repository during recovery.

## 2. Restore the trees into staging

Restore into new directories, never over a live path. The snapshot keeps real
paths, so each tree appears under its original path inside the staging directory:

```bash
restic restore <workspaces-snapshot-id> --target /srv/recovery/restored \
  --include /srv/workspaces/projects/summitflow --verify
restic restore <root-snapshot-id> --target /srv/recovery/restored-root --include /etc --verify
restic restore <home-snapshot-id> --target /srv/recovery/restored-home --verify \
  --include /home/<user>/.env.local --include /home/<user>/.config \
  --include /home/<user>/.local/state
RECOVERY_ROOT=/srv/recovery/restored-root
RECOVERY_HOME=/srv/recovery/restored-home/home/<user>
```

Use the whole `home` job instead of the three includes if you want the entire
home directory. Move the SummitFlow checkout to its final path and inspect it:

```bash
mkdir -p /srv/workspaces/projects
mv /srv/recovery/restored/srv/workspaces/projects/summitflow /srv/workspaces/projects/summitflow
git -C /srv/workspaces/projects/summitflow fsck --full
git -C /srv/workspaces/projects/summitflow status --short --branch
```

The tree is a consistent btrbk snapshot taken at the recorded time. It holds
committed history, unpublished refs, the staged index, working files, and the
durable data under the project including `data/design-studio/mockups`. Preserve
that state. Do not clean, reset, or look for obsolete `/tmp/summitflow/mockups`
state. `docker/workspace-packages` supplies the local wheels and tarballs named by
`backend/pyproject.toml` and `pnpm-lock.yaml`; check they are present. Then build
the backend environment:

```bash
cd /srv/workspaces/projects/summitflow/backend
uv sync --frozen
ST_DEV_CHECKOUT=1 st --help
```

Restore every other project the same way (add one `--include` per project, or
`--include /srv/workspaces/projects`), then compare the folders with the
database after step 5. If the replacement user or paths differ, decide the final
layout now and correct host-specific paths in the recovered environment files,
service units, and project records before enabling automation.

## 3. Get the database dumps

```bash
restic dump <postgres-snapshot-id> /postgres-dumpall.sql > /srv/recovery/dumps/postgres-dumpall.sql
restic dump <redis-snapshot-id> /redis-dump.rdb > /srv/recovery/dumps/redis-dump.rdb
RECOVERY_DUMPS=/srv/recovery/dumps
tail -n 3 "$RECOVERY_DUMPS/postgres-dumpall.sql"   # must end with the cluster dump complete line
test "$(head -c 5 "$RECOVERY_DUMPS/redis-dump.rdb")" = REDIS
```

A dump without its trailer, or an empty one, is a failed restore.

## 4. Put configuration in place while services are stopped

Do **not** run `docker/install.sh`: it generates new passwords and starts a
normally initialized database, both of which conflict with this restore.

```bash
RECOVERY_COMPOSE=/srv/workspaces/projects/summitflow/docker/compose
RECOVERY_COMPOSE_ENV="$HOME/.config/credstore/summitflow/compose.env"
```

Install the recovered files before starting Compose:

- `$RECOVERY_HOME/.config/credstore/summitflow/compose.env` to
  `~/.config/credstore/summitflow/compose.env`, mode `0600`. It holds the
  database and application secrets that match the dump; do not replace them.
  Review and update only host-specific values such as `HOST_HOME_PATH`,
  `DOCKER_GID`, device paths and obsolete SMB locations.
- Hatchet configuration is already in the restored checkout, at
  `docker/compose/hatchet-config/`. It must be present before
  `hatchet-setup-config` runs; its Compose command is intentionally
  `--overwrite=false`.
- `$RECOVERY_HOME/.env.local` to `~/.env.local`, mode `0600`, and
  `$RECOVERY_HOME/.local/state/agent-hub/` to `~/.local/state/agent-hub/`,
  preserving modes.
- `$RECOVERY_HOME/.local/state/summitflow/backup-keys/` to the same path, plus the
  restic password file and rclone configuration from custody (section 9).
- `$RECOVERY_ROOT/etc/btrbk/summitflow.conf` to `/etc/btrbk/summitflow.conf`,
  once the new T7 target exists (see the host recovery guide).

Keep user services disabled. Copy the regular unit files from
`$RECOVERY_HOME/.config/systemd/user/` to `~/.config/systemd/user/`, but review
their absolute paths first, and note which units were enabled (the `*.wants`
links in the same tree). Re-enable those unit names through `systemctl --user
enable <unit>` only after their executables and working directories exist. Do not
blindly recreate arbitrary symlink targets.

Old managed-release build trees are not backup contents. Release receipts and job
records under `~/.local/state` are audit evidence only: retain them without
resubmitting jobs, and do not recreate old transient `sf-rebuild-*` jobs. New
releases are built from the recovered project sources in step 7.

## 5. Restore PostgreSQL into a provably new PG16 volume

The production dump (`postgres-dumpall.sql`) is a full `pg_dumpall`: it contains roles and databases.
Normal first startup of this repository's Compose service also creates the
`admin` role and application databases through `init-db.sh`, so restoring the
dump after normal startup would collide with them.

The following sequence creates the exact volume name used by Compose, starts a
temporary PG16 container **without** the repository init script, and restores as
the image's bootstrap `postgres` role. It refuses any pre-existing Compose
container or volume.

First, stop and investigate if either preflight produces output or succeeds:

```bash
RECOVERY_PG_VOLUME=summitflow-stack_pgdata
RECOVERY_PG_CONTAINER=summitflow-recovery-pg16

test -z "$(docker ps -aq --filter label=com.docker.compose.project=summitflow-stack)" || {
  echo "REFUSING: summitflow-stack containers already exist" >&2
  exit 1
}
if docker volume inspect "$RECOVERY_PG_VOLUME" >/dev/null 2>&1; then
  echo "REFUSING: $RECOVERY_PG_VOLUME already exists" >&2
  exit 1
fi
if docker container inspect "$RECOVERY_PG_CONTAINER" >/dev/null 2>&1; then
  echo "REFUSING: $RECOVERY_PG_CONTAINER already exists" >&2
  exit 1
fi
```

Create and initialize only that new volume:

```bash
docker volume create --label summitflow.recovery=fresh "$RECOVERY_PG_VOLUME"
set +x
POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export POSTGRES_PASSWORD
docker run --detach \
  --name "$RECOVERY_PG_CONTAINER" \
  --env POSTGRES_PASSWORD \
  --volume "$RECOVERY_PG_VOLUME:/var/lib/postgresql/data" \
  pgvector/pgvector:pg16
unset POSTGRES_PASSWORD
```

Wait until `docker exec "$RECOVERY_PG_CONTAINER" pg_isready -U postgres`
succeeds. Check the dump ends with its trailer line (section 3), then restore with pipeline failure
propagation enabled:

```bash
set -o pipefail
sed -e '/^CREATE ROLE postgres;$/d' -e '/^ALTER ROLE postgres /d' \
      "$RECOVERY_DUMPS/postgres-dumpall.sql" \
  | docker exec --interactive "$RECOVERY_PG_CONTAINER" \
      psql -v ON_ERROR_STOP=1 -U postgres -d postgres
```

Only the temporary image-created `postgres` role statements are omitted. All
captured application roles, databases, schema, and data still come from the
dump. A nonzero pipeline status is a failed restore: do not start Compose or
silently rerun against the same volume.

Confirm that expected databases and the restored `admin` role exist, without
printing role passwords:

```bash
docker exec "$RECOVERY_PG_CONTAINER" \
  psql -U postgres -d postgres -tAc \
  "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
docker exec "$RECOVERY_PG_CONTAINER" \
  psql -U postgres -d postgres -tAc \
  "SELECT rolname FROM pg_roles WHERE rolname IN ('admin','summitflow_app','agent_hub_app') ORDER BY rolname"
```

The actual deployment uses `admin`, not the temporary bootstrap login. Disable
that bootstrap login and stop the temporary container, leaving the restored
volume intact:

```bash
docker exec "$RECOVERY_PG_CONTAINER" \
  psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
  -c "ALTER ROLE postgres NOLOGIN PASSWORD NULL"
docker stop "$RECOVERY_PG_CONTAINER"
docker rm "$RECOVERY_PG_CONTAINER"
```

If restore validation failed, preserve the logs and dump. Remove or replace the
explicit failed recovery volume only after an operator confirms that it contains
no wanted data. Never adapt this procedure to an existing volume.

## 6. Restore Redis into a provably new volume

Redis uses `summitflow-stack_redis-data` and reads `/data/dump.rdb`. Refuse a
pre-existing volume, then copy the validated RDB before Redis first starts:

```bash
RECOVERY_REDIS_VOLUME=summitflow-stack_redis-data
if docker volume inspect "$RECOVERY_REDIS_VOLUME" >/dev/null 2>&1; then
  echo "REFUSING: $RECOVERY_REDIS_VOLUME already exists" >&2
  exit 1
fi
test "$(head -c 5 "$RECOVERY_DUMPS/redis-dump.rdb")" = REDIS
docker volume create --label summitflow.recovery=fresh "$RECOVERY_REDIS_VOLUME"
docker run --rm --user 0 \
  --volume "$RECOVERY_REDIS_VOLUME:/data" \
  --volume "$RECOVERY_DUMPS/redis-dump.rdb:/recovery/dump.rdb:ro" \
  redis:7-bookworm sh -euc '
    test -z "$(find /data -mindepth 1 -maxdepth 1 -print -quit)"
    cp /recovery/dump.rdb /data/dump.rdb
    chown redis:redis /data/dump.rdb
    chmod 600 /data/dump.rdb
  '
```

Do not start a second Redis against this volume. The checked-in Redis config
enables AOF. Redis 7 does **not** load the standalone `dump.rdb` on a normal
AOF-enabled first start; it creates an empty AOF which then wins. Convert the
recovered RDB before any normal Compose startup.

Start one network-isolated bootstrap container with AOF temporarily disabled:

```bash
RECOVERY_REDIS_CONTAINER=summitflow-recovery-redis7
if docker container inspect "$RECOVERY_REDIS_CONTAINER" >/dev/null 2>&1; then
  echo "REFUSING: $RECOVERY_REDIS_CONTAINER already exists" >&2
  exit 1
fi
docker run --detach \
  --name "$RECOVERY_REDIS_CONTAINER" \
  --network none \
  --volume "$RECOVERY_REDIS_VOLUME:/data" \
  --volume "$RECOVERY_COMPOSE/redis.conf:/usr/local/etc/redis/redis.conf:ro" \
  redis:7-bookworm \
  redis-server /usr/local/etc/redis/redis.conf --appendonly no
```

Use `docker exec "$RECOVERY_REDIS_CONTAINER" redis-cli -n <db> DBSIZE` to
review DBs 0, 1, and 2 before conversion. Require the expected recovered state;
an empty result is a failed restore, not permission to continue.

Enable AOF on the live bootstrap process, then wait for a completed successful
rewrite and the Redis 7 multipart manifest:

```bash
docker exec "$RECOVERY_REDIS_CONTAINER" redis-cli CONFIG SET appendonly yes
for RECOVERY_REDIS_ATTEMPT in $(seq 1 120); do
  RECOVERY_REDIS_INFO="$(docker exec "$RECOVERY_REDIS_CONTAINER" redis-cli INFO persistence | tr -d '\r')"
  if grep -q '^aof_enabled:1$' <<<"$RECOVERY_REDIS_INFO" \
     && grep -q '^aof_rewrite_in_progress:0$' <<<"$RECOVERY_REDIS_INFO" \
     && grep -q '^aof_rewrite_scheduled:0$' <<<"$RECOVERY_REDIS_INFO" \
     && grep -q '^aof_last_bgrewrite_status:ok$' <<<"$RECOVERY_REDIS_INFO" \
     && docker exec "$RECOVERY_REDIS_CONTAINER" \
          test -f /data/appendonlydir/appendonly.aof.manifest; then
    break
  fi
  sleep 1
done
RECOVERY_REDIS_INFO="$(docker exec "$RECOVERY_REDIS_CONTAINER" redis-cli INFO persistence | tr -d '\r')"
grep -q '^aof_enabled:1$' <<<"$RECOVERY_REDIS_INFO"
grep -q '^aof_rewrite_in_progress:0$' <<<"$RECOVERY_REDIS_INFO"
grep -q '^aof_rewrite_scheduled:0$' <<<"$RECOVERY_REDIS_INFO"
grep -q '^aof_last_bgrewrite_status:ok$' <<<"$RECOVERY_REDIS_INFO"
docker exec "$RECOVERY_REDIS_CONTAINER" \
  test -f /data/appendonlydir/appendonly.aof.manifest
unset RECOVERY_REDIS_INFO RECOVERY_REDIS_ATTEMPT
```

Recheck DBs 0, 1, and 2, then stop gracefully and remove only the temporary
container. Do not delete the RDB; normal Redis startup will prefer the newly
created AOF.

```bash
docker exec "$RECOVERY_REDIS_CONTAINER" redis-cli SHUTDOWN NOSAVE
docker wait "$RECOVERY_REDIS_CONTAINER" >/dev/null
docker rm "$RECOVERY_REDIS_CONTAINER"
```

## 7. Start infrastructure, then rebuild managed applications

From the recovered Compose directory, start PostgreSQL, Redis, and the socket
proxy first:

```bash
cd "$RECOVERY_COMPOSE"
docker compose --env-file "$RECOVERY_COMPOSE_ENV" --profile infra up -d postgres redis docker-socket-proxy
docker compose --env-file "$RECOVERY_COMPOSE_ENV" ps
```

Verify PostgreSQL and authenticated Redis health. Then start Hatchet. Because
both its database and configuration were restored, do not regenerate either:

```bash
docker compose --env-file "$RECOVERY_COMPOSE_ENV" --profile infra up -d hatchet-migrate hatchet-setup-config hatchet
docker compose --env-file "$RECOVERY_COMPOSE_ENV" ps
```

Review Hatchet migration output and require its ready endpoint before starting
workers. A mismatched or unavailable `HATCHET_TAG` is a registry/version problem,
not permission to regenerate Hatchet state.

Before a SummitFlow worker starts, query `projects.root_path` in the restored
`summitflow` database and correct each stale old-host path to the corresponding
recovered checkout. Put the restic password file and rclone configuration where
the restored `storage_backends` row names them (section 9). Also review the
recovered per-project `agent_configs` and leave scheduled actions disabled until
final validation. Do not start a worker merely to use the UI to repair these
prerequisites.

For each restored managed project, preserve its WIP and first identify the
commit that should run. A managed release accepts a clean Git commit; it does not
deploy uncommitted recovery files. Run full local acceptance for that chosen
commit and use the resulting receipt for the rebuild:

```bash
cd /srv/workspaces/projects/<project>
st check --acceptance --sha <reviewed-commit>
st service rebuild <project-id> --acceptance <acceptance-receipt-path>
```

Repeat for SummitFlow, Agent Hub, and each application/worker required on this
host. This creates new release trees and new `current` pointers. Do not point at
the old build IDs from the infrastructure manifest: those source trees were not
backup contents. A full SummitFlow rebuild starts its declared default Hatchet
worker; therefore it must not run until the source-path reconciliation, the
backup key files and the automation review above are complete.

After builds and local health checks succeed, reload the reviewed user units,
enable only the units recorded as enabled, and start them in dependency order:

```bash
systemctl --user daemon-reload
systemctl --user enable <reviewed-unit-name>
systemctl --user start <reviewed-unit-name>
```

The checked-in `scripts/install-host-infra.sh` can recreate SummitFlow's
backup write-window units, the host backup timer, btrbk log rotation, Docker log
limits, and the infrastructure reconcile unit. Host checks and maintenance are
restored with Nightshift. Review its hard-coded paths and effects before running
it with sudo; it is not a restore.

## 8. Restore ingress last

Do not expose services until their local health checks and owner flows work.
Install Caddy and cloudflared from their normal public package sources, but keep
their services stopped. The `root` job holds `/etc`, so their configuration and
secret files are in the snapshot you restored into `$RECOVERY_ROOT` (section 2):

- install `$RECOVERY_ROOT/etc/caddy/Caddyfile` as `/etc/caddy/Caddyfile` and
  `$RECOVERY_ROOT/etc/cloudflared/config.yml` as `/etc/cloudflared/config.yml`;
- install the two host secrets, `/etc/caddy/env` and the tunnel credential file
  that `config.yml` names, from the same tree, root-owned, mode 600, with no ACLs
  for other users; and
- if either secret is not in the snapshot, re-issue it. For the tunnel
  credential, run
  `sudo cloudflared tunnel token --cred-file <path named in config.yml> <tunnel>`
  after `cloudflared tunnel login` (or create a new tunnel and point
  `config.yml` at it). For `/etc/caddy/env`, create a Cloudflare API token
  limited to Zone DNS edit on the served zone and write it as
  `CLOUDFLARE_API_TOKEN=<token>`.

POSIX ACLs, xattrs, numeric ownership policy, and system-level unit enablement
are not fully reconstructed by a restore.

Validate configurations before starting either service:

```bash
sudo cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
sudo caddy validate --config /etc/caddy/Caddyfile
```

Start Caddy and cloudflared only after local API and UI checks pass. The remote
Cloudflare tunnel, DNS, and Access policy must still exist in the provider
control plane.

## 9. Reconnect the Drive repository

Open the restored SummitFlow UI through the existing Cloudflare Access route and
authenticate with the Gmail owner account. Do not generate a replacement key or
repository: the existing Drive snapshots are encrypted to the saved password.

The restored database names the repository: the enabled restic row of
`storage_backends` holds the locator, the password file, the rclone configuration
and the key directory (paths only, no secrets). List it, then put the owner's
password file and rclone configuration at exactly those paths, as user-owned
mode-600 regular files in the private mode-700 key directory:

```bash
st db query -t "SELECT name, config FROM storage_backends WHERE enabled"
```

If the new host needs other paths, correct that row's `config` before the first
run; there is no per-source or storage setup left in `st backup`. Never paste
credentials or tokens into chat.

Check the connection without writing anything:

```bash
st backup list
st backup status
```

Both read the repository, and `status` leads with whether anything is missing.
Then take the first copy of the new host: set up the T7 target and
`/etc/btrbk/summitflow.conf` per the [host recovery guide](native-host-recovery.md),
install the timer with `scripts/install-host-infra.sh`, and run `st backup run
--offsite`. btrbk starts with a full seed on the empty T7.

## 10. Validate before resuming automation

Require all of the following:

- expected databases, roles, schema heads, and application row counts;
- Redis responds with the recovered password and expected logical databases;
- Hatchet is ready and workers reconnect without regenerating config;
- each local API/UI/worker is healthy from its new managed release;
- recovered Git refs, index, WIP and local package artifacts are present;
- Cloudflare Access reaches the owner UI and still enforces the existing policy;
- `st backup list` shows the recovered snapshots, and
  `st backup restore summitflow --to <new empty dir> --dry-run` picks the one you
  restored from; and
- after `st backup run --offsite`, `st backup status` says "All backups current"
  with a new local point and a new Drive snapshot per job, and its test restore
  passes.

Only then re-enable recurring jobs and maintenance timers. Keep the custody copy
of the password and rclone configuration, and keep the Drive repository
untouched, until the new host has more than one verified Drive snapshot of its
own.

After recovery evidence is retained, remove the staging trees and dumps in
`/srv/recovery` with an explicit, reviewed target. Deleting files on an SSD is
not guaranteed secure erasure; use encrypted temporary storage when that property
matters. Never remove the custody copies as part of plaintext cleanup.
