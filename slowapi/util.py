from starlette.requests import Request

def get_ip_address(request: Request, proxy_middleware: bool = False, proxy_nginx: bool = False) -> str:
    """
    Returns the IP address for the current request.
    Handles different proxy configurations based on parameters.

    :param proxy_middleware: If True, uses the 'X-Forwarded-For' header (typically for Uvicorn's ProxyHeadersMiddleware).
    :param proxy_nginx: If True, uses the 'x-forwarded-for' header (typically for Nginx proxy).
    :return: The client IP address or '127.0.0.1' if no valid IP is found.
    """
    if proxy_middleware and proxy_nginx:
        raise ValueError("Both proxy_middleware and proxy_nginx cannot be True at the same time.")
    
    if proxy_nginx:
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
    
    if proxy_middleware:
        if "X_FORWARDED_FOR" in request.headers:
            return request.headers["X_FORWARDED_FOR"]
    
    if request.client and request.client.host:
        return request.client.host
    
    return "127.0.0.1"
