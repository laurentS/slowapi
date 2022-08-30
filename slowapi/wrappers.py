import inspect
from typing import Callable, Iterator, List, Optional, Union

from limits import RateLimitItem, parse_many  # type: ignore


class Limit(object):
    """
    simple wrapper to encapsulate limits and their context
    """

    def __init__(
        self,
        limit: RateLimitItem,
        key_func: Callable[..., str],
        scope: Optional[Union[str, Callable[..., str]]],
        per_method: bool,
        methods: Optional[List[str]],
        error_message: Optional[Union[str, Callable[..., str]]],
        exempt_when: Optional[Callable[..., bool]],
        cost: Union[int, Callable[..., int]],
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

    @property
    def scope(self) -> str:
        # flack.request.endpoint is the name of the function for the endpoint
        # FIXME: how to get the request here?
        if self.__scope is None:
            return ""
        else:
            return (
                self.__scope(request.endpoint)  # type: ignore
                if callable(self.__scope)
                else self.__scope
            )


class LimitGroup(object):
    """
    represents a group of related limits either from a string or a callable that returns one
    """

    def __init__(
        self,
        limit_provider: Union[str, Callable[..., str]],
        key_function: Callable[..., str],
        scope: Optional[Union[str, Callable[..., str]]],
        per_method: bool,
        methods: Optional[List[str]],
        error_message: Optional[Union[str, Callable[..., str]]],
        exempt_when: Optional[Callable[..., bool]],
        cost: Union[int, Callable[..., int]],
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
        self.request = None

    def __iter__(self) -> Iterator[Limit]:
        if callable(self.__limit_provider):
            if "key" in inspect.signature(self.__limit_provider).parameters.keys():
                assert (
                    "request" in inspect.signature(self.key_function).parameters.keys()
                ), f"Limit provider function {self.key_function.__name__} needs a `request` argument"
                if self.request is None:
                    raise Exception("`request` object can't be None")
                limit_raw = self.__limit_provider(self.key_function(self.request))
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

    def with_request(self, request):
        self.request = request
        return self
