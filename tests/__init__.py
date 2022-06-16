import logging

from fastapi import FastAPI
from mock import mock  # type: ignore
from starlette.applications import Starlette

from slowapi.errors import RateLimitExceeded
from slowapi.extension import Limiter, _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


class TestSlowapi:
    def build_starlette_app(self, config={}, **limiter_args):
        limiter_args.setdefault("key_func", get_remote_address)
        limiter = Limiter(**limiter_args)
        app = Starlette(debug=True)
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)

        mock_handler = mock.Mock()
        mock_handler.level = logging.INFO
        limiter.logger.addHandler(mock_handler)
        return app, limiter

    def build_fastapi_app(self, config={}, **limiter_args):
        limiter_args.setdefault("key_func", get_remote_address)
        limiter = Limiter(**limiter_args)
        app = FastAPI()
        app.state.limiter = limiter
        app.add_middleware(SlowAPIMiddleware)

        mock_handler = mock.Mock()
        mock_handler.level = logging.INFO
        limiter.logger.addHandler(mock_handler)
        return app, limiter
