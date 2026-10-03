import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from slowapi import Limiter
from slowapi.util import get_remote_address
from tests import TestSlowapi


BOOLEAN_SETTINGS = (
    ("RATELIMIT_ENABLED", "enabled"),
    ("RATELIMIT_HEADERS_ENABLED", "_headers_enabled"),
    ("RATELIMIT_SWALLOW_ERRORS", "_swallow_errors"),
    ("RATELIMIT_IN_MEMORY_FALLBACK_ENABLED", "_in_memory_fallback_enabled"),
)


def test_import():
    import slowapi  # noqa: F401


@pytest.fixture
def config_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for setting, _ in BOOLEAN_SETTINGS:
        monkeypatch.delenv(setting, raising=False)
    return tmp_path


@pytest.mark.parametrize(
    "value, expected",
    [
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("true", True),
        ("TRUE", True),
        ("1", True),
    ],
)
def test_boolean_environment_values(config_environment, monkeypatch, value, expected):
    for setting, _ in BOOLEAN_SETTINGS:
        monkeypatch.setenv(setting, value)

    limiter = Limiter(key_func=get_remote_address, enabled=False)

    for _, attribute in BOOLEAN_SETTINGS:
        assert getattr(limiter, attribute) is expected


@pytest.mark.parametrize("enabled", [False, True])
def test_boolean_constructor_values_without_config(config_environment, enabled):
    limiter = Limiter(
        key_func=get_remote_address,
        enabled=enabled,
        headers_enabled=enabled,
        swallow_errors=enabled,
        in_memory_fallback_enabled=enabled,
    )

    for _, attribute in BOOLEAN_SETTINGS:
        assert getattr(limiter, attribute) is enabled


@pytest.mark.parametrize("filename", [None, "limits.env"])
def test_false_boolean_values_from_config_file(config_environment, filename):
    config_file = config_environment / (filename or ".env")
    config_file.write_text(
        "\n".join(f"{setting}=false" for setting, _ in BOOLEAN_SETTINGS)
    )

    limiter = Limiter(
        key_func=get_remote_address, enabled=False, config_filename=filename
    )

    for _, attribute in BOOLEAN_SETTINGS:
        assert getattr(limiter, attribute) is False


@pytest.mark.parametrize("setting", [setting for setting, _ in BOOLEAN_SETTINGS])
def test_invalid_boolean_config_is_rejected(config_environment, monkeypatch, setting):
    monkeypatch.setenv(setting, "invalid")

    with pytest.raises(ValueError, match=setting):
        Limiter(key_func=get_remote_address, enabled=False)


class TestBooleanConfig(TestSlowapi):
    @pytest.mark.parametrize("value", ["false", "true"])
    def test_headers_configuration_on_responses(
        self, config_environment, monkeypatch, build_starlette_app, value
    ):
        monkeypatch.setenv("RATELIMIT_HEADERS_ENABLED", value)
        app, limiter = build_starlette_app()

        @limiter.limit("1/minute")
        def endpoint(request: Request):
            return PlainTextResponse("test")

        app.add_route("/test", endpoint)
        rate_headers = {
            "x-ratelimit-limit",
            "x-ratelimit-remaining",
            "x-ratelimit-reset",
            "retry-after",
        }

        with TestClient(app) as client:
            for status in (200, 429):
                response = client.get("/test")
                assert response.status_code == status
                if value == "false":
                    assert rate_headers.isdisjoint(response.headers)
                else:
                    assert rate_headers.issubset(response.headers)

    @pytest.mark.parametrize(
        "setting, value, status",
        [
            ("RATELIMIT_SWALLOW_ERRORS", "false", 503),
            ("RATELIMIT_IN_MEMORY_FALLBACK_ENABLED", "false", 503),
            ("RATELIMIT_IN_MEMORY_FALLBACK_ENABLED", "true", 200),
        ],
    )
    def test_storage_error_configuration(
        self,
        config_environment,
        monkeypatch,
        build_starlette_app,
        setting,
        value,
        status,
    ):
        monkeypatch.setenv(setting, value)
        app, limiter = build_starlette_app()

        def unavailable_storage(*args, **kwargs):
            raise ConnectionError("storage unavailable")

        monkeypatch.setattr(limiter._limiter, "hit", unavailable_storage)

        def handle_storage_error(request: Request, exc: ConnectionError):
            return PlainTextResponse("storage unavailable", status_code=503)

        app.add_exception_handler(ConnectionError, handle_storage_error)

        @limiter.limit("1/minute")
        def endpoint(request: Request):
            return PlainTextResponse("test")

        app.add_route("/test", endpoint)

        with TestClient(app) as client:
            assert client.get("/test").status_code == status
            fallback_enabled = (
                setting == "RATELIMIT_IN_MEMORY_FALLBACK_ENABLED" and value == "true"
            )
            assert limiter._storage_dead is fallback_enabled
            assert client.get("/test").status_code == (
                429 if fallback_enabled else status
            )
