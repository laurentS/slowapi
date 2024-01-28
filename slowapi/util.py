from asyncio import iscoroutinefunction
from functools import wraps
from inspect import signature, Parameter

from starlette.requests import Request
from typing import Callable, List


def get_ipaddr(request: Request) -> str:
    """
    Returns the ip address for the current request (or 127.0.0.1 if none found)
     based on the X-Forwarded-For headers.
     Note that a more robust method for determining IP address of the client is
     provided by uvicorn's ProxyHeadersMiddleware.
    """
    if "X_FORWARDED_FOR" in request.headers:
        return request.headers["X_FORWARDED_FOR"]
    else:
        if not request.client or not request.client.host:
            return "127.0.0.1"

        return request.client.host


def get_remote_address(request: Request) -> str:
    """
    Returns the ip address for the current request (or 127.0.0.1 if none found)
    """
    if not request.client or not request.client.host:
        return "127.0.0.1"

    return request.client.host


def get_request_param(func: Callable) -> List[Parameter]:
    """Retrieve list of parameters that are a Request"""
    sig = signature(func)
    params = list(sig.parameters.values())
    return [param for param in params if param.annotation == Request]


def add_request_signature(func: Callable):
    """Adds starlette.Request argument to function's signature so that it'll be accessible to custom decorators"""

    def scrap_req(func: Callable, args, kwargs):
        if getattr(func, "scrap_req", False):
            req_param = get_request_param(func)[0]
            try:
                del kwargs[req_param.name]
            except KeyError:
                # Request is not in kwargs for some reason delete from args
                # Deletion index: 0
                del args[0]
        return args, kwargs

    if iscoroutinefunction(func):

        @wraps(func)
        async def wrapper(*args, **kwargs):
            args, kwargs = scrap_req(func, args, kwargs)
            return await func(*args, **kwargs)

    else:

        @wraps(func)
        def wrapper(*args, **kwargs):
            args, kwargs = scrap_req(func, args, kwargs)
            return func(*args, **kwargs)

    sig = signature(func)
    params = list(sig.parameters.values())

    rq = get_request_param(func)
    if len(rq) == 1:
        if not hasattr(func, "scrap_req"):  # Ignore if already set
            func.scrap_req = False
    else:
        func.scrap_req = True
        name = "request"  # Slowapi should allow for request to be anything <- param name generator
        param_names = [pname.name for pname in params]
        if name not in param_names:
            func.req = name

            req = Parameter(name=name, kind=Parameter.POSITIONAL_OR_KEYWORD, annotation=Request)
            params.insert(0, req)
            sig = sig.replace(parameters=params)
            func.__signature__ = sig
        else:
            fname = f"{func.__module__}.{func.__name__}"
            raise Exception(f"Remove 'request' argument from function {fname}"
                            f" or add [request : starlette.Request] manually.")

    return wrapper