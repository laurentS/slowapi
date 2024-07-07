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

#### Note: config file is set to ".env" by default. Therefore, if you have a .env file setup for something else already, specify the config_filename parameter
```python
limiter = Limiter(key_func=get_remote_address, default_limits=["1/minute"], config_filename=".your_config_file")
```

## Use redis as backend for the limiter

```python
limiter = Limiter(key_func=get_remote_address, storage_uri="redis://<host>:<port>/n")
```

where the /n in the redis url is the database number. To use the default one, just drop the /n from the url.

There are more examples in the [limits docs](https://limits.readthedocs.io/en/stable/storage.html) which is the library slowapi uses to manage storage.

## Set a custom cost per hit

Setting a custom cost per hit is useful to throttle requests based on something else than the request count.

Define a function which takes a request as parameter and returns a cost and pass it to the `limit` decorator:

```python
    def get_hit_cost(request: Request) -> int:
        return len(request)

    @app.route("/someroute")
    @limiter.limit("100/minute", cost=get_hit_cost)
    def t(request: Request):
        return PlainTextResponse("I'm limited by the request size")
```

## WSGI vs ASGI Middleware

`SlowAPIMiddleware` inheriting from Starlette's BaseHTTPMiddleware, you can find an alternative ASGI Middleware `SlowAPIASGIMiddleware`.  
A few reasons to choose the ASGI middleware over the HTTP one are:
- Starlette [is probably going to deprecate BaseHTTPMiddleware](https://github.com/encode/starlette/issues/1678)
- ASGI middlewares [are more performant than WSGI ones](https://github.com/tiangolo/fastapi/issues/2241)
- built-in support for asynchronous exception handlers
- ...


Both middlewares are added to your application the same way:
```python
app = Starlette() # or FastAPI()
app.add_middleware(SlowAPIMiddleware)
```
or
```python
app = Starlette() # or FastAPI()
app.add_middleware(SlowAPIASGIMiddleware)
```

## Use view function's name instead of full endpoint as part of the storage key

Let's use this route as an example:
```python
@app.route("/some_route/{some_param}")
def my_func(some_param):
    ...
```

```python
limiter = Limiter(key_func=lambda: "mock", default_limits=["1/minute"], key_style="url")
```

When initializing the Limiter object with `key_style="url"`, it will use the full endpoint url as part of the storage key.

When calling the `/some_route/my_param` endpoint would result with a key shaped like: `LIMITER/mock//some_route/my_param/1/1/minute`.

> This means, that if the route contains some URL parameter, calling the endpoint with different parameters won't share the limitations.

```python
limiter = Limiter(key_func=lambda: "mock", default_limits=["1/minute"], key_style="endpoint")
```

When initializing the Limiter object with `key_style="endpoint"`, it will use the function name as part of the storage key.

When calling the `/some_route/my_param` endpoint would result with a key shaped like: `LIMITER/mock/{module}.my_func/1/1/minute`

> This means, that if the route contains some URL parameter, calling the endpoint with different parameters will still share the limitations, since the view function is the same.
