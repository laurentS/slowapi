"""
The starlette extension to rate-limit requests
"""
import asyncio
import functools
import inspect
import itertools
import logging
import os
import time
from datetime import datetime
from email.utils import formatdate, parsedate_to_datetime
from functools import wraps
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

from limits import RateLimitItem  # type: ignore
from limits.errors import ConfigurationError  # type: ignore
from limits.storage import MemoryStorage, storage_from_string  # type: ignore
from limits.strategies import STRATEGIES, RateLimiter  # type: ignore
from starlette.config import Config
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from typing_extensions import Literal

from .errors import RateLimitExceeded
from .wrappers import Limit, LimitGroup

# used to annotate get_app_config method
T = TypeVar("T")
# Define an alias for the most commonly used type
StrOrCallableStr = Union[str, Callable[..., str]]


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
        {"error": f"Rate limit exceeded: {exc.detail}"}, status_code=429
    )
    response = request.app.state.limiter._inject_headers(
        response, request.state.view_rate_limit
    )
    return response


class Limiter:
    """
    Initializes the slowapi rate limiter.

    ** parameter **

    * **app**: `Starlette/FastAPI` instance to initialize the extension
     with.

    * **default_limits**: a variable list of strings or callables returning strings denoting global
     limits to apply to all routes. `ratelimit-string` for  more details.

    * **application_limits**: a variable list of strings or callables returning strings for limits that
     are applied to the entire application (i.e a shared limit for all routes)

    * **key_func**: a callable that returns the domain to rate limit by.

    * **headers_enabled**: whether ``X-RateLimit`` response headers are written.

    * **strategy:** the strategy to use. refer to `ratelimit-strategy`

    * **storage_uri**: the storage location. refer to `ratelimit-conf`

    * **storage_options**: kwargs to pass to the storage implementation upon
      instantiation.
    * **auto_check**: whether to automatically check the rate limit in the before_request
     chain of the application. default ``True``
    * **swallow_errors**: whether to swallow errors when hitting a rate limit.
     An exception will still be logged. default ``False``
    * **in_memory_fallback**: a variable list of strings or callables returning strings denoting fallback
     limits to apply when the storage is down.
    * **in_memory_fallback_enabled**: simply falls back to in memory storage
     when the main storage is down and inherits the original limits.
    * **key_prefix**: prefix prepended to rate limiter keys.
    * **enabled**: set to False to deactivate the limiter (default: True)
    * **config_filename**: name of the config file for Starlette from which to load settings
     for the rate limiter. Defaults to ".env".
    * **key_style**: set to "url" to use the url, "endpoint" to use the view_func
    """

    def __init__(
        self,
        # app: Starlette = None,
        key_func: Callable[..., str],
        default_limits: List[StrOrCallableStr] = [],
        application_limits: List[StrOrCallableStr] = [],
        headers_enabled: bool = False,
        strategy: Optional[str] = None,
        storage_uri: Optional[str] = None,
        storage_options: Dict[str, str] = {},
        auto_check: bool = True,
        swallow_errors: bool = False,
        in_memory_fallback: List[StrOrCallableStr] = [],
        in_memory_fallback_enabled: bool = False,
        retry_after: Optional[str] = None,
        key_prefix: str = "",
        enabled: bool = True,
        config_filename: Optional[str] = None,
        key_style: Literal["endpoint", "url"] = "url",
    ) -> None:
        """
        Configure the rate limiter at app level
        """
        # assert app is not None, "Passing the app instance to the limiter is required"
        # self.app = app
        # app.state.limiter = self

        self.logger = logging.getLogger("slowapi")

        dotenv_file_exists = os.path.isfile(".env")
        self.app_config = Config(
            ".env"
            if dotenv_file_exists and config_filename is None
            else config_filename
        )

        self.enabled = enabled
        self._default_limits = []
        self._application_limits = []
        self._in_memory_fallback: List[LimitGroup] = []
        self._in_memory_fallback_enabled = (
            in_memory_fallback_enabled or len(in_memory_fallback) > 0
        )
        self._exempt_routes: Set[str] = set()
        self._request_filters: List[Callable[..., bool]] = []
        self._headers_enabled = headers_enabled
        self._header_mapping: Dict[int, str] = {}
        self._retry_after: Optional[str] = retry_after
        self._strategy = strategy
        self._storage_uri = storage_uri
        self._storage_options = storage_options
        self._auto_check = auto_check
        self._swallow_errors = swallow_errors

        self._key_func = key_func
        self._key_prefix = key_prefix
        self._key_style = key_style

        for limit in set(default_limits):
            self._default_limits.extend(
                [
                    LimitGroup(
                        limit, self._key_func, None, False, None, None, None, 1, False
                    )
                ]
            )
        for limit in application_limits:
            self._application_limits.extend(
                [
                    LimitGroup(
                        limit,
                        self._key_func,
                        "global",
                        False,
                        None,
                        None,
                        None,
                        1,
                        False,
                    )
                ]
            )
        for limit in in_memory_fallback:
            self._in_memory_fallback.extend(
                [
                    LimitGroup(
                        limit, self._key_func, None, False, None, None, None, 1, False
                    )
                ]
            )
        self._route_limits: Dict[str, List[Limit]] = {}
        self._dynamic_route_limits: Dict[str, List[LimitGroup]] = {}
        # a flag to note if the storage backend is dead (not available)
        self._storage_dead: bool = False
        self._fallback_limiter = None
        self.__check_backend_count = 0
        self.__last_check_backend = time.time()
        self.__marked_for_limiting: Dict[str, List[Callable]] = {}

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
        self._storage = storage_from_string(
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
        app_limits: Optional[StrOrCallableStr] = self.get_app_config(
            C.APPLICATION_LIMITS, None
        )
        if not self._application_limits and app_limits:
            self._application_limits = [
                LimitGroup(
                    app_limits,
                    self._key_func,
                    "global",
                    False,
                    None,
                    None,
                    None,
                    1,
                    False,
                )
            ]

        conf_limits: Optional[StrOrCallableStr] = self.get_app_config(
            C.DEFAULT_LIMITS, None
        )
        if not self._default_limits and conf_limits:
            self._default_limits = [
                LimitGroup(
                    conf_limits, self._key_func, None, False, None, None, None, 1, False
                )
            ]
        fallback_enabled = self.get_app_config(C.IN_MEMORY_FALLBACK_ENABLED, False)
        fallback_limits: Optional[StrOrCallableStr] = self.get_app_config(
            C.IN_MEMORY_FALLBACK, None
        )
        if not self._in_memory_fallback and fallback_limits:
            self._in_memory_fallback = [
                LimitGroup(
                    fallback_limits,
                    self._key_func,
                    None,
                    False,
                    None,
                    None,
                    None,
                    1,
                    False,
                )
            ]
        if not self._in_memory_fallback_enabled:
            self._in_memory_fallback_enabled = (
                fallback_enabled or len(self._in_memory_fallback) > 0
            )

        if self._in_memory_fallback_enabled:
            self._fallback_storage = MemoryStorage()
            self._fallback_limiter = STRATEGIES[strategy](self._fallback_storage)

    def slowapi_startup(self) -> None:
        """
        Starlette startup event handler that links the app with the Limiter instance.
        """
        app.state.limiter = self  # type: ignore
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore

    def get_app_config(self, key: str, default_value: T = None) -> T:
        """
        Place holder until we find a better way to load config from app
        """
        return (
            self.app_config(key, default=default_value, cast=type(default_value))
            if default_value
            else self.app_config(key, default=default_value)
        )

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
            assert (
                self._fallback_limiter
            ), "Fallback limiter is needed when in memory fallback is enabled"
            return self._fallback_limiter
        else:
            return self._limiter

    def _inject_headers(
        self, response: Response, current_limit: Tuple[RateLimitItem, List[str]]
    ) -> Response:
        if self.enabled and self._headers_enabled and current_limit is not None:
            if not isinstance(response, Response):
                raise Exception(
                    "parameter `response` must be an instance of starlette.responses.Response"
                )
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
                existing_retry_after_header = response.headers.get("Retry-After")

                if existing_retry_after_header is not None:
                    reset_in = max(
                        self._determine_retry_time(existing_retry_after_header),
                        reset_in,
                    )

                response.headers[self._header_mapping[HEADERS.RETRY_AFTER]] = (
                    formatdate(reset_in)
                    if self._retry_after == "http-date"
                    else str(int(reset_in - time.time()))
                )
            except:
                if self._in_memory_fallback and not self._storage_dead:
                    self.logger.warning(
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

    def _inject_asgi_headers(
        self, headers: MutableHeaders, current_limit: Tuple[RateLimitItem, List[str]]
    ) -> MutableHeaders:
        """
        Injects 'X-RateLimit-Reset', 'X-RateLimit-Remaining', 'X-RateLimit-Limit'
        and 'Retry-After' headers into :headers parameter if needed.

        Basically the same as _inject_headers, but without access to the Response object.
        -> supports ASGI Middlewares.
        """
        if self.enabled and self._headers_enabled and current_limit is not None:
            try:
                window_stats: Tuple[int, int] = self.limiter.get_window_stats(
                    current_limit[0], *current_limit[1]
                )
                reset_in = 1 + window_stats[0]
                headers[self._header_mapping[HEADERS.LIMIT]] = str(
                    current_limit[0].amount
                )
                headers[self._header_mapping[HEADERS.REMAINING]] = str(window_stats[1])
                headers[self._header_mapping[HEADERS.RESET]] = str(reset_in)

                # response may have an existing retry after
                existing_retry_after_header = headers.get("Retry-After")

                if existing_retry_after_header is not None:
                    reset_in = max(
                        self._determine_retry_time(existing_retry_after_header),
                        reset_in,
                    )

                headers[self._header_mapping[HEADERS.RETRY_AFTER]] = (
                    formatdate(reset_in)
                    if self._retry_after == "http-date"
                    else str(int(reset_in - time.time()))
                )
            except Exception:
                if self._in_memory_fallback and not self._storage_dead:
                    self.logger.warning(
                        "Rate limit storage unreachable - falling back to"
                        " in-memory storage"
                    )
                    self._storage_dead = True
                    headers = self._inject_asgi_headers(headers, current_limit)
                if self._swallow_errors:
                    self.logger.exception(
                        "Failed to update rate limit headers. Swallowing error"
                    )
                else:
                    raise
        return headers

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

                cost = lim.cost(request) if callable(lim.cost) else lim.cost
                if not self.limiter.hit(lim.limit, *args, cost=cost):
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

    def _determine_retry_time(self, retry_header_value) -> int:
        try:
            retry_after_date: Optional[datetime] = parsedate_to_datetime(
                retry_header_value
            )
        except (TypeError, ValueError):
            retry_after_date = None

        if retry_after_date is not None:
            return int(time.mktime(retry_after_date.timetuple()))

        try:
            retry_after_int: int = int(retry_header_value)
        except TypeError:
            raise ValueError(
                "Retry-After Header does not meet RFC2616 - value is not of http-date or int type."
            )

        return int(time.time() + retry_after_int)

    def _check_request_limit(
        self,
        request: Request,
        endpoint_func: Optional[Callable[..., Any]],
        in_middleware: bool = True,
    ) -> None:
        """
        Determine if the request is within limits
        """
        endpoint_url = request["path"] or ""
        view_func = endpoint_func

        endpoint_func_name = (
            f"{view_func.__module__}.{view_func.__name__}" if view_func else ""
        )
        _endpoint_key = endpoint_url if self._key_style == "url" else endpoint_func_name
        # cases where we don't need to check the limits
        if (
            not _endpoint_key
            or not self.enabled
            # or we are sending a static file
            # or view_func == current_app.send_static_file
            or endpoint_func_name in self._exempt_routes
            or any(fn() for fn in self._request_filters)
        ):
            return
        limits: List[Limit] = []
        dynamic_limits: List[Limit] = []

        if not in_middleware:
            limits = (
                self._route_limits[endpoint_func_name]
                if endpoint_func_name in self._route_limits
                else []
            )
            dynamic_limits = []
            if endpoint_func_name in self._dynamic_route_limits:
                for lim in self._dynamic_route_limits[endpoint_func_name]:
                    try:
                        dynamic_limits.extend(list(lim.with_request(request)))
                    except ValueError as e:
                        self.logger.error(
                            "failed to load ratelimit for view function %s (%s)",
                            endpoint_func_name,
                            e,
                        )

        try:
            all_limits: List[Limit] = []
            if self._storage_dead and self._fallback_limiter:
                if in_middleware and endpoint_func_name in self.__marked_for_limiting:
                    pass
                else:
                    if self.__should_check_backend() and self._storage.check():
                        self.logger.info("Rate limit storage recovered")
                        self._storage_dead = False
                        self.__check_backend_count = 0
                    else:
                        all_limits = list(itertools.chain(*self._in_memory_fallback))
            if not all_limits:
                route_limits: List[Limit] = limits + dynamic_limits
                all_limits = (
                    list(itertools.chain(*self._application_limits))
                    if in_middleware
                    else []
                )
                all_limits += route_limits
                combined_defaults = all(
                    not limit.override_defaults for limit in route_limits
                )
                if (
                    not route_limits
                    and not (
                        in_middleware
                        and endpoint_func_name in self.__marked_for_limiting
                    )
                    or combined_defaults
                ):
                    all_limits += list(itertools.chain(*self._default_limits))
            # actually check the limits, so far we've only computed the list of limits to check
            self.__evaluate_limits(request, _endpoint_key, all_limits)
        except Exception as e:  # no qa
            if isinstance(e, RateLimitExceeded):
                raise
            if self._in_memory_fallback_enabled and not self._storage_dead:
                self.logger.warn(
                    "Rate limit storage unreachable - falling back to"
                    " in-memory storage"
                )
                self._storage_dead = True
                self._check_request_limit(request, endpoint_func, in_middleware)
            else:
                if self._swallow_errors:
                    self.logger.exception("Failed to rate limit. Swallowing error")
                else:
                    raise

    def __limit_decorator(
        self,
        limit_value: StrOrCallableStr,
        key_func: Optional[Callable[..., str]] = None,
        shared: bool = False,
        scope: Optional[StrOrCallableStr] = None,
        per_method: bool = False,
        methods: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        exempt_when: Optional[Callable[..., bool]] = None,
        cost: Union[int, Callable[..., int]] = 1,
        override_defaults: bool = True,
    ) -> Callable[..., Any]:
        _scope = scope if shared else None

        def decorator(func: Callable[..., Response]):
            keyfunc = key_func or self._key_func
            name = f"{func.__module__}.{func.__name__}"
            dynamic_limit = None
            static_limits: List[Limit] = []
            if callable(limit_value):
                dynamic_limit = LimitGroup(
                    limit_value,
                    keyfunc,
                    _scope,
                    per_method,
                    methods,
                    error_message,
                    exempt_when,
                    cost,
                    override_defaults,
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
                            cost,
                            override_defaults,
                        )
                    )
                except ValueError as e:
                    self.logger.error(
                        "Failed to configure throttling for %s (%s)",
                        name,
                        e,
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
                    if self.enabled:
                        request = kwargs.get("request", args[idx] if args else None)
                        if not isinstance(request, Request):
                            raise Exception(
                                "parameter `request` must be an instance of starlette.requests.Request"
                            )

                        if self._auto_check and not getattr(
                            request.state, "_rate_limiting_complete", False
                        ):
                            self._check_request_limit(request, func, False)
                            request.state._rate_limiting_complete = True
                    response = await func(*args, **kwargs)  # type: ignore
                    if self.enabled:
                        if not isinstance(response, Response):
                            # get the response object from the decorated endpoint function
                            self._inject_headers(
                                kwargs.get("response"), request.state.view_rate_limit  # type: ignore
                            )
                        else:
                            self._inject_headers(
                                response, request.state.view_rate_limit
                            )
                    return response

                return async_wrapper

            else:
                # Handle sync request/response functions.
                @functools.wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Response:
                    # get the request object from the decorated endpoint function
                    if self.enabled:
                        request = kwargs.get("request", args[idx] if args else None)
                        if not isinstance(request, Request):
                            raise Exception(
                                "parameter `request` must be an instance of starlette.requests.Request"
                            )

                        if self._auto_check and not getattr(
                            request.state, "_rate_limiting_complete", False
                        ):
                            self._check_request_limit(request, func, False)
                            request.state._rate_limiting_complete = True
                    response = func(*args, **kwargs)
                    if self.enabled:
                        if not isinstance(response, Response):
                            # get the response object from the decorated endpoint function
                            self._inject_headers(
                                kwargs.get("response"), request.state.view_rate_limit  # type: ignore
                            )
                        else:
                            self._inject_headers(
                                response, request.state.view_rate_limit
                            )
                    return response

                return sync_wrapper

        return decorator

    def limit(
        self,
        limit_value: StrOrCallableStr,
        key_func: Optional[Callable[..., str]] = None,
        per_method: bool = False,
        methods: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        exempt_when: Optional[Callable[..., bool]] = None,
        cost: Union[int, Callable[..., int]] = 1,
        override_defaults: bool = True,
    ) -> Callable:
        """
        Decorator to be used for rate limiting individual routes.

        * **limit_value**: rate limit string or a callable that returns a string.
         :ref:`ratelimit-string` for more details.
        * **key_func**: function/lambda to extract the unique identifier for
         the rate limit. defaults to remote address of the request.
        * **per_method**: whether the limit is sub categorized into the http
         method of the request.
        * **methods**: if specified, only the methods in this list will be rate
         limited (default: None).
        * **error_message**: string (or callable that returns one) to override the
         error message used in the response.
        * **exempt_when**: function returning a boolean indicating whether to exempt
        the route from the limit
        * **cost**: integer (or callable that returns one) which is the cost of a hit
        * **override_defaults**: whether to override the default limits (default: True)
        """
        return self.__limit_decorator(
            limit_value,
            key_func,
            per_method=per_method,
            methods=methods,
            error_message=error_message,
            exempt_when=exempt_when,
            cost=cost,
            override_defaults=override_defaults,
        )

    def shared_limit(
        self,
        limit_value: StrOrCallableStr,
        scope: StrOrCallableStr,
        key_func: Optional[Callable[..., str]] = None,
        error_message: Optional[str] = None,
        exempt_when: Optional[Callable[..., bool]] = None,
        cost: Union[int, Callable[..., int]] = 1,
        override_defaults: bool = True,
    ) -> Callable:
        """
        Decorator to be applied to multiple routes sharing the same rate limit.

        * **limit_value**: rate limit string or a callable that returns a string.
         :ref:`ratelimit-string` for more details.
        * **scope**: a string or callable that returns a string
         for defining the rate limiting scope.
        * **key_func**: function/lambda to extract the unique identifier for
         the rate limit. defaults to remote address of the request.
        * **per_method**: whether the limit is sub categorized into the http
         method of the request.
        * **methods**: if specified, only the methods in this list will be rate
         limited (default: None).
        * **error_message**: string (or callable that returns one) to override the
         error message used in the response.
        * **exempt_when**: function returning a boolean indicating whether to exempt
        the route from the limit
        * **cost**: integer (or callable that returns one) which is the cost of a hit
        * **override_defaults**: whether to override the default limits (default: True)
        """
        return self.__limit_decorator(
            limit_value,
            key_func,
            True,
            scope,
            error_message=error_message,
            exempt_when=exempt_when,
            cost=cost,
            override_defaults=override_defaults,
        )

    def exempt(self, obj):
        """
        Decorator to mark a view as exempt from rate limits.
        """
        name = "%s.%s" % (obj.__module__, obj.__name__)

        self._exempt_routes.add(name)

        if asyncio.iscoroutinefunction(obj):

            @wraps(obj)
            async def __async_inner(*a, **k):
                return await obj(*a, **k)

            return __async_inner
        else:

            @wraps(obj)
            def __inner(*a, **k):
                return obj(*a, **k)

            return __inner
