from cli.commands.logs_config import SYSTEM_SERVICES, USER_SERVICES, get_service_list


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
