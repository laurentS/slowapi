# Examples

Here are some examples of setup to get you started. Please open an issue if you have a use case that is not included here.

The tests show a lot of different use cases that are not all covered here.

## Apply a global (default) limit to all routes

```python
    from starlette.applications import Starlette
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address, default_limits=["1/minute"])
    app = Starlette()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # this will be limited by the default_limits
    async def homepage(request: Request):
        return PlainTextResponse("Only once per minute")

    app.add_route("/home", homepage)
```

## Exempt a route from the global limit

```python
    @app.route("/someroute")
    @limiter.exempt
    def t(request: Request):
        return PlainTextResponse("I'm unlimited")
```

## Dynamically change the rate limit

```python
    def dynamic_limit():
        # do anything you want here
        return "1/minute"

    @app.route("/homepage")
    @limiter.limit(dynamic_limit)
    async def homepage(request: Request):
        return PlainTextResponse("test")
```


## Disable the limiter entirely

You might want to disable the limiter, for instance for testing, etc...
Note that this disables it entirely, for all users. It is essentially as if the limiter was not there.
Simply pass `enabled=False` to the constructor.

```python
    limiter = Limiter(key_func=get_remote_address, enabled=False)

    @app.route("/someroute")
    @limiter.exempt
    def t(request: Request):
        return PlainTextResponse("I'm unlimited")
```

You can always switch this during the lifetime of the limiter:

```python
    limiter.enabled = False
```

## Use redis as backend for the limiter

```python
limiter = Limiter(key_func=get_remote_address, storage_uri="redis://<host>:<port>/n")
```

where the /n in the redis url is the database number. To use the default one, just drop the /n from the url.

There are more examples in the [limits docs](https://limits.readthedocs.io/en/stable/storage.html) which is the library slowapi uses to manage storage.
