from starlette.requests import Request


def get_ipaddr(request: Request) -> str:
    """
    Returns the ip address for the current request (or 127.0.0.1 if none found)
     based on the X-Forwarded-For headers.
     Note that a more robust method for determining IP address of the client is
     provided by uvicorn's ProxyHeadersMiddleware.
    """
    forwarded = (
        request.headers.get("x-forwarded-for")
        or request.headers.get("x_forwarded_for")
        or request.headers.get("X_FORWARDED_FOR")
    )
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        if client_ip:
            return client_ip

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
