# SlowApi

A rate limiting library for Starlette and FastAPI adapted from [flask-limiter](http://github.com/alisaifee/flask-limiter).

Note: this is alpha quality code still, the API may change, and things may fall apart while you try it.

# Quick start

## Installation

`slowapi` is available from [pypi](https://pypi.org/project/slowapi/) so you can install it as usual:

```
$ pip install slowapi
```

## Starlette

```python
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.requests import Request
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

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
    from fastapi import FastAPI, Request, Response
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Note: the route decorator must be above the limit decorator, not below it
    @app.get("/home")
    @limiter.limit("5/minute")
    async def home(request: Request):
        return Response("test")

    @app.get("/mars")
    @limiter.limit("5/minute")
    async def mars(request: Request, response: Response):
        return {"key": "value"}
```

This will provide the same result, but with a FastAPI app.

# Features

Most feature are coming from (will come from) FlaskLimiter and the underlying [limits](https://limits.readthedocs.io/).

Supported now:

- Single and multiple `limit` decorator on endpoint functions to apply limits
- Redis, memcached and memory backends to track your limits (memory as a fallback)
- Support for sync and async HTTP endpoints
- Support for shared limits across a set of routes
- Support for default global limit
- Support for a custom cost per hit

# Limitations and known issues

## Request argument

The `request` argument must be explicitly passed to your endpoint, or `slowapi` won't be able to hook into it. In other words, write:

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

## Response type

Similarly, if the returned response is not an instance of `Response` and
will be built at an upper level in the middleware stack, you'll need to provide
the response object explicitly if you want the `Limiter` to modify the headers
(`headers_enabled=True`):

```python
@limiter.limit("5/minute")
async def myendpoint(request: Request, response: Response)
return {"key": "value"}
```

## Decorators order

The order of decorators matters. It is not a bug, the `limit` decorator needs the `request` argument in the function it decorates (see above).
This works
```
@router.get("/test")
@limiter.limit("2/minute")
async def test(
    request: Request
):
return "hi"
```

but this doesnt

```
@limiter.limit("2/minute")
@router.get("/test")
async def test(
    request: Request
):
return "hi"
```

## Websocket endpoints

`websocket` endpoints are not supported yet.

# Examples of setup

See [examples](examples.md)

# Developing and contributing

PRs are more than welcome! Please include tests for your changes :)

Please run [black](black.readthedocs.io/) on your code before committing, or your PR will not pass the tests.

The package uses [poetry](https://python-poetry.org) to manage dependencies. To setup your dev env:

```bash
$ poetry install
```

To run the tests:
```bash
$ pytest
```

## Releasing a new version

`slowapi` tries to follow [semantic versioning](https://semver.org/).

Releases are published directly from CI (github actions). To create a new release:
- Update `CHANGELOG.md` and the version in `pyproject.toml`,
- Commit those changes to a new PR,
- Get the PR reviewed and merged,
- Tag the merge commit with the same version number prefixed with `v`, eg. `v0.1.6`,
- Push the tag to trigger the release.

# Credits

Credits go to [flask-limiter](https://github.com/alisaifee/flask-limiter) of which SlowApi is a (still partial) adaptation to Starlette and FastAPI.
It's also important to mention that the actual rate limiting work is done by [limits](https://github.com/alisaifee/limits/), `slowapi` is just a wrapper around it.

The documentation is built using [mkDocs](https://www.mkdocs.org/) and the API documentation is generated using [mkautodoc](https://github.com/tomchristie/mkautodoc).
