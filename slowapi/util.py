from datetime import datetime, timedelta
from email.utils import parsedate_tz
from typing import Optional

from starlette.requests import Request


def get_ipaddr(request: Request) -> str:
    """
    Returns the ip address for the current request (or 127.0.0.1 if none found)
     based on the X-Forwarded-For headers.
     Note that a more robust method for determining IP address of the client is
     provided by uvicorn's ProxyHeadersMiddleware.
    """
    if "X_FORWARDED_FOR" in request.headers:
        r = request.headers["X_FORWARDED_FOR"]
        return r
    else:
        return request.client.host or "127.0.0.1"


def get_remote_address(request: Request) -> str:
    """
    Returns the ip address for the current request (or 127.0.0.1 if none found)
    """
    return request.client.host or "127.0.0.1"
