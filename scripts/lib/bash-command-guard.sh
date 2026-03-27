#!/usr/bin/env bash

if [[ "${SF_COMMAND_GUARD_DISABLE:-0}" == "1" ]]; then
  return 0
fi

if [[ -n "${SF_COMMAND_GUARD_PREV_BASH_ENV:-}" && -f "${SF_COMMAND_GUARD_PREV_BASH_ENV}" ]]; then
  # Preserve any pre-existing shell startup behavior, then layer the guard on top.
  # shellcheck disable=SC1090
  source "${SF_COMMAND_GUARD_PREV_BASH_ENV}"
fi

if [[ -z "${SF_COMMAND_GUARD_BIN:-}" || -z "${SF_COMMAND_GUARD_WORDS:-}" ]]; then
  return 0
fi

if [[ ! -x "${SF_COMMAND_GUARD_BIN}" ]]; then
  return 0
fi

case "${0##*/}" in
  dt|st|db|commit.sh|dev-tools.sh|rebuild.sh|restart.sh|shutdown.sh|worktree-services.sh)
    return 0
    ;;
esac

__sf_guard_call() {
  local command_name="$1"
  shift

  local reconstructed="$command_name"
  local arg
  for arg in "$@"; do
    reconstructed+=" $(printf '%q' "$arg")"
  done

  local output=""
  local status=0
  output="$(BASH_ENV= SF_COMMAND_GUARD_DISABLE=1 "${SF_COMMAND_GUARD_BIN}" --shell-command "$reconstructed" --cwd "$PWD" 2>&1)" || status=$?
  if [[ $status -eq 0 ]]; then
    command "$command_name" "$@"
    return $?
  fi
  printf '%s\n' "$output" >&2
  return "$status"
}

for __sf_word in ${SF_COMMAND_GUARD_WORDS}; do
  eval "${__sf_word}() { __sf_guard_call '${__sf_word}' \"\$@\"; }"
done

unset __sf_word
