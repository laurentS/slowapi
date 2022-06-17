from starlette.applications import Starlette
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

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
