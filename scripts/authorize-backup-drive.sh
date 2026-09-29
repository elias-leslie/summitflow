#!/usr/bin/env bash
# Run by the owner in a private terminal. No OAuth material is accepted in args.
set +x
set -euo pipefail

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

[[ $# -eq 0 ]] || fail 'This command takes no arguments; enter credentials only at its private prompts.'
[[ -t 0 && -t 1 ]] || fail 'Run from a private interactive terminal, not a pipe or agent transcript.'
command -v rclone >/dev/null || fail 'Pinned rclone 1.75.1 is not on PATH.'
rclone_version=$(rclone version)
[[ "$rclone_version" == 'rclone v1.75.1' || "$rclone_version" == 'rclone v1.75.1'$'\n'* ]] || fail 'Expected rclone 1.75.1.'

state_root=${XDG_STATE_HOME:-"$HOME/.local/state"}
[[ "$state_root" == /* ]] || fail 'XDG_STATE_HOME must be absolute.'
key_directory=${SUMMITFLOW_BACKUP_KEY_DIR:-"$state_root/summitflow/backup-keys"}
[[ "$key_directory" == /* && "$key_directory" != / && -d "$key_directory" && ! -L "$key_directory" ]] || fail 'The canonical private backup-key directory is unavailable.'
[[ $(stat -c '%u:%a' -- "$key_directory") == "$(id -u):700" ]] || fail 'The backup-key directory must be owned by this user and mode 700.'

config=$key_directory/summitflow-drive.conf
# Discard inherited tool overrides so the approved config controls the OAuth flow.
while IFS= read -r variable; do
    if [[ "$variable" == RCLONE_* || "$variable" == RESTIC_* ]]; then
        unset "$variable"
    fi
done < <(compgen -v)

[[ ! -L "$config" ]] || fail 'The rclone config must not be a symlink.'
if [[ -e "$config" ]]; then
    [[ -f "$config" && $(stat -c '%u:%a' -- "$config") == "$(id -u):600" ]] || fail 'The existing rclone config is not a private user-owned regular file.'
    [[ $(rclone listremotes --config "$config") == 'summitflow-drive:' ]] || fail 'The existing private config is not the dedicated SummitFlow Drive remote.'
    printf 'Resuming the private SummitFlow Drive authorization. No existing config is overwritten.\n'
else
    printf 'Use your own Google OAuth Desktop client for the same Drive account.\n'
    printf 'This remote requests drive.file access, limited to files created by this app.\n'
    IFS= read -r -s -p 'Google OAuth client ID (hidden): ' client_id </dev/tty || fail 'Client ID input was interrupted.'
    printf '\n' >/dev/tty
    IFS= read -r -s -p 'Google OAuth client secret (hidden): ' client_secret </dev/tty || fail 'Client secret input was interrupted.'
    printf '\n' >/dev/tty
    [[ "$client_id" =~ ^[A-Za-z0-9._-]+$ && "$client_secret" =~ ^[A-Za-z0-9._-]+$ ]] || fail 'Client ID and secret must be nonempty single-line Google OAuth values.'
    umask 077
    (set -C; printf '[summitflow-drive]\ntype = drive\nscope = drive.file\nclient_id = %s\nclient_secret = %s\n' "$client_id" "$client_secret" > "$config") || fail 'Could not create the private rclone config.'
    unset client_id client_secret
fi
[[ $(stat -c '%u:%a' -- "$config") == "$(id -u):600" ]] || fail 'The rclone config is not a private user-owned file.'

printf 'Choose Y for local browser authentication. Never choose N: headless instructions can contain the client secret.\n'
printf 'Complete Google consent in the browser yourself. Do not paste a token into chat.\n'
rclone config reconnect summitflow-drive: --config "$config" || fail 'OAuth did not finish. Run this script again to resume securely.'
rclone lsf summitflow-drive: --config "$config" --max-depth 1 >/dev/null || fail 'OAuth finished but read access could not be verified.'
[[ $(stat -c '%u:%a' -- "$config") == "$(id -u):600" ]] || fail 'rclone changed the config ownership or permissions; stop before using it for backup.'
printf 'AUTH_READY remote=summitflow-drive config=%s\n' "$config"
