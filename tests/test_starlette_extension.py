import time

import hiro  # type: ignore
import pytest  # type: ignore
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from slowapi.util import get_ipaddr, get_remote_address
from tests import TestSlowapi


class TestDecorators(TestSlowapi):
    def test_single_decorator_async(self, build_starlette_app):
        app, limiter = build_starlette_app(key_func=get_ipaddr)

        @limiter.limit("5/minute")
        async def t1(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1", t1)

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429
            if i < 5:
                assert response.text == "test"

    def test_single_decorator_sync(self, build_starlette_app):
        app, limiter = build_starlette_app(key_func=get_ipaddr)

        @limiter.limit("5/minute")
        def t1(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1", t1)

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429
            if i < 5:
                assert response.text == "test"

    def test_exempt_when_argument(self, build_starlette_app):
        app, limiter = build_starlette_app(key_func=get_ipaddr)

        def return_true():
            return True

        def return_false():
            return False

        def dynamic(request: Request):
            user_agent = request.headers.get("User-Agent")
            if user_agent is None:
                return False
            return user_agent == "exempt"

        @limiter.limit("1/minute", exempt_when=return_true)
        def always_true(request: Request):
            return PlainTextResponse("test")

        @limiter.limit("1/minute", exempt_when=return_false)
        def always_false(request: Request):
            return PlainTextResponse("test")

        @limiter.limit("1/minute", exempt_when=dynamic)
        def always_dynamic(request: Request):
            return PlainTextResponse("test")

        app.add_route("/true", always_true)
        app.add_route("/false", always_false)
        app.add_route("/dynamic", always_dynamic)

        client = TestClient(app)
        # Test always true always exempting
        for i in range(0, 2):
            response = client.get("/true")
            assert response.status_code == 200
            assert response.text == "test"
        # Test always false hitting the limit after one hit
        for i in range(0, 2):
            response = client.get("/false")
            assert response.status_code == 200 if i < 1 else 429
            if i < 1:
                assert response.text == "test"
        # Test dynamic not exempting with the correct header
        for i in range(0, 2):
            response = client.get("/dynamic", headers={"User-Agent": "exempt"})
            assert response.status_code == 200
            assert response.text == "test"
        # Test dynamic exempting with the incorrect header
        for i in range(0, 2):
            response = client.get("/dynamic")
            assert response.status_code == 200 if i < 1 else 429
            if i < 1:
                assert response.text == "test"

    def test_shared_decorator(self, build_starlette_app):
        app, limiter = build_starlette_app(key_func=get_ipaddr)

        shared_lim = limiter.shared_limit("5/minute", "somescope")

        @shared_lim
        def t1(request: Request):
            return PlainTextResponse("test")

        @shared_lim
        def t2(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1", t1)
        app.add_route("/t2", t2)

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429
        # the shared limit has already been hit via t1
        assert client.get("/t2").status_code == 429

    def test_multiple_decorators(self, build_starlette_app):
        app, limiter = build_starlette_app(key_func=get_ipaddr)

        @limiter.limit("10 per minute", lambda: "test")
        @limiter.limit("5/minute")  # per ip as per default key_func
        async def t1(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1", t1)

        with hiro.Timeline().freeze() as timeline:
            cli = TestClient(app)
            for i in range(0, 10):
                response = cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.2"})
                assert response.status_code == 200 if i < 5 else 429
            for i in range(5):
                assert cli.get("/t1").status_code == 200

            assert cli.get("/t1").status_code == 429
            assert (
                cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.3"}).status_code
                == 429
            )

    def test_multiple_decorators_with_headers(self, build_starlette_app):
        app, limiter = build_starlette_app(key_func=get_ipaddr, headers_enabled=True)

        @limiter.limit("10 per minute", lambda: "test")
        @limiter.limit("5/minute")  # per ip as per default key_func
        async def t1(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1", t1)

        with hiro.Timeline().freeze() as timeline:
            cli = TestClient(app)
            for i in range(0, 10):
                response = cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.2"})
                assert response.status_code == 200 if i < 5 else 429
                assert response.headers.get("Retry-After") if i < 5 else True
            for i in range(5):
                assert cli.get("/t1").status_code == 200

            assert cli.get("/t1").status_code == 429
            assert (
                cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.3"}).status_code
                == 429
            )

    def test_headers_no_breach(self, build_starlette_app):
        app, limiter = build_starlette_app(
            headers_enabled=True, key_func=get_remote_address
        )

        @app.route("/t1")
        @limiter.limit("10/minute")
        def t1(request: Request):
            return PlainTextResponse("test")

        @app.route("/t2")
        @limiter.limit("2/second; 5 per minute; 10/hour")
        def t2(request: Request):
            return PlainTextResponse("test")

        with hiro.Timeline().freeze():
            with TestClient(app) as cli:
                resp = cli.get("/t1")
                assert resp.headers.get("X-RateLimit-Limit") == "10"
                assert resp.headers.get("X-RateLimit-Remaining") == "9"
                assert resp.headers.get("X-RateLimit-Reset") == str(
                    int(time.time() + 61)
                )
                assert resp.headers.get("Retry-After") == str(60)
                resp = cli.get("/t2")
                assert resp.headers.get("X-RateLimit-Limit") == "2"
                assert resp.headers.get("X-RateLimit-Remaining") == "1"
                assert resp.headers.get("X-RateLimit-Reset") == str(
                    int(time.time() + 2)
                )

                assert resp.headers.get("Retry-After") == str(1)

    def test_headers_breach(self, build_starlette_app):
        app, limiter = build_starlette_app(
            headers_enabled=True, key_func=get_remote_address
        )

        @app.route("/t1")
        @limiter.limit("2/second; 10 per minute; 20/hour")
        def t(request: Request):
            return PlainTextResponse("test")

        with hiro.Timeline().freeze() as timeline:
            with TestClient(app) as cli:
                for i in range(11):
                    resp = cli.get("/t1")
                    timeline.forward(1)

                assert resp.headers.get("X-RateLimit-Limit") == "10"
                assert resp.headers.get("X-RateLimit-Remaining") == "0"
                assert resp.headers.get("X-RateLimit-Reset") == str(
                    int(time.time() + 50)
                )
                assert resp.headers.get("Retry-After") == str(int(50))

    def test_retry_after(self, build_starlette_app):
        # FIXME: this test is not actually running!

        app, limiter = build_starlette_app(
            headers_enabled=True, key_func=get_remote_address
        )

        @app.route("/t1")
        @limiter.limit("1/minute")
        def t(request: Request):
            return PlainTextResponse("test")

        with hiro.Timeline().freeze() as timeline:
            with TestClient(app) as cli:
                resp = cli.get("/t1")
                retry_after = int(resp.headers.get("Retry-After"))
                assert retry_after > 0
                timeline.forward(retry_after)
                resp = cli.get("/t1")
                assert resp.status_code == 200

    def test_exempt_decorator(self, build_starlette_app):
        app, limiter = build_starlette_app(
            headers_enabled=True,
            key_func=get_remote_address,
            default_limits=["1/minute"],
        )

        @app.route("/t1")
        def t1(request: Request):
            return PlainTextResponse("test")

        with TestClient(app) as cli:
            resp = cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.10"})
            assert resp.status_code == 200
            resp2 = cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.10"})
            assert resp2.status_code == 429

        @app.route("/t2")
        @limiter.exempt
        def t2(request: Request):
            """Exempt a sync route"""
            return PlainTextResponse("test")

        with TestClient(app) as cli:
            resp = cli.get("/t2", headers={"X_FORWARDED_FOR": "127.0.0.10"})
            assert resp.status_code == 200
            resp2 = cli.get("/t2", headers={"X_FORWARDED_FOR": "127.0.0.10"})
            assert resp2.status_code == 200

        @app.route("/t3")
        @limiter.exempt
        async def t3(request: Request):
            """Exempt an async route"""
            return PlainTextResponse("test")

        with TestClient(app) as cli:
            resp = cli.get("/t3", headers={"X_FORWARDED_FOR": "127.0.0.10"})
            assert resp.status_code == 200
            resp2 = cli.get("/t3", headers={"X_FORWARDED_FOR": "127.0.0.10"})
            assert resp2.status_code == 200

    # todo: more tests - see https://github.com/alisaifee/flask-limiter/blob/55df08f14143a7e918fc033067a494248ab6b0c5/tests/test_decorators.py#L187
    def test_default_and_decorator_limit_merging(self, build_starlette_app):
        app, limiter = build_starlette_app(
            key_func=lambda: "test", default_limits=["10/minute"]
        )

        @limiter.limit("5 per minute", key_func=get_ipaddr, override_defaults=False)
        async def t1(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1", t1)

        with hiro.Timeline().freeze() as timeline:
            cli = TestClient(app)
            for i in range(0, 10):
                response = cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.2"})
                assert response.status_code == 200 if i < 5 else 429
            for i in range(5):
                assert cli.get("/t1").status_code == 200

            assert cli.get("/t1").status_code == 429
            assert (
                cli.get("/t1", headers={"X_FORWARDED_FOR": "127.0.0.3"}).status_code
                == 429
            )

    def test_cost(self, build_starlette_app):
        app, limiter = build_starlette_app(key_func=get_ipaddr)

        @limiter.limit("50/minute", cost=10)
        async def t1(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1", t1)

        @limiter.limit("50/minute", cost=15)
        async def t2(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t2", t2)

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1")
            assert response.status_code == 200 if i < 5 else 429
            if i < 5:
                assert response.text == "test"
            else:
                assert "error" in response.json()

            response = client.get("/t2")
            assert response.status_code == 200 if i < 3 else 429
            if i < 3:
                assert response.text == "test"
            else:
                assert "error" in response.json()

    def test_callable_cost(self, build_starlette_app):
        app, limiter = build_starlette_app(key_func=get_ipaddr)

        @limiter.limit("50/minute", cost=lambda request: int(request.headers["foo"]))
        async def t1(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1", t1)

        @limiter.limit(
            "50/minute", cost=lambda request: int(request.headers["foo"]) * 1.5
        )
        async def t2(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t2", t2)

        client = TestClient(app)
        for i in range(0, 10):
            response = client.get("/t1", headers={"foo": "10"})
            assert response.status_code == 200 if i < 5 else 429
            if i < 5:
                assert response.text == "test"
            else:
                assert "error" in response.json()

            response = client.get("/t2", headers={"foo": "5"})
            assert response.status_code == 200 if i < 6 else 429
            if i < 6:
                assert response.text == "test"
            else:
                assert "error" in response.json()

    @pytest.mark.parametrize(
        "key_style",
        ["url", "endpoint"],
    )
    def test_key_style(self, build_starlette_app, key_style):
        app, limiter = build_starlette_app(key_func=lambda: "mock", key_style=key_style)

        @limiter.limit("1/minute")
        async def t1_func(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1/{my_param}", t1_func)

        client = TestClient(app)
        client.get("/t1/param_one")
        second_call = client.get("/t1/param_two")
        # with the "url" key_style, since the `my_param` value changed, the storage key is different
        # meaning it should not raise any RateLimitExceeded error.
        if key_style == "url":
            assert second_call.status_code == 200
            assert limiter._storage.get("LIMITER/mock//t1/param_one/1/1/minute") == 1
            assert limiter._storage.get("LIMITER/mock//t1/param_two/1/1/minute") == 1
        # However, with the `endpoint` key_style, it will use the function name (e.g: "t1_func")
        # meaning it will raise a RateLimitExceeded error, because no matter the parameter value
        # it will share the limitations.
        elif key_style == "endpoint":
            assert second_call.status_code == 429
            # check that we counted 2 requests, even though we had a different value for "my_param"
            assert (
                limiter._storage.get(
                    "LIMITER/mock/tests.test_starlette_extension.t1_func/1/1/minute"
                )
                == 2
            )
