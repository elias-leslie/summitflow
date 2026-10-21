# Runtime placement

Each project's `project.identity.json` is the canonical catalog for its unit
names, ports and deployment location. The project registry supplies checkout
location and lifecycle; it does not override runtime placement.

Projects running inside a Proxmox guest declare `runtime.deployment`:

```json
{
  "kind": "proxmox",
  "ssh_host": "configured-proxmox-ssh-alias",
  "vmid": 456,
  "user": "appuser",
  "uid": 1234
}
```

`ssh_host` uses existing authenticated SSH configuration for the Proxmox host.
The VM id and guest user identify the actual native user services. Secrets and
private keys stay outside the catalog. An omitted deployment retains local
placement; an invalid explicit deployment is rejected.

`guest_type` defaults to `qemu`; use `lxc` for containers. `manager` defaults to
`user`; use `system` for guest system services (which need no `user`/`uid`).
Stopped guests report stopped without inventing unit state. Recent logs come
from the guest journal; live guest log streaming is currently unavailable.

Runtime and `st service status` inspect those guest units through the QEMU
guest agent or LXC `pct exec`. Runtime labels the host and guest, and start/stop/restart and
auto-start controls act on that guest. Local port listeners are never killed
for remote controls. CPU/memory process metrics are omitted for these rows;
the Proxmox panel reports guest resources. A responding HTTP endpoint alone
cannot establish that a unit is running.

`st service start` and `stop` use the same placement. `rebuild` and its `restart`
alias refuse remote projects: the existing build/install workflow deploys
local units only. Remote app upgrades follow their recorded native cutover
procedure until an explicit remote release workflow is implemented. The catalog
guard prevents the old workstation deployment from being recreated.

Local Docker infrastructure rows inspect actual container state before reporting
health; a forwarded listening port cannot establish a running local container.
The installed stack's existing system unit is controlled through noninteractive
sudo, using the owner's routine root authority. A container action still affects
the whole stack. No owner tap or remote application release is created.
