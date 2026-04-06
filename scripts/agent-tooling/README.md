# Agent Tooling Bootstrap

Tracked bootstrap assets for the mixed local agent environment:

- `scripts/setup-agent-tooling.sh` clones/upgrades the shared Claude/Codex config repos and installs the wrapper

The actual Claude and Codex home directories remain in their dedicated config repos:

- `git@github.com:elias-leslie/claude-config.git`
- `git@github.com:elias-leslie/codex-config.git`

Those repos own the durable hook/config content, including the Codex wrapper entrypoint. SummitFlow owns the deployment bootstrap and observability wiring.
