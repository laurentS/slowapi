import time

import hiro  # type: ignore
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from slowapi.util import get_ipaddr, get_remote_address
from tests import TestSlowapi


class TestDecorators(TestSlowapi):
    def test_single_decorator_async(self):
        app, limiter = self.build_starlette_app(key_func=get_ipaddr)

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

    def test_single_decorator_sync(self):
        app, limiter = self.build_starlette_app(key_func=get_ipaddr)

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

    def test_shared_decorator(self):
        app, limiter = self.build_starlette_app(key_func=get_ipaddr)

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

    def test_multiple_decorators(self):
        app, limiter = self.build_starlette_app(key_func=get_ipaddr)

        @limiter.limit("100 per minute", lambda: "test")
        @limiter.limit("50/minute")  # per ip as per default key_func
        async def t1(request: Request):
            return PlainTextResponse("test")

        app.add_route("/t1", t1)

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

    def test_headers_no_breach(self):
        app, limiter = self.build_starlette_app(
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

    def test_headers_breach(self):
        app, limiter = self.build_starlette_app(
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

                print(resp.headers)
                assert resp.headers.get("X-RateLimit-Limit") == "10"
                assert resp.headers.get("X-RateLimit-Remaining") == "0"
                assert resp.headers.get("X-RateLimit-Reset") == str(
                    int(time.time() + 50)
                )
                assert resp.headers.get("Retry-After") == str(int(50))

    def test_retry_after(self):
        # FIXME: this test is not actually running!

        app, limiter = self.build_starlette_app(
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
