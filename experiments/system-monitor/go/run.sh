#!/usr/bin/env bash
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
binary="$here/.build/collector"
if [[ ! -x "$binary" ]] || [[ -n $(find "$here" -maxdepth 1 \( -name '*.go' -o -name 'go.mod' -o -name 'go.sum' \) -newer "$binary" -print -quit) ]]; then
  "$here/build.sh"
fi
exec "$binary" "$@"
