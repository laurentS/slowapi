from typing import Iterator, List, Optional

from limits import RateLimitItem, parse_many
from starlette.requests import Request

from .types import (
    Cost,
    ErrorMessage,
    ExemptWhen,
    KeyFn,
    LimitProvider,
    Scope,
    is_limit_provider_fn,
    is_request_fn,
)


class Limit(object):
    """
    simple wrapper to encapsulate limits and their context
    """

    def __init__(
        self,
        limit: RateLimitItem,
        key_func: KeyFn,
        scope: Optional[Scope],
        per_method: bool,
        methods: Optional[List[str]],
        error_message: Optional[ErrorMessage],
        exempt_when: Optional[ExemptWhen],
        cost: Cost,
        override_defaults: bool,
    ) -> None:
        self.limit = limit
        self.key_func = key_func
        self.__scope = scope
        self.per_method = per_method
        self.methods = methods
        self.error_message = error_message
        self.exempt_when = exempt_when
        self.cost = cost
        self.override_defaults = override_defaults

    @property
    def is_exempt(self) -> bool:
        """
        Check if the limit is exempt.
        Return True to exempt the route from the limit.
        """
        return self.exempt_when() if self.exempt_when is not None else False

    def scope(self, request: Request) -> str:
        if self.__scope is None:
            return ""
        else:
            return self.__scope(request) if callable(self.__scope) else self.__scope


class LimitGroup(object):
    """
    represents a group of related limits either from a string or a callable that returns one
    """

    def __init__(
        self,
        limit_provider: LimitProvider,
        key_function: KeyFn,
        scope: Optional[Scope],
        per_method: bool,
        methods: Optional[List[str]],
        error_message: Optional[ErrorMessage],
        exempt_when: Optional[ExemptWhen],
        cost: Cost,
        override_defaults: bool,
    ):
        self.__limit_provider = limit_provider
        self.__scope = scope
        self.key_function = key_function
        self.per_method = per_method
        self.methods = methods and [m.lower() for m in methods] or methods
        self.error_message = error_message
        self.exempt_when = exempt_when
        self.cost = cost
        self.override_defaults = override_defaults

    def resolve(self, request: Optional[Request] = None) -> Iterator[Limit]:
        if callable(self.__limit_provider):
            if is_limit_provider_fn(self.__limit_provider):
                assert is_request_fn(
                    self.key_function
                ), f"Limit provider function {getattr(self.key_function, '__name__', str(self.key_function))} needs a `request` argument"
                if request is None:
                    raise Exception("`request` object can't be None")
                limit_raw = self.__limit_provider(self.key_function(request))
            else:
                limit_raw = self.__limit_provider()
        else:
            limit_raw = self.__limit_provider
        limit_items: List[RateLimitItem] = parse_many(limit_raw)
        for limit in limit_items:
            yield Limit(
                limit,
                self.key_function,
                self.__scope,
                self.per_method,
                self.methods,
                self.error_message,
                self.exempt_when,
                self.cost,
                self.override_defaults,
            )
