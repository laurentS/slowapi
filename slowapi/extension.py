"""
The starlette extension to rate-limit requests
"""
import asyncio
import datetime
import functools
import inspect
import itertools
import json
import logging
import sys
import time
import warnings
from email.utils import formatdate, parsedate_to_datetime
from functools import wraps
from typing import (Any, Callable, Dict, List, Optional, Set, Tuple, Type,
                    TypeVar, Union)

from limits import RateLimitItem  # type: ignore
from limits.errors import ConfigurationError  # type: ignore
from limits.storage import Storage  # type: ignore
from limits.storage import MemoryStorage, storage_from_string
from limits.strategies import STRATEGIES, RateLimiter  # type: ignore
from starlette.applications import Starlette
from starlette.config import Config
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .errors import RateLimitExceeded
from .util import get_ipaddr
from .wrappers import Limit, LimitGroup

# used to annotate get_app_config method
T = TypeVar("T")


class C:
    ENABLED = "RATELIMIT_ENABLED"
    HEADERS_ENABLED = "RATELIMIT_HEADERS_ENABLED"
    STORAGE_URL = "RATELIMIT_STORAGE_URL"
    STORAGE_OPTIONS = "RATELIMIT_STORAGE_OPTIONS"
    STRATEGY = "RATELIMIT_STRATEGY"
    GLOBAL_LIMITS = "RATELIMIT_GLOBAL"
    DEFAULT_LIMITS = "RATELIMIT_DEFAULT"
    APPLICATION_LIMITS = "RATELIMIT_APPLICATION"
    HEADER_LIMIT = "RATELIMIT_HEADER_LIMIT"
    HEADER_REMAINING = "RATELIMIT_HEADER_REMAINING"
    HEADER_RESET = "RATELIMIT_HEADER_RESET"
    SWALLOW_ERRORS = "RATELIMIT_SWALLOW_ERRORS"
    IN_MEMORY_FALLBACK = "RATELIMIT_IN_MEMORY_FALLBACK"
    IN_MEMORY_FALLBACK_ENABLED = "RATELIMIT_IN_MEMORY_FALLBACK_ENABLED"
    HEADER_RETRY_AFTER = "RATELIMIT_HEADER_RETRY_AFTER"
    HEADER_RETRY_AFTER_VALUE = "RATELIMIT_HEADER_RETRY_AFTER_VALUE"
    KEY_PREFIX = "RATELIMIT_KEY_PREFIX"


class HEADERS:
    RESET = 1
    REMAINING = 2
    LIMIT = 3
    RETRY_AFTER = 4


MAX_BACKEND_CHECKS = 5


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """
    Build a simple JSON response that includes the details of the rate limit
    that was hit. If no limit is hit, the countdown is added to headers.
    """
    response = JSONResponse(
        {"error": f"Rate limit exceeded: {exc.limit}"}, status_code=429
    )
    response = request.app.state.limiter._inject_headers(
        response, request.state.view_rate_limit
    )
    return response


class Limiter:
    """
    :param app: :class:`Starlette/FastAPI` instance to initialize the extension
     with.
    :param list default_limits: a variable list of strings or callables returning strings denoting global
     limits to apply to all routes. :ref:`ratelimit-string` for  more details.
    :param list application_limits: a variable list of strings or callables returning strings for limits that
     are applied to the entire application (i.e a shared limit for all routes)
    :param function key_func: a callable that returns the domain to rate limit by.
    :param bool headers_enabled: whether ``X-RateLimit`` response headers are written.
    :param str strategy: the strategy to use. refer to :ref:`ratelimit-strategy`
    :param str storage_uri: the storage location. refer to :ref:`ratelimit-conf`
    :param dict storage_options: kwargs to pass to the storage implementation upon
      instantiation.
    :param bool auto_check: whether to automatically check the rate limit in the before_request
     chain of the application. default ``True``
    :param bool swallow_errors: whether to swallow errors when hitting a rate limit.
     An exception will still be logged. default ``False``
    :param list in_memory_fallback: a variable list of strings or callables returning strings denoting fallback
     limits to apply when the storage is down.
    :param bool in_memory_fallback_enabled: simply falls back to in memory storage
     when the main storage is down and inherits the original limits.
    :param str key_prefix: prefix prepended to rate limiter keys.
    :param Optional[str] config_filename: name of the config file for Starlette from which to load settings
     for the rate limiter. Defaults to ".env".
    """

    def __init__(
        self,
        # app: Starlette = None,
        key_func=Callable[..., str],
        default_limits: List[Union[str, Callable[..., str]]] = [],
        application_limits: List[Union[str, Callable[..., str]]] = [],
        headers_enabled: bool = False,
        strategy: Optional[str] = None,
        storage_uri: Optional[str] = None,
        storage_options: Dict = {},
        auto_check: bool = True,
        swallow_errors: bool = False,
        in_memory_fallback: List = [],
        in_memory_fallback_enabled: bool = False,
        retry_after=None,
        key_prefix: str = "",
        enabled: bool = True,
        config_filename: Optional[str] = None,
    ):
        """
        Configure the rate limiter at app level
        """
        # assert app is not None, "Passing the app instance to the limiter is required"
        # self.app = app
        # app.state.limiter = self

        self.logger = logging.getLogger("slowapi")

        self.app_config = Config(
            config_filename if config_filename is not None else ".env"
        )

        self.enabled = enabled
        self._default_limits = []
        self._application_limits = []
        self._in_memory_fallback = []
        self._in_memory_fallback_enabled = (
            in_memory_fallback_enabled or len(in_memory_fallback) > 0
        )
        self._exempt_routes: Set = set()
        self._request_filters: List = []
        self._headers_enabled = headers_enabled
        self._header_mapping: Dict[int, str] = {}
        self._retry_after = retry_after
        self._strategy = strategy
        self._storage_uri = storage_uri
        self._storage_options = storage_options
        self._auto_check = auto_check
        self._swallow_errors = swallow_errors

        self._key_func = key_func
        self._key_prefix = key_prefix

        for limit in set(default_limits):
            self._default_limits.extend(
                [LimitGroup(limit, self._key_func, None, False, None, None, None)]
            )
        for limit in application_limits:
            self._application_limits.extend(
                [LimitGroup(limit, self._key_func, "global", False, None, None, None)]
            )
        for limit in in_memory_fallback:
            self._in_memory_fallback.extend(
                [LimitGroup(limit, self._key_func, None, False, None, None, None)]
            )
        self._route_limits: Dict = {}
        self._dynamic_route_limits: Dict = {}
        # a flag to note if the storage backend is dead (not available)
        self._storage_dead: bool = False
        self._fallback_limiter = None
        self.__check_backend_count = 0
        self.__last_check_backend = time.time()
        self.__marked_for_limiting: Dict = {}

        class BlackHoleHandler(logging.StreamHandler):
            def emit(*_):
                return

        self.logger.addHandler(BlackHoleHandler())

        self.enabled = self.get_app_config(C.ENABLED, self.enabled)
        self._swallow_errors = self.get_app_config(
            C.SWALLOW_ERRORS, self._swallow_errors
        )
        self._headers_enabled = self._headers_enabled or self.get_app_config(
            C.HEADERS_ENABLED, False
        )
        self._storage_options.update(self.get_app_config(C.STORAGE_OPTIONS, {}))
        self._storage: Storage = storage_from_string(
            self._storage_uri or self.get_app_config(C.STORAGE_URL, "memory://"),
            **self._storage_options,
        )
        strategy = self._strategy or self.get_app_config(C.STRATEGY, "fixed-window")
        if strategy not in STRATEGIES:
            raise ConfigurationError("Invalid rate limiting strategy %s" % strategy)
        self._limiter: RateLimiter = STRATEGIES[strategy](self._storage)
        self._header_mapping.update(
            {
                HEADERS.RESET: self._header_mapping.get(
                    HEADERS.RESET,
                    self.get_app_config(C.HEADER_RESET, "X-RateLimit-Reset"),
                ),
                HEADERS.REMAINING: self._header_mapping.get(
                    HEADERS.REMAINING,
                    self.get_app_config(C.HEADER_REMAINING, "X-RateLimit-Remaining"),
                ),
                HEADERS.LIMIT: self._header_mapping.get(
                    HEADERS.LIMIT,
                    self.get_app_config(C.HEADER_LIMIT, "X-RateLimit-Limit"),
                ),
                HEADERS.RETRY_AFTER: self._header_mapping.get(
                    HEADERS.RETRY_AFTER,
                    self.get_app_config(C.HEADER_RETRY_AFTER, "Retry-After"),
                ),
            }
        )
        self._retry_after = self._retry_after or self.get_app_config(
            C.HEADER_RETRY_AFTER_VALUE
        )
        self._key_prefix = self._key_prefix or self.get_app_config(C.KEY_PREFIX)
        app_limits = self.get_app_config(C.APPLICATION_LIMITS, None)
        if not self._application_limits and app_limits:
            self._application_limits = [
                LimitGroup(
                    app_limits, self._key_func, "global", False, None, None, None
                )
            ]

        conf_limits = self.get_app_config(C.DEFAULT_LIMITS, None)
        if not self._default_limits and conf_limits:
            self._default_limits = [
                LimitGroup(conf_limits, self._key_func, None, False, None, None, None)
            ]
        fallback_enabled = self.get_app_config(C.IN_MEMORY_FALLBACK_ENABLED, False)
        fallback_limits = self.get_app_config(C.IN_MEMORY_FALLBACK, None)
        if not self._in_memory_fallback and fallback_limits:
            self._in_memory_fallback = [
                LimitGroup(
                    fallback_limits, self._key_func, None, False, None, None, None
                )
            ]
        if not self._in_memory_fallback_enabled:
            self._in_memory_fallback_enabled = (
                fallback_enabled or len(self._in_memory_fallback) > 0
            )

        if self._in_memory_fallback_enabled:
            self._fallback_storage = MemoryStorage()
            self._fallback_limiter = STRATEGIES[strategy](self._fallback_storage)

    def slowapi_startup(self):
        """
        Starlette startup event handler that links the app with the Limiter instance.
        """
        print("STARTUP")
        app.state.limiter = self
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    def get_app_config(self, key: str, default_value: T = None) -> T:
        """
        Place holder until we find a better way to load config from app
        """
        return self.app_config(key, default=default_value, cast=type(default_value))

    def __should_check_backend(self) -> bool:
        if self.__check_backend_count > MAX_BACKEND_CHECKS:
            self.__check_backend_count = 0
        if time.time() - self.__last_check_backend > pow(2, self.__check_backend_count):
            self.__last_check_backend = time.time()
            self.__check_backend_count += 1
            return True
        return False

    def reset(self) -> None:
        """
        resets the storage if it supports being reset
        """
        try:
            self._storage.reset()
            self.logger.info("Storage has been reset and all limits cleared")
        except NotImplementedError:
            self.logger.warning("This storage type does not support being reset")

    @property
    def limiter(self) -> RateLimiter:
        """
        The backend that keeps track of consumption of endpoints vs limits
        """
        if self._storage_dead and self._in_memory_fallback_enabled:
            return self._fallback_limiter
        else:
            return self._limiter

    def _inject_headers(
        self, response: Response, current_limit: Tuple[RateLimitItem, List[str]]
    ) -> Response:
        if self.enabled and self._headers_enabled and current_limit is not None:
            try:
                window_stats: Tuple[int, int] = self.limiter.get_window_stats(
                    current_limit[0], *current_limit[1]
                )
                reset_in = 1 + window_stats[0]
                response.headers.append(
                    self._header_mapping[HEADERS.LIMIT], str(current_limit[0].amount)
                )
                response.headers.append(
                    self._header_mapping[HEADERS.REMAINING], str(window_stats[1])
                )
                response.headers.append(
                    self._header_mapping[HEADERS.RESET], str(reset_in)
                )

                # response may have an existing retry after
                print(response.headers)
                existing_retry_after_header = response.headers.get("Retry-After")

                if existing_retry_after_header is not None:
                    # might be in http-date format
                    retry_after = parsedate_to_datetime(existing_retry_after_header)

                    # parse_date failure returns None
                    if retry_after is None:
                        retry_after = time.time() + int(existing_retry_after_header)

                    if isinstance(retry_after, datetime.datetime):
                        retry_after_int: int = int(time.mktime(retry_after.timetuple()))

                    reset_in = max(retry_after_int, reset_in)

                response.headers[self._header_mapping[HEADERS.RETRY_AFTER]] = (
                    formatdate(reset_in)
                    if self._retry_after == "http-date"
                    else str(int(reset_in - time.time()))
                )
            except:
                if self._in_memory_fallback and not self._storage_dead:
                    self.logger.warn(
                        "Rate limit storage unreachable - falling back to"
                        " in-memory storage"
                    )
                    self._storage_dead = True
                    response = self._inject_headers(response, current_limit)
                if self._swallow_errors:
                    self.logger.exception(
                        "Failed to update rate limit headers. Swallowing error"
                    )
                else:
                    raise
        return response

    def __evaluate_limits(
        self, request: Request, endpoint: str, limits: List[Limit]
    ) -> None:
        failed_limit = None
        limit_for_header = None
        for lim in limits:
            limit_scope = lim.scope or endpoint
            if lim.is_exempt:
                continue
            if lim.methods is not None and request.method.lower() not in lim.methods:
                continue
            if lim.per_method:
                limit_scope += ":%s" % request.method

            if "request" in inspect.signature(lim.key_func).parameters.keys():
                limit_key = lim.key_func(request)
            else:
                limit_key = lim.key_func()

            args = [limit_key, limit_scope]
            if all(args):
                if self._key_prefix:
                    args = [self._key_prefix] + args
                if not limit_for_header or lim.limit < limit_for_header[0]:
                    limit_for_header = (lim.limit, args)
                if not self.limiter.hit(lim.limit, *args):
                    self.logger.warning(
                        "ratelimit %s (%s) exceeded at endpoint: %s",
                        lim.limit,
                        limit_key,
                        limit_scope,
                    )
                    failed_limit = lim
                    limit_for_header = (lim.limit, args)
                    break
            else:
                self.logger.error(
                    "Skipping limit: %s. Empty value found in parameters.", lim.limit
                )
                continue
        # keep track of which limit was hit, to be picked up for the response header
        request.state.view_rate_limit = limit_for_header

        if failed_limit:
            raise RateLimitExceeded(failed_limit)

    def __check_request_limit(
        self, request: Request, endpoint_func: Callable, in_middleware: bool = True
    ) -> None:
        """
        Determine if the request is within limits
        """
        endpoint = request["path"] or ""
        # view_func = current_app.view_functions.get(endpoint, None)
        view_func = endpoint_func

        name = "%s.%s" % (view_func.__module__, view_func.__name__) if view_func else ""
        # cases where we don't need to check the limits
        if (
            not endpoint
            or not self.enabled
            # or we are sending a static file
            # or view_func == current_app.send_static_file
            or name in self._exempt_routes
            or any(fn() for fn in self._request_filters)
        ):
            return
        limits: List = []
        dynamic_limits: List = []

        if not in_middleware:
            limits = name in self._route_limits and self._route_limits[name] or []
            dynamic_limits = []
            if name in self._dynamic_route_limits:
                for lim in self._dynamic_route_limits[name]:
                    try:
                        dynamic_limits.extend(list(lim))
                    except ValueError as e:
                        self.logger.error(
                            "failed to load ratelimit for view function %s (%s)",
                            name,
                            e,
                        )

        try:
            all_limits: List = []
            if self._storage_dead and self._fallback_limiter:
                if in_middleware and name in self.__marked_for_limiting:
                    pass
                else:
                    if self.__should_check_backend() and self._storage.check():
                        self.logger.info("Rate limit storage recovered")
                        self._storage_dead = False
                        self.__check_backend_count = 0
                    else:
                        all_limits = list(itertools.chain(*self._in_memory_fallback))
            if not all_limits:
                route_limits = limits + dynamic_limits
                all_limits = (
                    list(itertools.chain(*self._application_limits))
                    if in_middleware
                    else []
                )
                all_limits += route_limits
                if not route_limits and not (
                    in_middleware and name in self.__marked_for_limiting
                ):
                    all_limits += list(itertools.chain(*self._default_limits))
            # actually check the limits, so far we've only computed the list of limits to check
            self.__evaluate_limits(request, endpoint, all_limits)
        except Exception as e:  # no qa
            if isinstance(e, RateLimitExceeded):
                raise
            if self._in_memory_fallback_enabled and not self._storage_dead:
                self.logger.warn(
                    "Rate limit storage unreachable - falling back to"
                    " in-memory storage"
                )
                self._storage_dead = True
                self.__check_request_limit(request, endpoint_func, in_middleware)
            else:
                if self._swallow_errors:
                    self.logger.exception("Failed to rate limit. Swallowing error")
                else:
                    raise

    def __limit_decorator(
        self,
        limit_value: Union[str, Callable[..., str]],
        key_func: Optional[Callable[..., str]] = None,
        shared: bool = False,
        scope: Optional[Union[str, Callable[..., str]]] = None,
        per_method: bool = False,
        methods: Optional[List] = None,
        error_message: Optional[str] = None,
        exempt_when: Optional[Callable[..., bool]] = None,
    ) -> Callable:

        _scope = scope if shared else None

        def decorator(func: Callable) -> Callable:
            keyfunc = key_func or self._key_func
            name = f"{func.__module__}.{func.__name__}"
            dynamic_limit, static_limits = None, []
            if callable(limit_value):
                dynamic_limit = LimitGroup(
                    limit_value,
                    keyfunc,
                    _scope,
                    per_method,
                    methods,
                    error_message,
                    exempt_when,
                )
            else:
                try:
                    static_limits = list(
                        LimitGroup(
                            limit_value,
                            keyfunc,
                            _scope,
                            per_method,
                            methods,
                            error_message,
                            exempt_when,
                        )
                    )
                except ValueError as e:
                    self.logger.error(
                        "Failed to configure throttling for %s (%s)", name, e,
                    )
            self.__marked_for_limiting.setdefault(name, []).append(func)
            if dynamic_limit:
                self._dynamic_route_limits.setdefault(name, []).append(dynamic_limit)
            else:
                self._route_limits.setdefault(name, []).extend(static_limits)

            connection_type: Optional[str] = None
            sig = inspect.signature(func)
            for idx, parameter in enumerate(sig.parameters.values()):
                if parameter.name == "request" or parameter.name == "websocket":
                    connection_type = parameter.name
                    break
            else:
                raise Exception(
                    f'No "request" or "websocket" argument on function "{func}"'
                )

            if asyncio.iscoroutinefunction(func):
                # Handle async request/response functions.
                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Response:
                    # get the request object from the decorated endpoint function
                    request = kwargs.get("request", args[idx] if args else None)
                    assert isinstance(request, Request)

                    if self._auto_check and not getattr(
                        request.state, "_rate_limiting_complete", False
                    ):
                        self.__check_request_limit(request, func, False)
                        request.state._rate_limiting_complete = True
                    response = await func(*args, **kwargs)
                    self._inject_headers(response, request.state.view_rate_limit)
                    return response

                return async_wrapper

            else:
                # Handle sync request/response functions.
                @functools.wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Response:
                    # get the request object from the decorated endpoint function
                    request = kwargs.get("request", args[idx] if args else None)
                    assert isinstance(request, Request)

                    if self._auto_check and not getattr(
                        request.state, "_rate_limiting_complete", False
                    ):
                        self.__check_request_limit(request, func, False)
                        request.state._rate_limiting_complete = True
                    response = func(*args, **kwargs)
                    self._inject_headers(response, request.state.view_rate_limit)
                    return response

                return sync_wrapper

        return decorator

    def limit(
        self,
        limit_value: Union[str, Callable[[str], str]],
        key_func: Optional[Callable[..., str]] = None,
        per_method: bool = False,
        methods: Optional[List] = None,
        error_message: Optional[str] = None,
        exempt_when=None,
    ):
        """
        decorator to be used for rate limiting individual routes.

        :param limit_value: rate limit string or a callable that returns a string.
         :ref:`ratelimit-string` for more details.
        :param function key_func: function/lambda to extract the unique identifier for
         the rate limit. defaults to remote address of the request.
        :param bool per_method: whether the limit is sub categorized into the http
         method of the request.
        :param list methods: if specified, only the methods in this list will be rate
         limited (default: None).
        :param error_message: string (or callable that returns one) to override the
         error message used in the response.
        :param exempt_when:
        :return:
        """
        return self.__limit_decorator(
            limit_value,
            key_func,
            per_method=per_method,
            methods=methods,
            error_message=error_message,
            exempt_when=exempt_when,
        )

    def shared_limit(
        self,
        limit_value: Union[str, Callable[[str], str]],
        scope: Union[str, Callable[..., str]],
        key_func: Optional[Callable[..., str]] = None,
        error_message: Optional[str] = None,
        exempt_when=None,
    ):
        """
        decorator to be applied to multiple routes sharing the same rate limit.

        :param limit_value: rate limit string or a callable that returns a string.
         :ref:`ratelimit-string` for more details.
        :param scope: a string or callable that returns a string
         for defining the rate limiting scope.
        :param function key_func: function/lambda to extract the unique identifier for
         the rate limit. defaults to remote address of the request.
        :param error_message: string (or callable that returns one) to override the
         error message used in the response.
        :param exempt_when:
        """
        return self.__limit_decorator(
            limit_value,
            key_func,
            True,
            scope,
            error_message=error_message,
            exempt_when=exempt_when,
        )
