# Host maintenance and recovery boundary

The host uses two deliberately separate maintenance layers.

## Native, independent layer

These controls must continue to work when SummitFlow, PostgreSQL, Hatchet, or
Agent Hub is unavailable. `scripts/install-host-maintenance.sh` installs a copy
of the standard-library-only guardian into `/usr/local/libexec` and installs
native systemd timers for:

- 15-minute disk, Btrfs, SMART, Veeam, Docker, PostgreSQL, and core-container checks;
- direct Docker Compose reconciliation of shared infrastructure, without `st` or API dependencies;
- daily age-gated Docker/cache/log maintenance;
- weekly/monthly NVMe self-tests;
- monthly Btrfs checksum scrubs;
- bounded journald and Docker log growth.

Current state is written atomically to
`/var/lib/summitflow-host-guardian/status.json`. State transitions are appended
to `events.jsonl` so the Telegram delivery layer can catch up after a database
or network outage.

## SummitFlow-owned layer

SummitFlow remains responsible for application-aware concerns:

- backup source schedules and retention with minimum restore-point safeguards;
- Veeam job policy and restore-point reporting;
- verified infrastructure/project archives and restore drills;
- PostgreSQL bloat analysis and targeted `VACUUM ANALYZE`;
- application health, runtime hygiene, dashboards, and notification records.

The native guardian may observe and restart foundational services, but it does
not query SummitFlow's database or call its API. SummitFlow may consume the
guardian's JSON status, but native maintenance never consumes SummitFlow.

## Schedule

| Control | Schedule |
|---|---|
| Host guard and core reconcile | every 15 minutes |
| Host retention maintenance | daily around 05:15 |
| Veeam system image | daily at 02:00 |
| SummitFlow daily maintenance | daily at 04:00 |
| Managed restore tests | Sunday at 06:00 |
| Btrfs scrub | first Sunday around 08:00 |
| NVMe short self-test | Saturday around 03:00 |
| NVMe extended self-test | first Saturday around 00:30 |

## Operator commands

```bash
sudo systemctl start summitflow-host-guardian.service
sudo systemctl start summitflow-host-maintenance.service
sudo systemctl start summitflow-btrfs-scrub.service
cat /var/lib/summitflow-host-guardian/status.json
systemctl list-timers 'summitflow-*'
journalctl -u summitflow-host-guardian.service -n 100
```

Do not manually delete Veeam chain files, named Docker volumes, PostgreSQL data,
or Btrfs snapshots. Use the owning retention/recovery workflow.
