import hiro  # type: ignore
import pytest  # type: ignore
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.testclient import TestClient

from slowapi.util import get_ipaddr
from tests import TestSlowapi


class TestDecorators(TestSlowapi):
    def test_single_decorator(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        @app.get("/t1")
        @limiter.limit("5/minute")
        async def t1(request: Request):
            return PlainTextResponse("test")

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429

    def test_single_decorator_with_headers(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr, headers_enabled=True)

        @app.get("/t1")
        @limiter.limit("5/minute")
        async def t1(request: Request):
            return PlainTextResponse("test")

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429
            assert (
                response.headers.get("X-RateLimit-Limit") is not None if i < 5 else True
            )
            assert response.headers.get("Retry-After") is not None if i < 5 else True

    def test_single_decorator_not_response(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        @app.get("/t1")
        @limiter.limit("5/minute")
        async def t1(request: Request, response: Response):
            return {"key": "value"}

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429

    def test_single_decorator_not_response_with_headers(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr, headers_enabled=True)

        @app.get("/t1")
        @limiter.limit("5/minute")
        async def t1(request: Request, response: Response):
            return {"key": "value"}

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429
            assert (
                response.headers.get("X-RateLimit-Limit") is not None if i < 5 else True
            )
            assert response.headers.get("Retry-After") is not None if i < 5 else True

    def test_multiple_decorators(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        @app.get("/t1")
        @limiter.limit(
            "100 per minute", lambda: "test"
        )  # effectively becomes a limit for all users
        @limiter.limit("50/minute")  # per ip as per default key_func
        async def t1(request: Request):
            return PlainTextResponse("test")

        with hiro.Timeline().freeze() as timeline:
            cli = TestClient(app)
            for i in range(0, 100):
                response = cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.2"})
                assert response.status_code == 200 if i < 50 else 429
            for i in range(50):
                assert cli.get("/t1").status_code == 200

            assert cli.get("/t1").status_code == 429
            assert (
                cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.3"}).status_code
                == 429
            )

    def test_multiple_decorators_not_response(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        @app.get("/t1")
        @limiter.limit(
            "100 per minute", lambda: "test"
        )  # effectively becomes a limit for all users
        @limiter.limit("50/minute")  # per ip as per default key_func
        async def t1(request: Request, response: Response):
            return {"key": "value"}

        with hiro.Timeline().freeze() as timeline:
            cli = TestClient(app)
            for i in range(0, 100):
                response = cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.2"})
                assert response.status_code == 200 if i < 50 else 429
            for i in range(50):
                assert cli.get("/t1").status_code == 200

            assert cli.get("/t1").status_code == 429
            assert (
                cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.3"}).status_code
                == 429
            )

    def test_multiple_decorators_not_response_with_headers(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr, headers_enabled=True)

        @app.get("/t1")
        @limiter.limit(
            "100 per minute", lambda: "test"
        )  # effectively becomes a limit for all users
        @limiter.limit("50/minute")  # per ip as per default key_func
        async def t1(request: Request, response: Response):
            return {"key": "value"}

        with hiro.Timeline().freeze() as timeline:
            cli = TestClient(app)
            for i in range(0, 100):
                response = cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.2"})
                assert response.status_code == 200 if i < 50 else 429
            for i in range(50):
                assert cli.get("/t1").status_code == 200

            assert cli.get("/t1").status_code == 429
            assert (
                cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.3"}).status_code
                == 429
            )

    def test_endpoint_missing_request_param(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        with pytest.raises(Exception) as exc_info:

            @app.get("/t3")
            @limiter.limit("5/minute")
            async def t3():
                return PlainTextResponse("test")

        assert exc_info.match(
            r"""^No "request" or "websocket" argument on function .*"""
        )

    def test_endpoint_missing_request_param_sync(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        with pytest.raises(Exception) as exc_info:

            @app.get("/t3_sync")
            @limiter.limit("5/minute")
            def t3():
                return PlainTextResponse("test")

        assert exc_info.match(
            r"""^No "request" or "websocket" argument on function .*"""
        )

    def test_endpoint_request_param_invalid(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        @app.get("/t4")
        @limiter.limit("5/minute")
        async def t4(request: str = None):
            return PlainTextResponse("test")

        with pytest.raises(Exception) as exc_info:
            client = TestClient(app)
            client.get("/t4")
        assert exc_info.match(
            r"""parameter `request` must be an instance of starlette.requests.Request"""
        )

    def test_endpoint_response_param_invalid(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr, headers_enabled=True)

        @app.get("/t4")
        @limiter.limit("5/minute")
        async def t4(request: Request, response: str = None):
            return {"key": "value"}

        with pytest.raises(Exception) as exc_info:
            client = TestClient(app)
            client.get("/t4")
        assert exc_info.match(
            r"""parameter `response` must be an instance of starlette.responses.Response"""
        )

    def test_endpoint_request_param_invalid_sync(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        @app.get("/t5")
        @limiter.limit("5/minute")
        def t5(request: str = None):
            return PlainTextResponse("test")

        with pytest.raises(Exception) as exc_info:
            client = TestClient(app)
            client.get("/t5")
        assert exc_info.match(
            r"""parameter `request` must be an instance of starlette.requests.Request"""
        )

    def test_endpoint_response_param_invalid_sync(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr, headers_enabled=True)

        @app.get("/t5")
        @limiter.limit("5/minute")
        def t5(request: Request, response: str = None):
            return {"key": "value"}

        with pytest.raises(Exception) as exc_info:
            client = TestClient(app)
            client.get("/t5")
        assert exc_info.match(
            r"""parameter `response` must be an instance of starlette.responses.Response"""
        )

    def test_dynamic_limit_provider_depending_on_key(self, build_fastapi_app):
        def custom_key_func(request: Request):
            if request.headers.get("TOKEN") == "secret":
                return "admin"
            return "user"

        def dynamic_limit_provider(key: str):
            if key == "admin":
                return "10/minute"
            return "5/minute"

        app, limiter = build_fastapi_app(key_func=custom_key_func)

        @app.get("/t1")
        @limiter.limit(dynamic_limit_provider)
        async def t1(request: Request, response: Response):
            return {"key": "value"}

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429

        for i in range(0, 20):
            response = client.get("/t1", headers={"TOKEN": "secret"})
            assert response.status_code == 200 if i < 10 else 429

    def test_disabled_limiter(self, build_fastapi_app):
        """
        Check that the limiter does nothing if disabled (both sync and async)
        """
        app, limiter = build_fastapi_app(key_func=get_ipaddr, enabled=False)

        @app.get("/t1")
        @limiter.limit("5/minute")
        async def t1(request: Request):
            return PlainTextResponse("test")

        @app.get("/t2")
        @limiter.limit("5/minute")
        def t2(request: Request):
            return PlainTextResponse("test")

        @app.get("/t3")
        def t3(request: Request):
            return PlainTextResponse("also a test")

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200

        for i in range(0, 10):
            response = client.get("/t2")
            assert response.status_code == 200

        for i in range(0, 10):
            response = client.get("/t3")
            assert response.status_code == 200

    def test_cost(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        @app.get("/t1")
        @limiter.limit("50/minute", cost=10)
        async def t1(request: Request):
            return PlainTextResponse("test")

        @app.get("/t2")
        @limiter.limit("50/minute", cost=15)
        async def t2(request: Request):
            return PlainTextResponse("test")

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429

            response = client.get("/t2")
            assert response.status_code == 200 if i < 3 else 429

    def test_callable_cost(self, build_fastapi_app):
        app, limiter = build_fastapi_app(key_func=get_ipaddr)

        @app.get("/t1")
        @limiter.limit("50/minute", cost=lambda request: int(request.headers["foo"]))
        async def t1(request: Request):
            return PlainTextResponse("test")

        @app.get("/t2")
        @limiter.limit(
            "50/minute", cost=lambda request: int(request.headers["foo"]) * 1.5
        )
        async def t2(request: Request):
            return PlainTextResponse("test")

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1", headers={"foo": "10"})
            assert response.status_code == 200 if i < 5 else 429

            response = client.get("/t2", headers={"foo": "5"})
            assert response.status_code == 200 if i < 6 else 429

    @pytest.mark.parametrize(
        "key_style, expected_key",
        [
            ("url", "LIMITER/mock//t1/1/1/minute"),
            (
                "endpoint",
                "LIMITER/mock/tests.test_fastapi_extension.t1_func/1/1/minute",
            ),
        ],
    )
    def test_key_style(self, key_style, expected_key):
        app, limiter = self.build_fastapi_app(
            key_func=lambda: "mock", key_style=key_style
        )

        @app.get("/t1")
        @limiter.limit("1/minute")
        async def t1_func(request: Request):
            return PlainTextResponse("test")

        client = TestClient(app)
        client.get("/t1", headers={"foo": "10"})
        assert limiter._storage.get(expected_key) == 1
