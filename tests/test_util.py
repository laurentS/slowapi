import pytest
from starlette.requests import Request

from slowapi.util import get_ipaddr, get_remote_address


def build_request(
    headers: dict[str, str] | None = None,
    client: tuple[str, int] | None = ("192.168.1.100", 50000),
) -> Request:
    # ASGI spec: Header name MUST be lowercased bytes
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": client,
    }
    return Request(scope)


@pytest.mark.parametrize(
    "headers,client,expected_ip",
    [
        # Standard HTTP X-Forwarded-For (single IP)
        (
            {"X-Forwarded-For": "198.51.100.1"},
            ("10.0.0.1", 1234),
            "198.51.100.1",
        ),
        # Lowercase header
        (
            {"x-forwarded-for": "198.51.100.2"},
            ("10.0.0.1", 1234),
            "198.51.100.2",
        ),
        # Multiple comma-separated proxy IPs (returns client IP, trimmed)
        (
            {"X-Forwarded-For": "203.0.113.195, 70.41.3.18, 150.172.238.178"},
            ("10.0.0.1", 1234),
            "203.0.113.195",
        ),
        (
            {"X-Forwarded-For": "  203.0.113.196  , 70.41.3.18"},
            ("10.0.0.1", 1234),
            "203.0.113.196",
        ),
        # Backward compatibility with existing mock tests using underscore
        (
            {"X_FORWARDED_FOR": "127.0.0.2"},
            ("10.0.0.1", 1234),
            "127.0.0.2",
        ),
        # Precedence: standard header over legacy underscore
        (
            {
                "X-Forwarded-For": "198.51.100.5",
                "X_FORWARDED_FOR": "127.0.0.9",
            },
            ("10.0.0.1", 1234),
            "198.51.100.5",
        ),
        # Empty or whitespace header falls back to client host
        ({"X-Forwarded-For": ""}, ("192.168.1.100", 50000), "192.168.1.100"),
        (
            {"X-Forwarded-For": "   "},
            ("192.168.1.100", 50000),
            "192.168.1.100",
        ),
        # No header, fallback to client host
        ({}, ("192.168.1.100", 50000), "192.168.1.100"),
        # No header, no client info -> fallback to 127.0.0.1
        ({}, None, "127.0.0.1"),
    ],
)
def test_get_ipaddr(
    headers: dict[str, str],
    client: tuple[str, int] | None,
    expected_ip: str,
) -> None:
    req = build_request(headers=headers, client=client)
    assert get_ipaddr(req) == expected_ip


@pytest.mark.parametrize(
    "client,expected_ip",
    [
        (("192.168.1.50", 12345), "192.168.1.50"),
        (None, "127.0.0.1"),
    ],
)
def test_get_remote_address(
    client: tuple[str, int] | None,
    expected_ip: str,
) -> None:
    req = build_request(
        headers={"X-Forwarded-For": "198.51.100.1"},
        client=client,
    )
    # get_remote_address ignores X-Forwarded-For and checks client host
    assert get_remote_address(req) == expected_ip
