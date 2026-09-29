# Local-first cold recovery

This runbook covers recovery when the SummitFlow API/task database and GitHub are
unavailable. It does not overwrite a production checkout or restore a production
database.

## Required material

- The downloaded native SummitFlow project archive. New archives are named
  `summitflow-YYYYMMDD-HHMMSS.tar.gz.age`. A large archive may instead be a
  `.parts.json` manifest plus all of its `.partNNNNNN` files from the same
  source folder.
- The separately saved age identity exported by SummitFlow. Keep the file private;
  it contains one `AGE-SECRET-KEY-...` line.
- Linux with `age`, Git, Python 3.13+, and `uv`. The standalone source bootstrap
  alone supports Python 3.12+; installing the recovered backend requires 3.13+.
- Enough private temporary disk space for one plaintext archive and extracted tree.

GitHub credentials and a GitHub account are not required. The archive contains its
own Git bundle, refs, HEAD, exact index, working files, and recovery manifest.

Dependency caches are intentionally not backup contents. Rebuilding the backend
requires the package sources or registries referenced by `backend/uv.lock`. Building
the frontend likewise requires the pnpm registry and any local workspace package
artifacts referenced by `pnpm-lock.yaml`. A containerized infrastructure drill also
requires the configured container registry unless those images already exist locally.

## Native project archive layout

After decryption, a project archive has exactly one top-level directory. For the
SummitFlow source backup it is `summitflow/`:

```text
summitflow/
├── ... captured source and working files
├── database.sql.gz                         # when the source has a database
└── .summitflow-recovery/
    ├── manifest.json                       # HEAD, refs and payload checksums
    ├── git.bundle                          # committed and unpublished Git history
    └── git-index                           # exact staged state
```

Infrastructure archives instead use `infrastructure/` and contain
`pgdumpall.sql.gz`, `configs/`, and `state/` capture manifests.

## Bootstrap the offline CLI

Work only in a new private directory. Replace the angle-bracket placeholders with
actual paths; do not put the recovery-key contents on the command line.

Download `recovery-bootstrap.py` from the Drive recovery kit (the repository copy
is `scripts/recovery-bootstrap.py`). Verify the kit with its `SHA256SUMS` file.
Use the archive checksum in the dated recovery inventory when it matches your
chosen archive; omit that argument if the archive is newer than the inventory.
When choosing without a matching inventory record, prefer a complete parts set
over a same-named raw archive. A failed older whole-file upload may coexist with
the later verified parts; its filename alone does not establish completeness.
Create the private workspace before copying or assembling recovery material:

```bash
umask 077
recovery_workspace=$(mktemp -d)
```

If the selected recovery point is segmented, download its `.parts.json` manifest
and every part it names into one private directory. The inventory's `artifacts`
array records those individual objects; the kit's `SHA256SUMS` covers only its
four static files. Assemble with the utility rather than `cat`:

```bash
python3 recovery-bootstrap.py \
  --assemble-parts <downloaded-archive.tar.gz.age.parts.json> \
  --output-file "$recovery_workspace/downloaded-archive.tar.gz.age"
```

Assembly needs no key. It streams the parts in their required order and verifies
their safe names, regular non-linked file type, sizes, individual checksums, and
the final ciphertext checksum before publishing a mode-`0600` output. It refuses
to overwrite an existing output and removes incomplete temporary output on
failure. The manifest and its checksums are not independent authentication;
successful age decryption is still mandatory. Use the assembled output as the
archive in the commands below. Its basename must exactly match the manifest's
`archive_name`.

```bash
python3 recovery-bootstrap.py <downloaded-summitflow.tar.gz.age> \
  --identity-file <saved-recovery-key-file> \
  --output-dir "$recovery_workspace/bootstrap" \
  --expected-sha256 sha256:<ciphertext-sha256>
```

This stages and hashes one stable ciphertext copy, decrypts privately, rejects
unsafe archive paths/member types, and publishes the source only after extraction
succeeds. It does not install dependencies, restore databases or start services.
Temporary plaintext archives are removed on exit; the extracted source remains
private and may contain sensitive configuration. Retain the original ciphertext.

Install the recovered backend CLI from the extracted source:

```bash
cd "$recovery_workspace/bootstrap/summitflow/backend"
uv sync --frozen
```

If `uv sync` reports a missing local wheel, recover the archive for that package's
owning project or restore the retained `docker/workspace-packages` artifact. GitHub is
not the required source for those packages, but their package registry or local build
inputs must be available.

## Perform the isolated restore

Choose a destination that is absent or empty. The optional checksum is the ciphertext
`encrypted_checksum` from a retained local `offsite-manifest.json` or backup record.
It uses the exact `sha256:<64 lowercase hex characters>` form.

```bash
uv run --frozen st backup restore \
  --file <downloaded-summitflow.tar.gz.age> \
  --into <empty-destination> \
  --identity-file <saved-recovery-key-file> \
  --expected-checksum sha256:<ciphertext-sha256>
```

Omit `--expected-checksum` only when that independent record is unavailable. Age still
authenticates the encrypted payload and fails on a wrong key or modified ciphertext;
the restore additionally verifies the Git bundle and saved-index checksums. Without an
external checksum, it does not independently prove that the downloaded object is the
specific archive previously recorded by SummitFlow.

The command never contacts the SummitFlow API and never reads or writes the task or
backup database. It decrypts in a private temporary directory, validates the archive
layout, restores files into the empty destination, recreates Git refs/HEAD/index, and
copies any database dump to `.summitflow-recovery/`. It does not load that dump.

Inspect the result before making it a runtime checkout:

```bash
git -C <empty-destination> fsck --full
git -C <empty-destination> status --short --branch
```

For an infrastructure archive, decrypt it into private temporary storage and validate
it only against disposable services:

```bash
./scripts/infra-restore-drill.sh <plaintext-infrastructure.tar.gz>
```

That drill does not authorize restoring `pgdumpall.sql.gz` into production. Database
promotion, service activation, secret placement, and cleanup of plaintext recovery
material remain explicit operator actions.

For the complete replacement-host sequence, including fresh database/Redis
volumes, durable state and ingress, use `START-HERE.md` in Drive (repository:
`docs/disaster-recovery.md`). Do not substitute the fresh-install secret-generation
steps from the application README for restoring existing credentials.

## Repository payload recovery

Use this procedure only for a recorded Restic pilot snapshot. Native age
archives remain the default. The local and Google Drive repositories are
independent encrypted repositories. The Drive recovery procedure must work when
the local repository, SummitFlow database/API and original host are unavailable.

Keep `scripts/backup-repository-recover.sh`, this runbook, the pinned tool
checksums, and a dated repository/source inventory in the recovery kit. Verify
the kit against its independently saved checksums before running it. The pilot
kit is additional recovery material; the existing native kit and age key remain
necessary for retained native archives. Publication of the expanded kit and
dedicated Drive OAuth setup are qualification work, not completed by checking
these files into Git.

Prepare Linux with Bash, Python 3.12+, restic 0.19.1 and rclone 1.75.1. Verify
the tool releases with their published checksums and signatures. Git is needed
only when reconstructing a captured repository. No SummitFlow dependencies,
task database, API, GitHub account or running database service are needed to
list/check/restore payloads with the standalone script.

Obtain the offsite repository password and the dedicated rclone configuration
from separate offline custody. They must be regular files owned by the recovery
user with mode `0600`, at absolute paths without symlinks. Keep the offsite
password separately from the Drive repository, and preserve the independent
local repository password and native age identity. Put file references on the
command line, never their contents. The script does not read shell env files or
create OAuth credentials. GOA/GVfs desktop sign-in is not its authentication
path. Dedicated Drive OAuth is pending until an operator provisions and proves
the recorded bounded remote.

### Select a recovery point from Drive

Use the exact repository locator in the dated inventory. This example names a
bounded folder; replace `backup-drive` and the folder with the recorded values:

```bash
bash scripts/backup-repository-recover.sh snapshots \
  --repository 'rclone:backup-drive:SummitFlow Backups/restic' \
  --password-file /secure/offline/restic-drive.password \
  --rclone-config /secure/offline/restic-rclone.conf \
  --source summitflow
```

Record the full 64-character snapshot ID, source tag, timestamp and captured
paths from the JSON result. Choose a separately verified point for every
required source. `latest` alone is ambiguous in a shared repository. Remote
snapshot IDs can differ from local IDs after native `restic copy`; use the
remote ID from the inventory or the remote listing.

Check repository structure before restoring:

```bash
bash scripts/backup-repository-recover.sh check \
  --repository 'rclone:backup-drive:SummitFlow Backups/restic' \
  --password-file /secure/offline/restic-drive.password \
  --rclone-config /secure/offline/restic-rclone.conf
```

A structure check does not read every payload pack. For the recorded monthly
payload coverage, add `--read-data-subset 1/30`, then advance only after a
successful check through all 30 parts. Interrupted checks do not count as
completed coverage. Retain the month's repository inventory and completion
records, and reconcile inventory changes or interrupted scope through the
managed verifier. The standalone script does not maintain durable coverage
state. Random percentages do not establish full coverage. A full
`restic check --read-data` is an explicit operator operation when required;
it downloads all packs and must be included in traffic evidence.
[Restic documents structure and payload checks separately](https://restic.readthedocs.io/en/stable/045_working_with_repos.html#checking-integrity-and-consistency).

### Restore into private isolated storage

Create an empty private destination on encrypted local storage with enough
space for the selected source. Keep credentials outside the destination:

```bash
umask 077
mkdir -m 700 -p /srv/recovery/restic/summitflow
bash scripts/backup-repository-recover.sh restore \
  --repository 'rclone:backup-drive:SummitFlow Backups/restic' \
  --password-file /secure/offline/restic-drive.password \
  --rclone-config /secure/offline/restic-rclone.conf \
  --snapshot <full-remote-snapshot-id> \
  --into /srv/recovery/restic/summitflow \
  --verify
```

The script requires an empty absolute private directory, refuses root symlinks
and path traversal, and runs `restic restore --verify`. Restic reconstructs the
paths stored in the selected snapshot beneath this destination. Use the recorded
capture path to locate the materialized project tree; do not assume it is the
destination's root. `--verify` checks restored file contents.
[The pinned Restic command defines this verification](https://github.com/restic/restic/blob/v0.19.1/cmd/restic/cmd_restore.go).

For a local recovery point, use the same commands with the absolute local
repository path and its own password-file reference, omitting `--rclone-config`.
That local test does not qualify recovery from Drive alone. Any command failure
is a failed step. Preserve its evidence and any partial destination; retry into
a different empty directory. The script does not delete partial restores or
remove repository locks.

### Recover Git and registered configuration links

For a project with `.summitflow-recovery/manifest.json`, repeat the restore into
a fresh empty destination and add `--git-root <relative-materialized-project-path>`.
For example, if the inventory records a capture at
`/srv/private-capture/summitflow/project-snapshot`, the relative argument is
`srv/private-capture/summitflow/project-snapshot`. Use the actual recorded path.

The script checks bundle/index SHA-256 against the recovery manifest, reconstructs
refs and HEAD with standard Git, installs the saved index, and runs `git fsck
--full`. It supports SHA-1 and SHA-256 repositories and refuses an existing
`.git`. Working files remain as restored, including staged changes, unstaged
changes and untracked WIP. Inspect `git status --short --branch` before deciding
what to deploy. Nothing in this step resets, cleans or commits recovered work.

Restore canonical `codex-config`, `claude-config`, `claude-root-config` and
`agent-skills` sources before rebuilding registered links. An explicit
`.claude.json` source restores as that named regular file inside its payload.
External source links are versioned `mapped_links` metadata, not host links in
the payload. Their target source IDs and relative paths must map to explicit
restored destinations inside one isolated recovery root.

Once the recovered backend dependencies are installed, the existing
`app.tasks.backup_native_recovery.restore_mapped_links` helper can apply that
explicit destination map. It does not access the task database. Call it only
after every required target exists, pass the encompassing `isolated_root`, and
keep the map pointed at isolated restored trees. The standalone shell script
leaves mappings unapplied. Never reconstruct the captured absolute host targets,
follow arbitrary links to gather missing files, or point the recovery map into
the live home directory.

### Validate state before activation

Project database payloads are plain `database.sql`; if an original source file
already used that path, the generated dump is
`.summitflow-recovery/database.sql`. Infrastructure payloads contain plain
`pgdumpall.sql`, `configs/`, `state/`, and the existing capture-component
manifests. They carry recovery data, not permission to load it. Require the
expected component statuses and preserve missing/error evidence.

Use the existing [hard-loss runbook](disaster-recovery.md) for reviewed fresh
database volumes, Redis recovery, credential placement and managed rebuilds.
Its native archive examples use `.sql.gz`; make a private gzip working copy of
the restored plain SQL when adapting those steps, retaining the original plain
dump. The standalone repository script does not load SQL, start services, change
accounts, place host secrets or activate recovered state.

Record selected IDs and sources, repository check results, restored byte counts,
Git/ref/index checks, conversation/WIP/original-asset coverage, infrastructure
component results, missing prerequisites, and elapsed time. The essential
Drive-only recovery must complete on a fresh OS within four hours, including
validation of the agreed critical functions and state. File extraction alone
does not prove those functions recover. Local-only
or already-configured-host recovery does not satisfy that gate. Keep production
activation and plaintext cleanup as separately reviewed operations.
