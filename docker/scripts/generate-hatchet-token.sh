#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${COMPOSE_DIR:-}" ]]; then
  COMPOSE_DIR="$(cd "$COMPOSE_DIR" && pwd)"
elif [[ -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
  COMPOSE_DIR="$SCRIPT_DIR"
elif [[ -f "$SCRIPT_DIR/../compose/docker-compose.yml" ]]; then
  COMPOSE_DIR="$(cd "$SCRIPT_DIR/../compose" && pwd)"
else
  echo "ERROR: Could not locate docker-compose.yml. Set COMPOSE_DIR and retry." >&2
  exit 1
fi

cd "$COMPOSE_DIR"

TENANT_ID="$(docker compose exec -T postgres psql -U admin -d hatchet -t -A \
  -c "SELECT id FROM \"Tenant\" LIMIT 1" 2>/dev/null | tr -d '[:space:]' || true)"

if [[ -z "$TENANT_ID" ]]; then
  echo "ERROR: Could not discover Hatchet tenant ID." >&2
  echo "Run after Hatchet infrastructure is healthy, then retry:" >&2
  echo "  docker compose run --rm --no-deps hatchet-setup-config /hatchet/hatchet-admin token create --config /hatchet/config --tenant-id <UUID>" >&2
  exit 1
fi

HATCHET_TOKEN="$(docker compose run --rm --no-deps hatchet-setup-config \
  /hatchet/hatchet-admin token create --config /hatchet/config \
  --tenant-id "$TENANT_ID" --expiresIn "${HATCHET_TOKEN_EXPIRES_IN:-87600h}" 2>/dev/null \
  | grep -oE 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
  | tail -n 1 || true)"

if [[ -z "$HATCHET_TOKEN" ]]; then
  echo "ERROR: Hatchet token generation failed." >&2
  exit 1
fi

if [[ -f .env ]] && grep -q '^HATCHET_CLIENT_TOKEN=' .env; then
  sed -i "s|^HATCHET_CLIENT_TOKEN=.*|HATCHET_CLIENT_TOKEN=$HATCHET_TOKEN|" .env
else
  printf 'HATCHET_CLIENT_TOKEN=%s\n' "$HATCHET_TOKEN" >> .env
fi

echo "Hatchet token generated and saved to $COMPOSE_DIR/.env"
