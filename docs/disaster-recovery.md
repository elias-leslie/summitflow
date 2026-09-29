# SummitFlow hard-loss recovery

Use this runbook when the original computer and its disks are unavailable. It
recovers SummitFlow from the encrypted archives in the `SummitFlow Backups`
Google Drive folder plus the recovery key that the owner saved separately.

Native age archives remain the production default. For an explicitly enabled
Restic pilot recovery point, use the [repository recovery procedure](local-first-recovery.md#repository-payload-recovery)
and [qualification gates](backup-optimization-rollout.md). The repository script
works without the SummitFlow database or API. Retain this native archive path,
its separately saved age key, and the existing Veeam seven-point image policy.

This is not an operating-system image. It does not recreate Linux packages,
users, groups, device configuration, Google Online Accounts, package caches, or
container-image caches. It also does not make an existing database safe to
overwrite. The database procedure below deliberately refuses to use an existing
Docker volume.

## What must still exist

Keep these in `SummitFlow Backups`:

- this runbook as `START-HERE.md`;
- the source-only companion runbook as `OFFLINE-RESTORE.md`;
- `recovery-bootstrap.py`;
- the dated `recovery-inventory.json` and `SHA256SUMS`;
- retained encrypted infrastructure, project, config, and workspace archives
  in their source folders, including the SummitFlow source archive. A large
  archive may be stored as an ordered `.parts.json` manifest and all of its
  `.partNNNNNN` siblings instead of one `.tar.gz.age` object.

The inventory is a dated, verified recovery point and source-folder map, not a
permanent `latest` pointer. Normal retention can expire an archive it names.
Use the selection procedure below when that happens; do not depend on an old
filename remaining forever. Retain downloaded ciphertext after making a working
copy.

The age private key must **not** be in Google Drive beside the archives. Obtain
the separately saved file containing the `AGE-SECRET-KEY-...` identity. A
checksum stored in the same Drive folder detects transfer errors; a separately
saved copy of the dated inventory provides stronger evidence that the selected
objects are the ones previously recorded.

Prepare a compatible Linux host with:

- Python 3.12 or newer for `recovery-bootstrap.py`, Python 3.13 or newer for
  the recovered SummitFlow backend, `age`, Git, gzip, sed, and a SHA-256 tool;
- Docker Engine and Docker Compose v2;
- `uv`, and Node/corepack/pnpm for local application rebuilds; and
- enough private disk space for the ciphertext, plaintext archives, extracted
  trees, builds, and database volumes.

The restored source removes any requirement for a GitHub account. Rebuilding
still needs the public Linux, Python, npm, and container registries referenced by
the lockfiles and Compose configuration unless their artifacts are already
cached. This kit is not an offline package mirror.

## 1. Preserve and verify the recovery point

Download the whole kit and select one archive per required source. Prefer the
dated inventory's verified archives when still available. A browser is enough;
the replacement host does not yet have to be signed into Google Online Accounts.
Work on a private local disk:

```bash
umask 077
mkdir -p /srv/recovery/summitflow-drive-original /srv/recovery/work
```

Put the downloaded files in `summitflow-drive-original`, then verify the provided
checksums from that directory:

```bash
cd /srv/recovery/summitflow-drive-original
sha256sum --check SHA256SUMS
```

`SHA256SUMS` covers the four static kit files, not expiring backup archives,
parts, or part manifests. Stop if a kit file is absent or has a different
checksum. The inventory's `artifacts` array records the object name, size, and
SHA-256 for a raw archive, or for the `.parts.json` manifest and every part of a
segmented archive. Compare every downloaded object with that record. Do not edit
the downloaded files. Copy or assemble selected ciphertext in
`/srv/recovery/work` and retain the originals until the replacement system has
completed a new, independently verified backup cycle.

Review the inventory before continuing. It must identify each raw archive or
complete segmented artifact set, including the full ciphertext SHA-256, for at
least:

1. the SummitFlow source archive;
2. the infrastructure archive; and
3. one archive for every project/config/workspace source required by the old
   host.

It should also record the key ID and the infrastructure capture coverage. A
missing or incomplete component is a recovery limitation to resolve, not a
warning to ignore.

### If a dated archive has expired, or a newer recovery point is needed

Use the same source folder identified by the inventory. Select either its newest
timestamped `.tar.gz.age` object or its newest `.tar.gz.age.parts.json` manifest.
For a manifest, download the manifest and **all** sibling part names it lists
from that same source folder; an isolated part or incomplete set is not a backup.
If both a raw archive and a complete parts set share the same archive name,
prefer the parts set. An earlier failed whole-file upload can leave a raw object
beside the later verified parts. A matching timestamp or filename does not prove
that the raw object is complete. Verify the manifest, every part, and the
assembled ciphertext before decryption.
Record every downloaded object's filename, size, and local SHA-256, plus the
manifest's full ciphertext checksum, in your recovery notes. Check all source
folders for projects added after the inventory was written; later compare them
with the recovered backup-source registry. Do not silently omit new projects,
mix parts from different manifests, or substitute an archive from another source
folder.

An independent matching checksum or offsite verification record is preferable.
If none survived, say so in the recovery notes: a newly computed checksum proves
subsequent copies match, not that this was a previously verified backup. Omit the
optional expected-checksum argument only in that case. The age authentication
check, safe archive validation and restore checks remain mandatory. Encryption
authentication detects damaged ciphertext; it does not independently establish
who created a file in a writable Drive account.

### Assemble a segmented ciphertext

Raw `.tar.gz.age` objects need no assembly. For a `.parts.json` recovery point,
keep its parts beside the manifest and let the bootstrap utility stream and
verify them; do not concatenate them manually:

```bash
python3 recovery-bootstrap.py \
  --assemble-parts /srv/recovery/summitflow-drive-original/<archive>.parts.json \
  --output-file /srv/recovery/work/<archive>
```

The output filename must be the manifest's exact `archive_name`. The utility
requires the version-1 `summitflow-age-parts` contract, consecutive safe part
names, regular non-linked files, exact sizes, each part checksum, and the final
ciphertext checksum. It refuses to overwrite an output and removes an incomplete
temporary output on failure. Assembly does not use the age key and manifest
checksums are not independent authentication: successful age decryption of the
reassembled ciphertext remains mandatory.

For project/config archives, complete the isolated restore and verify Git history
and saved index where present. For infrastructure, inspect its capture manifest
for every required component and complete the disposable database/Redis restore
checks below before using it. If the newest retained archive fails, preserve the
failure evidence and try the next newest in that same source folder. Do not
replace a failed restore with a success claim based only on decryption.

## 2. Recover SummitFlow source without a running service

Choose an absent or empty output directory. Use the raw downloaded archive or
the verified archive produced by the assembly step. The bootstrap script only
decrypts, validates, and extracts the SummitFlow source. It does not install
packages, contact the API, load a database, create a key, or start a service.

```bash
python3 recovery-bootstrap.py \
  summitflow-YYYYMMDD-HHMMSS.tar.gz.age \
  --identity-file /secure/offline/backup-identity.agekey \
  --output-dir /srv/recovery/source \
  --expected-sha256 sha256:<ciphertext-sha256-from-the-dated-inventory>
```

On success the bootstrap source is `/srv/recovery/source/summitflow`. It includes
the recovery payload, but it is not yet a reconstructed Git checkout: there is
no `.git` directory and the saved refs/index have not been applied. Use this
copy only to install the offline CLI.

The recovered `docker/workspace-packages` directory supplies the local wheels
and tarballs referenced by `backend/pyproject.toml` and `pnpm-lock.yaml`. Verify
those files are present, then bootstrap the CLI:

```bash
cd /srv/recovery/source/summitflow/backend
uv sync --frozen
uv run --frozen st --help
```

Now use that CLI to restore the original SummitFlow ciphertext into the absent
or empty final checkout. This is the operation that verifies the recovery
manifest, recreates Git refs/HEAD/index, and restores WIP:

```bash
uv run --frozen st backup restore \
  --file /srv/recovery/work/summitflow-YYYYMMDD-HHMMSS.tar.gz.age \
  --into /srv/workspaces/projects/summitflow \
  --identity-file /secure/offline/backup-identity.agekey \
  --expected-checksum sha256:<ciphertext-sha256-from-the-dated-inventory>
```

Inspect the real recovered checkout:

```bash
git -C /srv/workspaces/projects/summitflow fsck --full
git -C /srv/workspaces/projects/summitflow status --short --branch
```

The archive contains committed history, unpublished refs, the exact staged
index, working files, and durable data including
`data/design-studio/mockups`. Preserve that state. Do not clean, reset, or look
for obsolete `/tmp/summitflow/mockups` state.

If the replacement user or path differs from the original host, decide the final
layout now. Later, update host-specific paths in recovered environment files,
service units, and database project/source records before enabling automation.

Create the final checkout's own backend environment rather than reusing the
temporary bootstrap venv:

```bash
cd /srv/workspaces/projects/summitflow/backend
uv sync --frozen
uv run --frozen st --help
```

Restore every other archive named by the dated inventory into a new empty
destination using the offline restore command. Use its own recorded checksum and
the same separately saved identity:

```bash
uv run --frozen st backup restore \
  --file /srv/recovery/work/<source-archive>.tar.gz.age \
  --into /srv/recovery/restored/<source-id> \
  --identity-file /secure/offline/backup-identity.agekey \
  --expected-checksum sha256:<that-archive-ciphertext-sha256>
```

Inspect each Git recovery result and then place it at its intended stable path.
The database contains old absolute project and backup-source paths; reconcile
those paths after the database is restored and before backup or autonomous
schedules are resumed.

## 3. Materialize and inspect the infrastructure archive

Decrypt the infrastructure ciphertext into private temporary storage. Never put
the identity itself on the command line:

```bash
age --decrypt \
  --identity /secure/offline/backup-identity.agekey \
  --output /srv/recovery/work/infrastructure.tar.gz \
  /srv/recovery/work/infrastructure-YYYYMMDD-HHMMSS.tar.gz.age
chmod 600 /srv/recovery/work/infrastructure.tar.gz
```

Before touching durable volumes, run the disposable restore drill from the
recovered SummitFlow checkout:

```bash
cd /srv/workspaces/projects/summitflow
./scripts/infra-restore-drill.sh /srv/recovery/work/infrastructure.tar.gz
```

The drill pulls `pgvector/pgvector:pg16` and Redis if those images are not
cached. Require an `ok: true` result. The drill proves that the dump and RDB can
be loaded into disposable containers; it does not restore the production
volumes.

Extract only regular files and directories to a private staging directory:

```bash
mkdir -p /srv/recovery/infra
python3 - /srv/recovery/work/infrastructure.tar.gz /srv/recovery/infra <<'PY'
from pathlib import Path, PurePosixPath
import sys
import tarfile

archive_path = Path(sys.argv[1])
destination = Path(sys.argv[2])
if any(destination.iterdir()):
    raise SystemExit("infrastructure destination must be empty")
with tarfile.open(archive_path, "r:gz") as archive:
    members = archive.getmembers()
    roots = {
        PurePosixPath(member.name).parts[0]
        for member in members
        if PurePosixPath(member.name).parts
    }
    if roots != {"infrastructure"}:
        raise SystemExit(f"unexpected archive root: {sorted(roots)}")
    if any(not (member.isdir() or member.isreg()) for member in members):
        raise SystemExit("infrastructure archive has an unsupported member type")
    archive.extractall(destination, members=members, filter="data")
PY
```

Set this shorthand for the remaining commands:

```bash
RECOVERY_INFRA=/srv/recovery/infra/infrastructure
RECOVERY_COMPOSE=/srv/workspaces/projects/summitflow/docker/compose
test -f "$RECOVERY_INFRA/pgdumpall.sql.gz"
test -f "$RECOVERY_INFRA/configs/redis-dump.rdb"
test "$(head -c 5 "$RECOVERY_INFRA/configs/redis-dump.rdb")" = REDIS
```

Review `state/capture-manifest.json` and each nested manifest. In particular,
require the expected config, Hatchet, ingress, user-systemd, Agent Hub, and
managed-service components to say `captured`. Nonzero skipped links or special
files are explicit limitations that need operator review.

## 4. Put configuration in place while services are stopped

Do **not** run `docker/install.sh`: it generates new passwords and starts a
normally initialized database, both of which conflict with this restore.

Install the recovered files before starting Compose:

- `configs/compose-env` to `$RECOVERY_COMPOSE/.env`, mode `0600`;
- `configs/hatchet-config/` to `$RECOVERY_COMPOSE/hatchet-config/`;
- `configs/env.local` to the service owner's `~/.env.local`, mode `0600`;
- `configs/smbcredentials` to `~/.smbcredentials`, mode `0600`, only if SMB is
  still used; and
- `state/agent-hub/files/` to `~/.local/state/agent-hub/`, preserving modes.

The restored Compose environment contains the database and application secrets
that match the dump. Do not replace those secrets during recovery. Review and
update only host-specific values such as `HOST_HOME_PATH`, `DOCKER_GID`, device
paths, and obsolete SMB locations. Hatchet configuration must be present before
`hatchet-setup-config` runs; its Compose command is intentionally
`--overwrite=false`.

Before any SummitFlow Hatchet worker can start, import the saved identity into
the fresh host by calling the same backup-key service used by the owner UI. Run
this as the operating-system account that will run SummitFlow, after restoring
`~/.env.local`. The snippet reads only the configured key-directory setting from
that file so it uses the same key store as the future service. It reads the
secret from a file, never places it in an argument, and prints only the
non-secret key ID:

```bash
cd /srv/workspaces/projects/summitflow/backend
RECOVERY_KEY_FILE=/secure/offline/backup-identity.agekey
uv run --frozen python - "$RECOVERY_KEY_FILE" <<'PY'
from pathlib import Path
import os
import sys

from dotenv import dotenv_values

configured = dotenv_values(Path.home() / ".env.local").get(
    "SUMMITFLOW_BACKUP_KEY_DIR"
)
if configured:
    os.environ["SUMMITFLOW_BACKUP_KEY_DIR"] = configured

from app.services.backup_keys import import_backup_recovery_key

key_text = Path(sys.argv[1]).read_text(encoding="utf-8")
status = import_backup_recovery_key(key_text)
key_text = ""
if not status.get("ready") or not status.get("key_id"):
    raise SystemExit("saved backup key was not imported and verified")
print(f"BACKUP_KEY_READY {status['key_id']}")
PY
unset RECOVERY_KEY_FILE
```

This import is allowed only while the key store is unconfigured and performs a
real age encrypt/decrypt round trip. Compare the printed key ID to the dated
inventory. Stop on `backup_key_already_configured` or a mismatch; never replace
key material to make an old archive pass. Keep the saved identity in its
separate custody location after import.

Keep user services disabled. Copy the regular unit files from
`state/systemd-user/files/` to `~/.config/systemd/user/`, but review their
absolute paths first. The enablement entries in
`state/systemd-user/manifest.json` record which units were enabled. Re-enable
those unit names through `systemctl --user enable <unit>` only after their
executables and working directories exist. Do not blindly recreate arbitrary
symlink targets.

Managed-service state under `state/managed-services/` contains receipts, job
records, and the names of the old `current` and `previous` builds. It deliberately
does not contain the old release source trees. Restore receipts as audit evidence
and retain job records without resubmitting them. Old build IDs are not runnable
releases and old transient `sf-rebuild-*` jobs must not be recreated. New releases
are built from the recovered project sources in step 7.

## 5. Restore PostgreSQL into a provably new PG16 volume

The production dump is a full `pg_dumpall`: it contains roles and databases.
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
succeeds. Review the dump source path one last time, then restore with pipeline
failure propagation enabled:

```bash
set -o pipefail
gzip --decompress --stdout "$RECOVERY_INFRA/pgdumpall.sql.gz" \
  | sed -e '/^CREATE ROLE postgres;$/d' -e '/^ALTER ROLE postgres /d' \
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
test "$(head -c 5 "$RECOVERY_INFRA/configs/redis-dump.rdb")" = REDIS
docker volume create --label summitflow.recovery=fresh "$RECOVERY_REDIS_VOLUME"
docker run --rm --user 0 \
  --volume "$RECOVERY_REDIS_VOLUME:/data" \
  --volume "$RECOVERY_INFRA/configs/redis-dump.rdb:/recovery/dump.rdb:ro" \
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
docker compose --profile infra up -d postgres redis docker-socket-proxy
docker compose ps
```

Verify PostgreSQL and authenticated Redis health. Then start Hatchet. Because
both its database and configuration were restored, do not regenerate either:

```bash
docker compose --profile infra up -d hatchet-migrate hatchet-setup-config hatchet
docker compose ps
```

Review Hatchet migration output and require its ready endpoint before starting
workers. A mismatched or unavailable `HATCHET_TAG` is a registry/version problem,
not permission to regenerate Hatchet state.

Before a SummitFlow worker starts, query `projects.root_path` and
`backup_sources.path` in the restored `summitflow` database. Correct each stale
old-host path to the corresponding recovered stable source. Confirm that the
saved backup key already reports `ready` with the inventory key ID. Also review
the recovered per-project `agent_configs` and leave autonomous pickup and
scheduled actions disabled until final validation. Do not start a worker merely
to use the UI to repair these prerequisites.

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
worker; therefore it must not run until the source-path reconciliation, cold key
import/verification, and automation review above are complete.

After builds and local health checks succeed, reload the reviewed user units,
enable only the units recorded as enabled, and start them in dependency order:

```bash
systemctl --user daemon-reload
systemctl --user enable <reviewed-unit-name>
systemctl --user start <reviewed-unit-name>
```

The checked-in `scripts/install-host-maintenance.sh` can recreate SummitFlow's
system-level maintenance units, Docker log limits, and the infrastructure
reconcile unit. Review its hard-coded paths and effects before running it with
sudo; it is not archive restoration.

## 8. Restore ingress last

Do not expose services until their local health checks and owner flows work.
Install Caddy and cloudflared from their normal public package sources, but keep
their services stopped. From the infrastructure staging tree:

- install `state/host-ingress/caddy/Caddyfile` as
  `/etc/caddy/Caddyfile`;
- install `state/host-ingress/caddy/env` as `/etc/caddy/env` with restrictive
  permissions; and
- install `state/host-ingress/cloudflared/config.yml` plus the exact credential
  filename recorded by `state/host-ingress/manifest.json` under
  `/etc/cloudflared/`, root-owned and unreadable by other users.

Reapply any service-account ACLs needed to read the host configuration. POSIX
ACLs, xattrs, numeric ownership policy, and system-level unit enablement are not
fully reconstructed by the archive.

Validate configurations before starting either service:

```bash
sudo cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
sudo caddy validate --config /etc/caddy/Caddyfile
```

Start Caddy and cloudflared only after local API and UI checks pass. The encrypted
archive carries the tunnel credential, but the remote Cloudflare tunnel, DNS,
and Access policy must still exist in the provider control plane.

## 9. Re-establish owner key and Drive access

Open the restored SummitFlow UI through the existing Cloudflare Access route and
authenticate with the Gmail owner account. In Backup encryption, confirm the
same key ID and the verified/ready state established by the cold import. The
normal fresh-host UI path is **Use an existing recovery key** and performs the
same real age challenge, but it is unnecessary after the cold import and must
not be used to replace configured material. Do not generate a replacement key:
existing Drive archives are encrypted to the saved one. Local bypass sessions
are intentionally not allowed to import or reveal recovery keys.

Next sign the Linux desktop into the Google account again through Google Online
Accounts, or establish another supported authenticated GIO mount. GOA/GVfs
tokens and keyring contents are not backup contents. Configure the recovered
`BACKUP_OFFSITE_GIO_URI` for the newly mounted `SummitFlow Backups` folder and
verify that GIO can list it. Initial recovery may use browser downloads; future
offsite replication requires the mounted provider URI.

## 10. Validate before resuming automation

Require all of the following:

- expected databases, roles, schema heads, and application row counts;
- Redis responds with the recovered password and expected logical databases;
- Hatchet is ready and workers reconnect without regenerating config;
- each local API/UI/worker is healthy from its new managed release;
- recovered Git refs, index, WIP, config/workspace sources, and local package
  artifacts are present;
- Agent Hub and systemd capture manifests have no unexplained skipped state;
- Cloudflare Access reaches the owner UI and still enforces the existing policy;
- the imported age key reports the same key ID as the dated inventory; and
- a new capture produces one encrypted `.tar.gz.age`, the same ciphertext is
  verified in Drive, and an isolated restore test passes.

Only then re-enable backup schedules, autonomous execution, recurring jobs, and
maintenance timers. Keep the downloaded ciphertext and saved key until the new
host has more than one independently verified recovery point.

After recovery evidence is retained, remove plaintext archives and extracted
temporary staging from `/srv/recovery` with an explicit, reviewed target. Deleting
files on an SSD is not guaranteed secure erasure; use encrypted temporary
storage when that property matters. Never remove the separately saved key or the
original Drive ciphertext as part of plaintext cleanup.
