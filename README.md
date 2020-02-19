# SlowApi

A rate limiting library for Starlette and FastAPI adapted from [flask-limiter](http://github.com/alisaifee/flask-limiter).

Note: this is alpha quality code still, the API may change, and things may fall apart while you try it.

# Quick start

## Starlette

```python
    from starlette.applications import Starlette
    from slowapi import Limiter, _rate_limit_exceeded_handler

    limiter = Limiter(key_func=get_remote_address)
    app = Starlette()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @limiter.limit("5/minute")
    async def homepage(request: Request):
        return PlainTextResponse("test")

    app.add_route("/home", homepage)
```

The above app will have a route `t1` that will accept up to 5 requests per minute. Requests beyond this limit will be answered with an HTTP 429 error, and the body of the view will not run.

## FastAPI

```python
    from fastapi import FastAPI
    from slowapi import Limiter, _rate_limit_exceeded_handler

    limiter = Limiter(key_func=get_remote_address)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/home")
    @limiter.limit("5/minute")
    async def homepage(request: Request):
        return PlainTextResponse("test")
```

This will provide the same result, but with a FastAPI app.

# Features

Most feature are coming from (will come from) FlaskLimiter and the underlying [limits](https://limits.readthedocs.io/).

Supported now:
- Single and multiple `limit` decorator on endpoint functions to apply limits
- redis, memcached and memory backends to track your limits (memory as a fallback)
- support for sync and async HTTP endpoints
- Support for shared limits across a set of routes


# Limitations and known issues

  * There is no support for default limits yet (in other words, the only default limit supported is "unlimited")

  * The `request` argument must be explicitly passed to your endpoint, or `slowapi` won't be able to hook into it. In other words, write:

```python
    @limiter.limit("5/minute")
    async def myendpoint(request: Request)
        pass
```

and not:

```python
    @limiter.limit("5/minute")
    async def myendpoint()
        pass
```

  * `websocket` endpoints are not supported yet.

# Developing and contributing

PRs are more than welcome! Please include tests for your changes :)

The package uses [poetry](https://python-poetry.org) to manage dependencies. To setup your dev env:

```bash
$ poetry install
```

To run the tests:
```bash
$ pytest
```

# Credits

Credits go to [flask-limiter](https://github.com/alisaifee/flask-limiter) of which SlowApi is a (still partial) adaptation to Starlette and FastAPI.
It's also important to mention that the actual rate limiting work is done be [limits](https://github.com/alisaifee/limits/), `slowapi` is just a wrapper around it.
