restic-append (CT 160) - append-only copy of davion-sidarli backups
====================================================================

What it is
  A third copy of the workstation's local restic repository (T7), kept on
  local-lvm in a 150 GB thin volume (CT 160 mp0 -> /srv/restic). The CT has
  no network. The workstation reaches it only through a forced-command SSH
  key on this host (/usr/local/sbin/restic-append-serve), which runs
  "rclone serve restic --stdio --append-only" inside the CT. That key can add
  snapshots and read /var/lib/restic-append/status.json, nothing else.

Retention
  Runs only here: restic-append-maintain.timer (weekly, Sun ~05:15) inside the
  CT. Same per-source windows as SummitFlow (never below 7 days, newest three
  per source kept). A circuit breaker refuses any run that would delete more
  than normal retention (>25% of all snapshots, >50% of one source, or an
  unexplained >10% drop) and records an alert in the status file instead.

FIRST THING TO SHRINK if davion-gem needs space
  This copy is the most expendable data on this host: the T7 and Google Drive
  copies remain. In order of preference:
    1. Lower retention: edit /etc/restic-append/policy.json in CT 160
       (pct exec 160 -- ...), then: pct exec 160 -- systemctl start restic-append-maintain
    2. Stop it entirely: pct stop 160 (backups continue; SummitFlow reports
       the PVE copy as stale).
    3. Reclaim the space: remove CT 160 (pct destroy 160). Only the extra
       copy is lost. Re-create with summitflow/scripts/pve-restic-append/install.sh.

Status
  pct exec 160 -- cat /var/lib/restic-append/status.json
  Workstation view: ~/.local/state/summitflow/backup-safety/status.json (pve_copy).
