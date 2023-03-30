import inspect
from typing import Callable, Iterable, Optional, Tuple

from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Message, Scope, Receive, Send

from slowapi import Limiter, _rate_limit_exceeded_handler


def _find_route_handler(
    routes: Iterable[BaseRoute], scope: Scope
) -> Optional[Callable]:
    handler = None
    for route in routes:
        match, _ = route.matches(scope)
        if match == Match.FULL and hasattr(route, "endpoint"):
            handler = route.endpoint  # type: ignore
    return handler


def _get_route_name(handler: Callable):
    return f"{handler.__module__}.{handler.__name__}"


def _check_limits(
    limiter: Limiter, request: Request, handler: Optional[Callable], app: Starlette
) -> Tuple[Optional[Callable], bool, Optional[Exception]]:
    """
    Utils to check (if needed) current requests limit.
    It returns a tuple of size 3:
        1. The exception handler to run, if needed
        2. a bool, True if we need to inject some headers, False otherwise
        3. the exception that happened, if any
    """
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
            return exception_handler, False, e

        return None, True, None
    return None, False, None


def sync_check_limits(
    limiter: Limiter, request: Request, handler: Optional[Callable], app: Starlette
) -> Tuple[Optional[Response], bool]:
    """
    Returns a `Response` object if an error occurred, as well as a boolean to know
    whether we should inject headers or not.
    Used in our WSGI middleware, it only supports synchronous exception_handler.
    This will fallback on _rate_limit_exceeded_handler otherwise.
    """
    exception_handler, _bool, exc = _check_limits(limiter, request, handler, app)
    if not exception_handler or not exc:
        return None, _bool

    # cannot execute asynchronous code in a synchronous middleware,
    # -> fallback on default exception handler
    if inspect.iscoroutinefunction(exception_handler):
        exception_handler = _rate_limit_exceeded_handler

    return exception_handler(request, exc), _bool  # type: ignore


async def async_check_limits(
    limiter: Limiter, request: Request, handler: Optional[Callable], app: Starlette
) -> Tuple[Optional[Response], bool]:
    """
    Returns a `Response` object if an error occurred, as well as a boolean to know
    whether we should inject headers or not.
    Used in our ASGI middleware, this support both synchronous or asynchronous exception handlers.
    """
    exception_handler, _bool, exc = _check_limits(limiter, request, handler, app)
    if not exception_handler:
        return None, _bool

    if inspect.iscoroutinefunction(exception_handler):
        return await exception_handler(request, exc), _bool
    else:
        return exception_handler(request, exc), _bool


def _should_exempt(limiter: Limiter, handler: Optional[Callable]) -> bool:
    # if we can't find the route handler
    if handler is None:
        return True

    name = _get_route_name(handler)

    # if exempt no need to check
    if name in limiter._exempt_routes:
        return True

    # there is a decorator for this route we let the decorator handle it
    if name in limiter._route_limits:
        return True

    return False


class SlowAPIMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        app: Starlette = request.app
        limiter: Limiter = app.state.limiter

        if not limiter.enabled:
            return await call_next(request)

        handler = _find_route_handler(app.routes, request.scope)
        if _should_exempt(limiter, handler):
            return await call_next(request)

        error_response, should_inject_headers = sync_check_limits(
            limiter, request, handler, app
        )
        if error_response is not None:
            return error_response

        response = await call_next(request)
        if should_inject_headers:
            response = limiter._inject_headers(response, request.state.view_rate_limit)
        return response


class SlowAPIASGIMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        await _ASGIMiddlewareResponder(self.app)(scope, receive, send)


class _ASGIMiddlewareResponder:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.error_response: Optional[Response] = None
        self.initial_message: Message = {}
        self.inject_headers = False

    async def send_wrapper(self, message: Message) -> None:
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
        self.send = send

        _app: Starlette = scope["app"]
        limiter: Limiter = _app.state.limiter

        if not limiter.enabled:
            return await self.app(scope, receive, self.send)

        handler = _find_route_handler(_app.routes, scope)
        request = Request(scope, receive=receive, send=self.send)
        if _should_exempt(limiter, handler):
            return await self.app(scope, receive, self.send)

        error_response, should_inject_headers = await async_check_limits(
            limiter, request, handler, _app
        )
        if error_response is not None:
            return await error_response(scope, receive, self.send_wrapper)

        if should_inject_headers:
            self.inject_headers = True
            self.limiter = limiter
            self.request = request

        return await self.app(scope, receive, self.send_wrapper)
