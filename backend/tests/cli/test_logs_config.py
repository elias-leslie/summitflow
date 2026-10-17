import pytest

from cli.commands.logs_config import (
    SYSTEM_SERVICES,
    USER_SERVICES,
    get_service_list,
    validate_since,
)

_IDENTITIES = [
    {"project": {"id": "portfolio-ai"}, "services": {
        "backend": "portfolio-backend.service", "frontend": "portfolio-frontend.service",
        "default_workers": ["portfolio-hatchet-worker.service"], "optional_workers": []}},
    {"project": {"id": "agent-hub"}, "services": {
        "backend": "agent-hub-backend.service", "frontend": "agent-hub-frontend.service",
        "default_workers": ["agent-hub-hatchet-ops-worker.service"],
        "optional_workers": ["agent-hub-hatchet-agent-worker.service"]}},
    {"project": {"id": "monkey-fight"}, "services": {
        "backend": "", "frontend": "monkey-fight.service", "default_workers": [], "optional_workers": []}},
    {"project": {"id": "tether"}, "services": {"backend": "tether@default.service", "frontend": ""}},
    {"project": {"id": "docs-only"}},
]


@pytest.fixture
def identity_services(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    from app import project_identity
    from cli.commands import logs_config

    monkeypatch.setattr(project_identity, "list_project_identities", lambda: _IDENTITIES)
    services = logs_config._identity_user_services()
    monkeypatch.setattr(logs_config, "USER_SERVICES", services)
    return services


def test_user_services_come_from_identity(identity_services: dict[str, str]) -> None:
    assert identity_services == {
        "portfolio-ai": "portfolio-backend.service",
        "portfolio-ai-web": "portfolio-frontend.service",
        "portfolio-ai-worker": "portfolio-hatchet-worker.service",
        "portfolio-hatchet-worker": "portfolio-hatchet-worker.service",
        "agent-hub": "agent-hub-backend.service",
        "agent-hub-web": "agent-hub-frontend.service",
        "agent-hub-worker": "agent-hub-hatchet-ops-worker.service",
        "agent-hub-hatchet-ops-worker": "agent-hub-hatchet-ops-worker.service",
        "agent-hub-hatchet-agent-worker": "agent-hub-hatchet-agent-worker.service",
        "monkey-fight": "monkey-fight.service",
        "monkey-fight-web": "monkey-fight.service",
        "tether": "tether@default.service",
    }


def test_get_service_list_splits_user_and_system_services(identity_services: dict[str, str]) -> None:
    user_svcs, system_svcs = get_service_list("portfolio-ai,agent-hub-worker,redis,test2")
    assert user_svcs == ["portfolio-ai", "agent-hub-worker"]
    assert system_svcs == ["redis"]

    user_svcs, system_svcs = get_service_list("all")
    assert user_svcs == list(identity_services)
    assert set(system_svcs) == set(SYSTEM_SERVICES)


def test_real_identities_cover_summitflow() -> None:
    assert USER_SERVICES["summitflow"] == "summitflow-backend.service"
    assert USER_SERVICES["summitflow-worker"] == "summitflow-hatchet-worker.service"


@pytest.mark.parametrize(
    "shorthand,expected",
    [
        ("2m", "2 minutes ago"),
        ("1h", "1 hours ago"),
        ("5min", "5 minutes ago"),
        ("3d", "3 days ago"),
        ("1hr", "1 hours ago"),
    ],
)
def test_validate_since_expands_shorthand(shorthand: str, expected: str) -> None:
    """Shorthand like '2m' should expand to journalctl-compatible format."""
    assert validate_since(shorthand) == expected


def test_validate_since_preserves_long_form() -> None:
    """Long-form values like '30 minutes ago' should pass through unchanged."""
    assert validate_since("30 minutes ago") == "30 minutes ago"
    assert validate_since("today") == "today"


def test_validate_since_rejects_invalid_input() -> None:
    """Invalid inputs should fall back to the default 30-minute window."""
    assert validate_since("garbage") == "30 minutes ago"
    assert validate_since("2x") == "30 minutes ago"
