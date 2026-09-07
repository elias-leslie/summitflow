"""Guest-agent recovery uses SSH only for the named Linux VM."""
from types import SimpleNamespace

from typer.testing import CliRunner

from cli.commands import vm


def test_repair_agent_checks_guest_name_before_restart(monkeypatch):
    client = SimpleNamespace(config_get=lambda _: {"name": "test-linux", "ostype": "l26"})
    monkeypatch.setattr(vm, "_client", lambda: client)
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="active\n", stderr="")
    monkeypatch.setattr("subprocess.run", run)
    result = CliRunner().invoke(vm.app, ["repair-agent", "112", "--ssh-target", "operator@10.0.4.50"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[-2:] == ["operator@10.0.4.50", "sh -s"]
    script = kwargs["input"]
    assert script.index("hostname -s") < script.index("systemctl restart qemu-guest-agent")
    assert "test-linux" in script
    assert "sudo -n" in script


def test_repair_agent_rejects_windows_before_ssh(monkeypatch):
    monkeypatch.setattr(vm, "_client", lambda: SimpleNamespace(config_get=lambda _: {"name": "test-win", "ostype": "win11"}))
    result = CliRunner().invoke(vm.app, ["repair-agent", "110", "--ssh-target", "operator@10.0.4.29"])
    assert result.exit_code != 0
    assert "Linux" in result.output
