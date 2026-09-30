#!/usr/bin/env bash
# Standalone repository recovery. No SummitFlow imports, database, or API.
set -euo pipefail
umask 077

usage() {
    cat <<'USAGE'
Usage: bash backup-repository-recover.sh snapshots|check|restore [options]
  --repository PATH|rclone:REMOTE:BOUNDED_FOLDER
  --password-file ABSOLUTE_PRIVATE_FILE
  --rclone-config ABSOLUTE_PRIVATE_FILE       required for rclone repositories
  --source SOURCE_ID                         optional snapshots filter
  --read-data-subset N/T                     optional deterministic check subset
  --snapshot FULL_64_HEX_ID --into ABSOLUTE_EMPTY_PRIVATE_DIR --verify
  --git-root RELATIVE_PROJECT_PATH           optional Git reconstruction after restore

Requires restic 0.19.1, rclone 1.75.1 for Drive, and Python 3.12+.
check without a subset checks structure; restore always verifies restored files.
No init, copy, unlock, forget, prune, delete, SQL loading, or service activation.
USAGE
}
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

[[ $# -gt 0 ]] || { usage; exit 1; }
mode=$1
shift
[[ "$mode" == --help || "$mode" == -h ]] && { usage; exit 0; }
[[ "$mode" == snapshots || "$mode" == check || "$mode" == restore ]] || fail "Unsupported mode"
repository='' password_file='' rclone_config='' source_id='' subset=''
snapshot='' destination='' git_root='' verify=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --verify) verify=true; shift ;;
        --help|-h) usage; exit 0 ;;
        --repository|--password-file|--rclone-config|--source|--read-data-subset|--snapshot|--into|--git-root)
            [[ $# -gt 1 ]] || fail "Missing option value"
            case "$1" in
                --repository) repository=$2 ;;
                --password-file) password_file=$2 ;;
                --rclone-config) rclone_config=$2 ;;
                --source) source_id=$2 ;;
                --read-data-subset) subset=$2 ;;
                --snapshot) snapshot=$2 ;;
                --into) destination=$2 ;;
                --git-root) git_root=$2 ;;
            esac
            shift 2 ;;
        *) fail "Unknown option" ;;
    esac
done
[[ -n "$repository" && -n "$password_file" ]] || fail "Repository and password-file references are required"
[[ -z "$source_id" || "$mode" == snapshots ]] || fail "--source is only supported for snapshots"
[[ -z "$subset" || "$mode" == check ]] || fail "--read-data-subset is only supported for check"
if [[ "$mode" == restore ]]; then
    [[ "$verify" == true && "$snapshot" =~ ^[0-9a-f]{64}$ && -n "$destination" ]] || fail "Restore requires a full snapshot ID, --into, and --verify"
else
    [[ "$verify" == false && -z "$snapshot" && -z "$destination" && -z "$git_root" ]] || fail "Restore options require restore mode"
fi
[[ -z "$source_id" || "$source_id" =~ ^[a-zA-Z0-9._-]+$ ]] || fail "Invalid source ID"
if [[ -n "$subset" ]]; then
    [[ "$subset" =~ ^([1-9][0-9]*)/([1-9][0-9]*)$ ]] || fail "Subset must use N/T"
    (( 10#${BASH_REMATCH[1]} <= 10#${BASH_REMATCH[2]} )) || fail "Subset N must not exceed T"
fi
command -v python3 >/dev/null || fail "Python 3.12+ is required"
python3 - "$repository" "$password_file" "$rclone_config" "$mode" "$destination" "$git_root" <<'PY'
import os
import re
import stat
import sys
from pathlib import Path

def require(condition, message):
    if not condition:
        raise SystemExit(f"ERROR: {message}")

require(sys.version_info >= (3, 12), "Python 3.12+ is required")
repo, password, config, mode, output, git_root = sys.argv[1:]
def private_file(raw):
    path = Path(raw)
    require(path.is_absolute() and path.resolve() == path, "Credential reference must be absolute and contain no symlink")
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid() and not metadata.st_mode & 0o077,
            "Credential reference must be a private regular file owned by this user")
private_file(password)
if repo.startswith("rclone:"):
    match = re.fullmatch(r"rclone:[A-Za-z0-9_-]+:([^\x00\r\n\\]+)", repo)
    require(match is not None, "Repository must identify a bounded rclone folder")
    require(all(part not in {"", ".", ".."} for part in match[1].split("/")), "Remote root and traversal are refused")
    require(bool(config), "--rclone-config is required")
    private_file(config)
else:
    path = Path(repo)
    require(path.is_absolute() and path != Path("/") and path.resolve() == path and path.is_dir(), "Local repository must be an existing absolute directory without symlinks")
    require(not config, "--rclone-config requires an rclone repository")
if mode == "restore":
    path = Path(output)
    require(path.is_absolute() and path != Path("/") and path.resolve() == path, "Destination must be absolute and contain no symlink or traversal")
    require(path.parent.is_dir(), "Destination parent must already exist")
    if path.exists():
        metadata = path.lstat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.getuid() and not metadata.st_mode & 0o077,
                "Destination must be a private directory owned by this user")
        require(not any(path.iterdir()), "Destination must be empty")
    if git_root:
        require(not git_root.startswith("/") and "\\" not in git_root and all(part not in {"", ".."} for part in git_root.split("/")), "Git root must be a relative path inside the restore destination")
PY

command -v restic >/dev/null || fail "restic 0.19.1 is required"
restic_version=$(restic version)
[[ "$restic_version" == 'restic 0.19.1 '* ]] || fail "Expected restic 0.19.1"
if [[ "$repository" == rclone:* ]]; then
    command -v rclone >/dev/null || fail "rclone 1.75.1 is required"
    rclone_version=$(rclone version)
    [[ "$rclone_version" == 'rclone v1.75.1' || "$rclone_version" == 'rclone v1.75.1'$'\n'* ]] || fail "Expected rclone 1.75.1"
fi
# Explicit file references override inherited repository, password, and remote settings.
while IFS= read -r variable; do
    if [[ "$variable" == RESTIC_* || "$variable" == RCLONE_* ]]; then
        unset "$variable"
    fi
done < <(compgen -v)
[[ -z "$rclone_config" ]] || export RCLONE_CONFIG="$rclone_config"
restic_args=(--repo "$repository" --password-file "$password_file" --no-cache)
case "$mode" in
    snapshots)
        extra=()
        [[ -z "$source_id" ]] || extra=(--tag "source:$source_id")
        restic "${restic_args[@]}" snapshots --json "${extra[@]}" ;;
    check)
        extra=()
        [[ -z "$subset" ]] || extra=("--read-data-subset=$subset")
        restic "${restic_args[@]}" check "${extra[@]}" ;;
    restore)
        [[ -d "$destination" ]] || mkdir -m 700 -- "$destination"
        restic "${restic_args[@]}" restore "$snapshot" --target "$destination" --verify
        [[ -n "$git_root" ]] || exit 0
        command -v git >/dev/null || fail "Git is required for --git-root"
        python3 - "$destination" "$git_root" <<'PY'
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

isolated = Path(sys.argv[1]).resolve(strict=True)
project = (isolated / sys.argv[2]).resolve(strict=True)
if not project.is_relative_to(isolated) or not project.is_dir():
    raise SystemExit("ERROR: Git project must remain inside the isolated restore")
recovery = project / ".summitflow-recovery"
def regular(path):
    if path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
        raise SystemExit("ERROR: Git recovery input must be a non-linked regular file")
def checksum(path):
    regular(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
manifest_path = recovery / "manifest.json"
regular(manifest_path)
if manifest_path.stat().st_size > 4 * 1024 * 1024:
    raise SystemExit("ERROR: Git recovery manifest is too large")
manifest = json.loads(manifest_path.read_text())
identity = manifest.get("git")
if manifest.get("version") != 1 or not isinstance(identity, dict):
    raise SystemExit("ERROR: No supported Git recovery identity in this payload")
bundle = recovery / "git.bundle"
if checksum(bundle) != identity.get("bundle_checksum"):
    raise SystemExit("ERROR: Git recovery bundle checksum mismatch")
index = recovery / "git-index"
if identity.get("index_checksum") is not None and checksum(index) != identity["index_checksum"]:
    raise SystemExit("ERROR: Git recovery index checksum mismatch")
object_format = identity.get("object_format", "sha1")
if object_format not in {"sha1", "sha256"}:
    raise SystemExit("ERROR: Unsupported Git object format")
object_id = re.compile(r"[0-9a-f]{%d}" % (40 if object_format == "sha1" else 64))
if not object_id.fullmatch(str(identity.get("head", ""))):
    raise SystemExit("ERROR: Invalid Git recovery HEAD")
if identity.get("recovery_format", 1) not in {1, 2}:
    raise SystemExit("ERROR: Unsupported Git recovery format")
shallow_commits = identity.get("shallow_commits", [])
if not isinstance(shallow_commits, list) or any(not isinstance(oid, str) or not object_id.fullmatch(oid) for oid in shallow_commits):
    raise SystemExit("ERROR: Invalid Git shallow recovery boundaries")
remote_config = identity.get("remote_config", [])
config_key = re.compile(r"(?:remote\..+\.(?:url|pushurl|fetch|mirror|tagopt)|branch\..+\.(?:remote|merge))")
if not isinstance(remote_config, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or not config_key.fullmatch(entry["key"]) or not isinstance(entry.get("value"), str) or "\0" in entry["value"] for entry in remote_config):
    raise SystemExit("ERROR: Invalid Git remote recovery configuration")
stash_entries = identity.get("stash_entries", [])
if not isinstance(stash_entries, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("object_id"), str) or not object_id.fullmatch(entry["object_id"]) or not isinstance(entry.get("message"), str) or "\0" in entry["message"] for entry in stash_entries):
    raise SystemExit("ERROR: Invalid Git stash recovery entries")
shared_name = identity.get("shared_index_name")
if shared_name is not None:
    if not isinstance(shared_name, str) or not re.fullmatch(r"sharedindex\.[0-9a-f]{40}|sharedindex\.[0-9a-f]{64}", shared_name):
        raise SystemExit("ERROR: Invalid shared Git index name")
    if checksum(recovery / "git-shared-index") != identity.get("shared_index_checksum"):
        raise SystemExit("ERROR: Shared Git index checksum mismatch")
if (project / ".git").exists() or (project / ".git").is_symlink():
    raise SystemExit("ERROR: Refusing an existing Git repository")
def git(*arguments):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "init.templateDir=", "-C", str(project), *arguments], env=environment, check=True, text=True, capture_output=True).stdout.strip()
git("init", "--object-format=" + object_format)
if shallow_commits:
    (project / ".git" / "shallow").write_text("\n".join(shallow_commits) + "\n", encoding="ascii")
git("bundle", "verify", str(bundle))
git("bundle", "unbundle", str(bundle))
for oid in shallow_commits:
    if git("cat-file", "-t", oid) != "commit":
        raise SystemExit("ERROR: Missing Git shallow recovery boundary")
for line in identity.get("refs", []):
    oid, separator, ref = str(line).partition(" ")
    if not separator or not object_id.fullmatch(oid) or not ref.startswith("refs/"):
        raise SystemExit("ERROR: Invalid Git recovery ref")
    git("check-ref-format", ref)
    if ref == "refs/stash" and stash_entries:
        continue
    git("update-ref", ref, oid)
for entry in reversed(stash_entries):
    git("update-ref", "--create-reflog", "-m", entry["message"], "refs/stash", entry["object_id"])
for entry in remote_config:
    git("config", "--local", "--add", entry["key"], entry["value"])
head_ref = identity.get("head_ref")
if head_ref:
    git("check-ref-format", head_ref)
    git("symbolic-ref", "HEAD", head_ref)
else:
    git("update-ref", "--no-deref", "HEAD", identity["head"])
if git("rev-parse", "HEAD") != identity["head"]:
    raise SystemExit("ERROR: Restored Git HEAD differs from the manifest")
if identity.get("index_checksum") is not None:
    if shared_name is not None:
        with (recovery / "git-shared-index").open("rb") as source, (project / ".git" / shared_name).open("xb") as destination:
            shutil.copyfileobj(source, destination)
        os.chmod(project / ".git" / shared_name, 0o600)
    with index.open("rb") as source, (project / ".git" / "index").open("xb") as destination:
        shutil.copyfileobj(source, destination)
    os.chmod(project / ".git" / "index", 0o600)
git("fsck", "--full")
print("GIT_READY " + str(project))
# Mapped links remain metadata until their target sources have been restored.
PY
        ;;
esac
