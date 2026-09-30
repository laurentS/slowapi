import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address


def test_asgi_middleware_sends_response_start_once_for_streaming():
    limiter = Limiter(
        key_func=get_remote_address, default_limits=["5/minute"], headers_enabled=True
    )
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIASGIMiddleware)

    @app.get("/stream")
    async def stream(request: Request):
        async def gen():
            for i in range(3):
                yield f"chunk{i}\n"

        return StreamingResponse(gen(), media_type="text/plain")

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "path": "/stream", "raw_path": b"/stream",
        "query_string": b"", "headers": [], "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80), "scheme": "http", "root_path": "",
        "app": app,
    }
    sent = []
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(3600)  # keep the "client" connected

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))

    starts = [m for m in sent if m["type"] == "http.response.start"]
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert len(starts) == 1
    assert body == b"chunk0\nchunk1\nchunk2\n"
    assert "x-ratelimit-limit" in [k.decode().lower() for k, _ in starts[0]["headers"]]
