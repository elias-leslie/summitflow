#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
bin=target/release/summitflow-host-collector-rust
if [[ ! -x "$bin" || Cargo.toml -nt "$bin" || Cargo.lock -nt "$bin" || src/main.rs -nt "$bin" ]]; then
  ./build.sh
fi
exec "$bin" "$@"
