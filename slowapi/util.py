from starlette.requests import Request


def get_remote_address(request: Request) -> str:
    """
    Returns the ip address for the current request (or 127.0.0.1 if none found)
    """
    is_local = not request.client or not request.client.host

    if is_local:
        return "127.0.0.1"
    else:
        return request.client.host


def get_ipaddr(request: Request) -> str:
    """
    Returns the ip address for the current request (or 127.0.0.1 if none found)
     based on the X-Forwarded-For headers.
     Note that a more robust method for determining IP address of the client is
     provided by uvicorn's ProxyHeadersMiddleware.
    """
    has_forwarded = "X_FORWARDED_FOR" in request.headers

    if has_forwarded:
        return request.headers["X_FORWARDED_FOR"]
    else:
        return get_remote_address(request)
