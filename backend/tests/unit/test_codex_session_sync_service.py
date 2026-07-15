from pathlib import Path


def test_periodic_service_closes_inactive_sessions() -> None:
    root = Path(__file__).resolve().parents[3]
    service = (root / "scripts" / "systemd" / "codex-session-sync.service").read_text(
        encoding="utf-8"
    )

    assert "--scan --close-inactive --verbose" in service
