from __future__ import annotations

import inspect
from typing import Any, Callable, TypeVar, Union

from starlette.requests import Request
from typing_extensions import Protocol, TypeIs

T = TypeVar("T", covariant=True)


class RequestFn(Protocol[T]):
    def __call__(self, request: Request) -> T: ...


PlainFn = Callable[[], T]
ValueOrFn = Union[T, PlainFn[T]]
MaybeRequestFn = Union[PlainFn[T], RequestFn[T]]
ValueOrRequestFn = Union[T, RequestFn[T]]

KeyFn = MaybeRequestFn[str]
Scope = ValueOrRequestFn[str]
ErrorMessage = ValueOrFn[str]
ExemptWhen = PlainFn[bool]
Cost = ValueOrRequestFn[int]


class LimitProviderFn(Protocol):
    def __call__(self, key: str) -> str: ...


LimitProvider = Union[str, PlainFn[str], LimitProviderFn]


def is_limit_provider_fn(func: Any) -> TypeIs[LimitProviderFn]:
    return "key" in inspect.signature(func).parameters.keys()


def is_request_fn(func: Any) -> TypeIs[RequestFn]:
    return "request" in inspect.signature(func).parameters.keys()
