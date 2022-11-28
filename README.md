# SlowApi

A rate limiting library for Starlette and FastAPI adapted from [flask-limiter](http://github.com/alisaifee/flask-limiter).

This package is used in various production setups, handling millions of requests per month, and seems to behave as expected.
There might be some API changes when changing the code to be fully `async`, but we will notify users via appropriate `semver` version changes.

The documentation is on [read the docs](https://slowapi.readthedocs.io/en/latest/).

# Quick start

## Installation

`slowapi` is available from [pypi](https://pypi.org/project/slowapi/) so you can install it as usual:

```
$ pip install slowapi
```

# Features

Most feature are coming from FlaskLimiter and the underlying [limits](https://limits.readthedocs.io/).

Supported now:

- Single and multiple `limit` decorator on endpoint functions to apply limits
- redis, memcached and memory backends to track your limits (memory as a fallback)
- support for sync and async HTTP endpoints
- Support for shared limits across a set of routes


# Limitations and known issues

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
It's also important to mention that the actual rate limiting work is done by [limits](https://github.com/alisaifee/limits/), `slowapi` is just a wrapper around it.
