"""Redis URL database selection tests."""

from __future__ import annotations

import pytest
import redis

from app.services.redis_pool import create_redis_client


@pytest.mark.parametrize(
    ("url", "expected_db"),
    [
        ("redis://localhost:6379", 1),
        ("redis://localhost:6379/0", 0),
        ("redis://localhost:6379/4", 4),
        ("redis://localhost:6379?db=9", 9),
    ],
)
def test_create_redis_client_defaults_only_when_url_has_no_database(
    url: str,
    expected_db: int,
) -> None:
    client = create_redis_client(url)

    assert client.connection_pool.connection_kwargs["db"] == expected_db


def test_create_redis_client_preserves_password_and_query_parameters() -> None:
    client = create_redis_client(
        "redis://:p%40ss@redis.internal:6380/2?socket_timeout=5",
        socket_timeout=1,
    )
    kwargs = client.connection_pool.connection_kwargs

    assert kwargs["db"] == 2
    assert kwargs["password"] == "p@ss"
    assert kwargs["host"] == "redis.internal"
    assert kwargs["port"] == 6380
    assert kwargs["socket_timeout"] == 5.0


def test_create_redis_client_preserves_tls_scheme_and_database() -> None:
    client = create_redis_client(
        "rediss://redis.example:6380/7?ssl_cert_reqs=none",
    )
    kwargs = client.connection_pool.connection_kwargs

    assert kwargs["db"] == 7
    assert client.connection_pool.connection_class is redis.SSLConnection
    assert kwargs["ssl_cert_reqs"] == "none"
