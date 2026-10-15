"""st vm power operations report what PVE actually did."""

import httpx
import pytest

from cli.lib import proxmox
from cli.lib.proxmox import ProxmoxClient, ProxmoxConfig, ProxmoxError


def client() -> ProxmoxClient:
    return ProxmoxClient(ProxmoxConfig("https://fixture", "id", "secret", "node"))


@pytest.mark.parametrize("action", ["start", "stop"])
def test_power_waits_for_the_task_and_surfaces_its_failure(monkeypatch, action):
    # PVE accepts a start of a running VM and fails only its task; "starting" was printed regardless.
    pve = client()
    monkeypatch.setattr(pve, "request", lambda method, path, **_: f"UPID:{path}")
    waited = []

    def wait_task(upid, **_):
        waited.append(upid)
        raise ProxmoxError("Proxmox task failed: VM 120 already running")

    monkeypatch.setattr(pve, "wait_task", wait_task)
    with pytest.raises(ProxmoxError, match="already running"):
        getattr(pve, action)("120")
    assert waited == [f"UPID:/nodes/node/qemu/120/status/{action}"]


def test_permission_403_names_the_pools_that_grant_vm_rights(monkeypatch):
    monkeypatch.setattr(proxmox, "_tls_context", lambda _: None)
    body = '{"message":"Permission check failed (/vms/120, VM.PowerMgmt)\\n","data":null}'
    monkeypatch.setattr(proxmox.httpx, "request", lambda *a, **k: httpx.Response(403, text=body))
    with pytest.raises(ProxmoxError) as failure:
        client().start("120")
    message = str(failure.value)
    assert "/vms/120, VM.PowerMgmt" in message
    assert "'summitflow'" in message and f"'{proxmox.POWER_POOL}'" in message
