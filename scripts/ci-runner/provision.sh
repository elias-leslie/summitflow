#!/usr/bin/env bash
# Idempotent setup for the Proxmox CI/acceptance runner (VM cloned from the
# agent-ready template). Run as the runner user with passwordless sudo:
#   NODE_VERSION=24.14.1 PNPM_VERSION=10.28.0 UV_VERSION=0.11.9 bash provision.sh
# Database passwords are generated on the VM and stay there.
set -euo pipefail

NODE_VERSION="${NODE_VERSION:?NODE_VERSION required}"
PNPM_VERSION="${PNPM_VERSION:?PNPM_VERSION required}"
UV_VERSION="${UV_VERSION:?UV_VERSION required}"
RUNNER_USER="$(id -un)"
PROJECTS_ROOT=/srv/workspaces/projects
ENV_FILE="$HOME/.env.local"

sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  build-essential ca-certificates curl git rsync xz-utils jq \
  postgresql-16 postgresql-16-pgvector >/dev/null

# Same path as the workstation: check configs reference /usr/local/bin/node.
if [[ "$(/usr/local/bin/node --version 2>/dev/null)" != "v$NODE_VERSION" ]]; then
  archive="node-v$NODE_VERSION-linux-x64.tar.xz"
  curl -fsSLo "/tmp/$archive" "https://nodejs.org/dist/v$NODE_VERSION/$archive"
  sudo tar -xJf "/tmp/$archive" -C /usr/local --strip-components=1
  rm -f "/tmp/$archive"
fi
sudo /usr/local/bin/corepack enable --install-directory /usr/local/bin
/usr/local/bin/corepack prepare "pnpm@$PNPM_VERSION" --activate >/dev/null

if [[ "$("$HOME/.local/bin/uv" --version 2>/dev/null)" != "uv $UV_VERSION"* ]]; then
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_NO_MODIFY_PATH=1 sh >/dev/null
fi

# Workstation paths are mirrored so resolved tool paths match.
sudo install -d -o "$RUNNER_USER" -g "$RUNNER_USER" /srv/workspaces "$PROJECTS_ROOT" /srv/ci /srv/ci/locks

# Test databases on this disposable server: like CI and the native fixture, the
# test role is superuser (pgvector and xdist worker databases need it).
# Never the workstation's credentials.
if [[ ! -f "$ENV_FILE" ]] || ! grep -q '^TEST_DATABASE_URL=' "$ENV_FILE"; then
  app_password="$(openssl rand -hex 24)"
  admin_password="$(openssl rand -hex 24)"
  sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'summitflow_app') THEN
    CREATE ROLE summitflow_app LOGIN SUPERUSER;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ci_admin') THEN
    CREATE ROLE ci_admin LOGIN SUPERUSER;
  END IF;
END \$\$;
ALTER ROLE summitflow_app SUPERUSER PASSWORD '$app_password';
ALTER ROLE ci_admin PASSWORD '$admin_password';
SQL
  umask 077
  {
    echo "TEST_DATABASE_URL=postgresql://summitflow_app:$app_password@localhost:5432/summitflow_test"
    echo "DATABASE_URL=postgresql://summitflow_app:$app_password@localhost:5432/summitflow_test"
    echo "DATABASE_ADMIN_URL=postgresql://ci_admin:$admin_password@localhost:5432/postgres"
  } >"$ENV_FILE"
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'summitflow_test'" | grep -q 1; then
  sudo -u postgres createdb -O summitflow_app summitflow_test
fi
sudo -u postgres psql -q -c 'ALTER ROLE summitflow_app SUPERUSER'

echo "runner ready: node $(/usr/local/bin/node --version) pnpm $(/usr/local/bin/pnpm --version) $("$HOME/.local/bin/uv" --version)"
