# Isolated VM service access

`st vm forward 125 8080 --json` exposes a running managed lab guest's service on
workstation loopback. Add `--to-vm 100` to expose the same service on the managed
browser VM's loopback. Use the returned `local_url` on the workstation and
`destination_url` inside the destination VM. Repeating the same VM, service port
and destination reuses its live transport.

`st vm forward-close ID --json` closes the exact SSH processes recorded for that
transport. A dead or reused PID is never signalled. Runtime records and SSH control
sockets are private to the invoking user and disappear with its runtime directory.

The command uses existing scoped SSH configuration, including guest usernames and
keys. It overrides `ClearAllForwardings` for its own connections only, disables
agent and X11 forwarding, and binds every exposed endpoint to `127.0.0.1`.
It changes no routes, firewalls, Proxmox settings or SSH configuration. Source VMs
must be running non-template QEMU guests in the existing lab pool.
Their address must fall within Nightshift's
configured lab CIDRs; SSH hostname checks bind both connections to the selected VMs.

The default boundary data comes from the sibling Nightshift checkout's
`deploy/boundary-net/net.json`. The pool follows the existing Proxmox client setting.
A port allocation race or SSH error is reported without
opening a broader connection or retrying against another guest.
