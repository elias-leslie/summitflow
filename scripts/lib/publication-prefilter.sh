# shellcheck shell=bash
# Pure-shell prefilter for the PreToolUse publication guard (no forks).
#
# publication_prefilter_skip PAYLOAD returns 0 only when the Python guard would
# certainly allow the call: a Bash tool call whose command names nothing any
# policy inspects. Anything else (other tools, odd payload shapes, escapes the
# shell cannot decode, a trigger term) returns 1 and the full guard decides.
#
# Trigger terms are the SAFE UNION of every executable, subcommand and marker
# checked by backend/app/services/_publication_guard.py (publication and
# hook-disable), the irreversible set in _command_guard_helpers.py
# (irreversible_system_decision, git_invocation, ssh remote commands) and the
# degraded fallback in publication_guard_entry.py. Adding an executable to any
# of those policies means adding it here; test_publication_prefilter.py
# replays every denied fixture through this filter.
#
# The command is matched twice: once with quotes and backslashes deleted
# (shlex joins r''m and \rm into rm) and once with them turned into spaces
# (the fallback's regex word boundaries). Wrappers (sudo, env, exec, uv run,
# xargs, bash -c, eval, $(...), heredocs) need no term of their own: the
# command they run is still text inside the same string.

_PF_WORDS='git|jj|gh|curl|wget|https?|xhs?|ssh|rm|find|btrfs|btrbk|restic|rclone|dmsetup|dd|wipefs|blkdiscard|mke2fs|mkswap|mkdosfs|mkntfs|mkexfatfs|parted|sgdisk|fdisk|sfdisk|gdisk|cfdisk|cryptsetup|qm|pct|pvesm|pvesh|zfs|zpool|lvremove|vgremove|pvremove|eval|base64'
_PF_TRIGGER="(^|[^a-z0-9_])(${_PF_WORDS})([^a-z0-9_]|\$)|(^|[^a-z0-9_])mkfs|hook|no-verify|sf_command_guard_disable|git_allow_secret|secretguard_disable|approve-deletion|api\\.github\\.com"

# Bash's regex engine backtracks superlinearly on long escape-heavy payloads;
# anything larger goes straight to Python so the hook never nears its timeout.
_PF_MAX_BYTES=32768

_PF_WS='[[:space:]]*'
_PF_BASH="\"tool_name\"${_PF_WS}:${_PF_WS}\"Bash\""
_PF_INPUT="\"tool_input\"${_PF_WS}:${_PF_WS}[{]"
_PF_CMD_KEY="\"cmd\"${_PF_WS}:"
_PF_TWO_COMMANDS="\"command\"${_PF_WS}:.*\"command\"${_PF_WS}:"
_PF_COMMAND="\"command\"${_PF_WS}:${_PF_WS}\"(([^\"\\\\]|\\\\.)*)\""

publication_prefilter_skip() {
    local LC_ALL=C payload="$1" command
    (( ${#payload} <= _PF_MAX_BYTES )) || return 1
    [[ $payload =~ $_PF_BASH && $payload =~ $_PF_INPUT ]] || return 1
    # Exactly one non-empty "command" string and no "cmd": the guard reads tool_input.command.
    [[ $payload =~ $_PF_CMD_KEY || $payload =~ $_PF_TWO_COMMANDS ]] && return 1
    [[ $payload =~ $_PF_COMMAND ]] || return 1
    command="${BASH_REMATCH[1]}"
    [[ $command =~ [^[:space:]] ]] || return 1
    # \uXXXX escapes and $'...' quoting hide text from a plain scan; so do the
    # non-ASCII letters Python lower()/re.I fold to ASCII (U+0130 U+0131 U+017F U+212A).
    case "$command" in
        *'\u'* | *"\$'"* | *$'\xc4\xb0'* | *$'\xc4\xb1'* | *$'\xc5\xbf'* | *$'\xe2\x84\xaa'*) return 1 ;;
    esac
    command="${command,,}"
    command="${command//'\\'/$'\x01'}"
    command="${command//'\n'/ }"
    command="${command//'\t'/ }"
    command="${command//'\r'/ }"
    command="${command//'\b'/ }"
    command="${command//'\f'/ }"
    command="${command//'\/'//}"
    command="${command//'\"'/\"}"
    local joined="${command//[$'\x01'\"\']/}" spaced="${command//[$'\x01'\"\']/ }"
    [[ $joined =~ $_PF_TRIGGER || $spaced =~ $_PF_TRIGGER ]] && return 1
    return 0
}
