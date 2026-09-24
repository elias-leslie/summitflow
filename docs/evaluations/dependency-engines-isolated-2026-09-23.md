# Isolated dependency engine evaluation, 2026-09-23

## Decision

Keep hosted Dependabot proposals and the existing `uv`/`pnpm` evidence path. Do not add a local engine adapter. The pinned local engines worked for targeted updates, but neither adds advisory discovery or an unmet review capability worth operating a second update producer. Renovate local is an experimental extract/lookup interface without update artifacts. Dependabot CLI produced useful local update YAML, but hosted Dependabot already has open [Python PR #2](https://github.com/elias-leslie/summitflow/pull/2) (17 grouped updates in `backend/uv.lock`) and [Actions PR #1](https://github.com/elias-leslie/summitflow/pull/1). No PR, lockfile update, or live package installation was made by this evaluation.

## Pins and isolation

| Candidate | Exact evaluated pin | Local footprint |
| --- | --- | ---: |
| Dependabot CLI | v1.93.0 Linux amd64 release archive SHA-256 `3c89e7a3d04066115a8d17574267ae288cb67f9dcb7096f9c7ce96ee180849ba` | 21 MB archive |
| Dependabot proxy | `ghcr.io/dependabot/proxy@sha256:18de7d168d9ef2975d57f02f253d4f15dfb94c1c4520a2984a0cfc74a4daed58` | 21 MB unpacked image |
| Dependabot uv updater | `ghcr.io/dependabot/dependabot-updater-uv@sha256:643650963d35f7bcaea14ffafbbc82ca9ca6b7bee912480df39d1c8a138947b2` | 2.06 GB unpacked image |
| Dependabot npm updater | `ghcr.io/dependabot/dependabot-updater-npm@sha256:7336ad84c4d94a7a30584a3655439c2aa079ba4f16c508898b7835e5127de334` | 1.33 GB unpacked image |
| Renovate | `renovate/renovate@sha256:17d4571bb8ca99019728e9e77730ed4060bf9b50737f42dc3cbe68993c554f5d`; binary reported 44.110.0 | 1.34 GB unpacked image |

These digests were resolved on September 23 and used directly for execution. The Dependabot CLI binary and both cache directories were under `/tmp/summitflow-dependency-engines-20260923`, not installed into SummitFlow. The representative Git repo there copied `backend/pyproject.toml`, `backend/uv.lock`, root and workspace `package.json` files, `pnpm-lock.yaml`, workflows, compose manifests, both bot configurations, and the local wheel/tarball files those manifests reference. Its final local commit was `4963dcca37440a9ed734e2db5a3b527afad94ed7`. The first uv attempt omitted local wheels and failed after 144.66 seconds with `dependency_file_not_resolvable`; the corrected copy then succeeded. This is a workspace-fixture failure, not a successful update result.

Renovate ran in disposable Docker containers with a read-only source bind, read-only root filesystem, temporary `/tmp`, CPU/memory/PID limits, and no token or Docker socket inside the container. Dependabot CLI used Docker to start its pinned updater and proxy, a copied `--local` source, and local YAML output. Its proxy mediated updater network calls; the CLI host still required Docker daemon access. `st check cleanroom` also copied the full tracked checkout into an ST-managed temporary home and repo, ran pinned Renovate extraction with a read-only bind, scrubbed project environment keys, and removed the snapshot afterward. No container was left running.

## Measurements and artifacts

Wall times are single observations on this host, not latency distributions. Cold/warm means empty/reused engine cache with images already pulled unless the pull is listed separately. Logs and full YAML receipts remain in `/tmp/summitflow-dependency-engines-20260923`; hashes below identify those local artifacts, but `/tmp` is not durable storage.

| Operation | Wall time | Observed result |
| --- | ---: | --- |
| Renovate image cold pull | 15.16 s | Pinned 44.110.0 image cached |
| Renovate local extract, representative copy | 3.46 s | 175 references in 11 files: compose 17, Actions 40, npm 72, PEP 621 43, Poetry 3 |
| Renovate local lookup, empty/reused 3.9 MB cache | 12.33 / 8.02 s | Lookup split 8.175 / 4.402 s; PyPI cache 0/35 then 35/35 hits; GitHub token/rate-limit warnings persisted |
| ST cleanroom Renovate extract, full checkout | 6.79 s including ST snapshot | 222 references in 15 files, including 46 Dockerfile and one pyenv reference absent from the smaller copy; warning about missing GitHub token |
| Dependabot proxy plus uv updater cold pulls | 25.04 s | Pinned images cached |
| Dependabot uv FastAPI job, empty/reused 82 MB cache | 16.01 / 11.83 s | YAML proposed `fastapi` 0.136.3 → 0.141.1 and updated `backend/uv.lock`; warm proxy 204/204 calls cached |
| Dependabot npm updater cold pull | 8.35 s | Pinned image cached |
| Dependabot npm React job, empty/reused 519 MB cache | 26.86 / 19.12 s | YAML proposed `react` 19.2.4 → 19.3.0 and `@types/react` 19.2.14 → 19.3.0; changed `frontend/package.json` and `pnpm-lock.yaml`; warm proxy 1064/1064 calls cached |

The uv cold/warm YAML receipts are 448,938 bytes, with SHA-256 `c434ed3a4a9dce8e7835169490e707190e7b9daf775479be689d94f441741292` and `d5dca819366707f40f086fe4c95f15e7b63d4bb0eb559c972015b823dc2c5a83`. The npm cached-run receipts are about 406 KB; cold/warm hashes are `2fa61368fb828de455192f1c3ebd4f0fae0ca39d1a77d1fe878346a10bfad39f` and `2d547d7a6fd1d7fe99e4ca1425d197227a136081b08089da648495427d1fd573`. Each pair parsed to the same YAML structure after removing the CLI-generated `ignore-conditions[].source` output-file path. Both recorded `update_dependency_list`, `create_pull_request`, and `mark_as_processed` events. These are *local recorded calls*, not published PRs. Renovate's debug log supplied extraction and lookup details, but the local platform did not emit an update YAML artifact.

## Existing evidence and coverage limits

On the copied lockfiles, `uv tree --frozen --package fastapi --outdated` reported locked 0.136.3 and latest 0.141.1 in 0.31 seconds. `pnpm outdated --recursive --format json react` reported wanted 19.2.4 and latest 19.3.0 in 0.49 seconds (exit 1 means outdated). These commands answer version-review questions much more cheaply than a complete engine job; they do not generate a tested lockfile patch. Hosted Python PR #2 already supplies a grouped lockfile diff, and Actions PR #1 supplies a workflow diff. Dependabot CLI Actions generation was not separately measured. The representative Renovate copy omitted three Dockerfiles and `.python-version`; the ST cleanroom full extraction covers those files.

Routine engine jobs did not establish advisory status. A separate `uv audit --frozen` on the copied backend lockfile returned exit 0 in 0.40 seconds and said no known vulnerabilities or adverse project statuses in 96 packages. `pnpm audit --json` returned exit 0 in 0.55 seconds, zero reported advisories across 567 dependencies. These are point-in-time whole-lock results, not per-package evidence from the engine jobs. Host `uv 0.11.9` marks audit experimental and rejects `--output-format json` with exit 2; its text output is insufficient for structured per-package Python review, so that live Python advisory check remains **unknown**. The newer official uv reference describes JSON/SARIF output, but that interface was not available in the installed version. Renovate's GitHub-token warning also means GitHub-backed lookup completeness is **unknown** in this run.

The cold cost of reaching one local update artifact was at least 41.05 seconds for uv (image pulls plus the successful targeted job) and 35.21 seconds for npm after the shared proxy was cached; warm jobs still took 11.83 and 19.12 seconds. This excludes CLI download, workspace preparation, the failed 144.66-second incomplete fixture run, cache/digest refresh, artifact parsing, and review of generated lockfiles. Persisting 82 MB to 519 MB per proxy cache and maintaining roughly 1.3 GB to 2.1 GB per updater image would add operational cost. A future adapter would need versioned YAML parsing, digest policy, cache ownership, cleanup, timeouts, failure-state preservation, and safeguards against duplicate hosted proposals. No measured gap currently justifies that code.

Primary documentation: [Dependabot CLI usage and proxy model](https://github.com/dependabot/cli), [Renovate local limitations](https://docs.renovatebot.com/modules/platform/local/), [uv audit CLI reference](https://docs.astral.sh/uv/reference/cli/#uv-audit), and [pnpm audit](https://pnpm.io/cli/audit).
