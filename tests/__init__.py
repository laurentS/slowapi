import asyncio
import logging

import pytest
from fastapi import FastAPI
from mock import mock  # type: ignore
from starlette.applications import Starlette
from starlette.requests import Request

from slowapi.errors import RateLimitExceeded
from slowapi.extension import Limiter, _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware, SlowAPIASGIMiddleware
from slowapi.util import get_remote_address


async def _async_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    await asyncio.sleep(0)
    return _rate_limit_exceeded_handler(request, exc)


class TestSlowapi:
    @pytest.fixture(
        params=[
            (SlowAPIMiddleware, _rate_limit_exceeded_handler),
            (SlowAPIASGIMiddleware, _rate_limit_exceeded_handler),
            (SlowAPIASGIMiddleware, _async_rate_limit_exceeded_handler),
        ]
    )
    def build_starlette_app(self, request):
        def _factory(config={}, **limiter_args):
            middleware, exception_handler = request.param

            limiter_args.setdefault("key_func", get_remote_address)
            limiter = Limiter(**limiter_args)
            app = Starlette(debug=True)
            app.state.limiter = limiter
            app.add_exception_handler(RateLimitExceeded, exception_handler)
            app.add_middleware(middleware)

            mock_handler = mock.Mock()
            mock_handler.level = logging.INFO
            limiter.logger.addHandler(mock_handler)
            return app, limiter

        return _factory

    @pytest.fixture(
        params=[
            (SlowAPIMiddleware, _rate_limit_exceeded_handler),
            (SlowAPIASGIMiddleware, _rate_limit_exceeded_handler),
            (SlowAPIASGIMiddleware, _async_rate_limit_exceeded_handler),
        ]
    )
    def build_fastapi_app(self, request):
        def _factory(config={}, **limiter_args):
            middleware, exception_handler = request.param
            limiter_args.setdefault("key_func", get_remote_address)
            limiter = Limiter(**limiter_args)
            app = FastAPI()
            app.state.limiter = limiter
            app.add_exception_handler(RateLimitExceeded, exception_handler)
            app.add_middleware(middleware)

            mock_handler = mock.Mock()
            mock_handler.level = logging.INFO
            limiter.logger.addHandler(mock_handler)
            return app, limiter

        return _factory
