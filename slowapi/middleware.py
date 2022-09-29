from typing import Optional

from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Scope, Receive, Send

from slowapi import Limiter, _rate_limit_exceeded_handler


class SlowAPIMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        app: Starlette = request.app
        limiter: Limiter = app.state.limiter
        handler = None
        if not limiter.enabled:
            return await call_next(request)

        for route in app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL and hasattr(route, "endpoint"):
                handler = route.endpoint  # type: ignore
        # if we can't find the route handler
        if handler is None:
            return await call_next(request)

        name = "%s.%s" % (handler.__module__, handler.__name__)
        # if exempt no need to check
        if name in limiter._exempt_routes:
            return await call_next(request)

        # there is a decorator for this route we let the decorator handle it
        if name in limiter._route_limits:
            return await call_next(request)

        # let the decorator handle if already in
        if limiter._auto_check and not getattr(
            request.state, "_rate_limiting_complete", False
        ):
            try:
                limiter._check_request_limit(request, handler, True)
            except Exception as e:
                # handle the exception since the global exception handler won't pick it up if we call_next
                exception_handler = app.exception_handlers.get(
                    type(e), _rate_limit_exceeded_handler
                )
                return exception_handler(request, e)
            # request.state._rate_limiting_complete = True
            response = await call_next(request)
            response = limiter._inject_headers(response, request.state.view_rate_limit)
            return response
        return await call_next(request)


class SlowAPIASGIMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.error_response: Optional[Response] = None
        self.initial_message: Message = {}
        self.inject_headers = False

    async def send_wrapper(self, message: Message):
        if message["type"] == "http.response.start":
            # do not send the http.response.start message now, so that we can edit the headers
            # before sending it, based on what happens in the http.response.body message.
            self.initial_message = message

        elif message["type"] == "http.response.body":
            if self.error_response:
                self.initial_message["status"] = self.error_response.status_code

            if self.inject_headers:
                headers = MutableHeaders(raw=self.initial_message["headers"])
                headers = self.limiter._inject_asgi_headers(
                    headers, self.request.state.view_rate_limit
                )

            # send the http.response.start message just before the http.response.body one,
            # now that the headers are updated
            await self.send(self.initial_message)
            await self.send(message)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        self.send = send

        _app: Starlette = scope["app"]
        limiter: Limiter = _app.state.limiter
        handler = None

        if not limiter.enabled:
            return await self.app(scope, receive, self.send)

        for route in _app.routes:
            match, _ = route.matches(scope)
            if match == Match.FULL and hasattr(route, "endpoint"):
                handler = route.endpoint  # type: ignore

        # if we can't find the route handler
        if handler is None:
            return await self.app(scope, receive, self.send)

        name = "%s.%s" % (handler.__module__, handler.__name__)

        # if exempt no need to check
        if name in limiter._exempt_routes:
            return await self.app(scope, receive, self.send)

        # there is a decorator for this route we let the decorator handle it
        if name in limiter._route_limits:
            return await self.app(scope, receive, self.send)

        # Limit
        request = Request(scope, receive=receive, send=self.send)

        # let the decorator handle if already in
        if limiter._auto_check and not getattr(
            request.state, "_rate_limiting_complete", False
        ):
            try:
                limiter._check_request_limit(request, handler, True)
            except Exception as e:
                # handle the exception since the global exception handler won't pick exceptions
                # raised from an ASGI Middleware
                exception_handler = _app.exception_handlers.get(
                    type(e), _rate_limit_exceeded_handler
                )
                response = exception_handler(request, e)
                self.error_response = response
                return await response(scope, receive, self.send_wrapper)

            self.inject_headers = True
            self.limiter = limiter
            self.request = request
        return await self.app(scope, receive, self.send_wrapper)
