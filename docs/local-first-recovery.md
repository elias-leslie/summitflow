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
