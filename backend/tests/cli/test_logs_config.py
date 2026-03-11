import pytest

from cli.commands.logs_config import (
    SYSTEM_SERVICES,
    USER_SERVICES,
    get_service_list,
    validate_since,
)


def test_get_service_list_includes_portfolio_ai_user_service() -> None:
    """Portfolio AI logs should be reachable through the shared st logs service map."""
    user_svcs, system_svcs = get_service_list("portfolio-ai,portfolio-companion,redis")

    assert "portfolio-ai" in USER_SERVICES
    assert USER_SERVICES["portfolio-ai"] == "portfolio-backend.service"
    assert USER_SERVICES["portfolio-companion"] == "portfolio-dev-companion.service"
    assert user_svcs == ["portfolio-ai", "portfolio-companion"]
    assert system_svcs == ["redis"]


def test_get_service_list_all_includes_portfolio_ai() -> None:
    """The all-services view should not silently omit Portfolio AI."""
    user_svcs, system_svcs = get_service_list("all")

    assert "portfolio-ai" in user_svcs
    assert set(system_svcs) == set(SYSTEM_SERVICES)


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
