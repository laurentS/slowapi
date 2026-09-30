# Streaming Middleware Fix Report

## Issue

`SlowAPIASGIMiddleware` forwarded the stored `http.response.start` ASGI message whenever it received an `http.response.body` message. Streaming responses emit multiple body messages, so the middleware sent the response-start message once per chunk. ASGI servers such as Uvicorn reject repeated response-start messages.

## Changes

- Added a `response_started` flag to `_ASGIMiddlewareResponder`.
- Forwarded the response-start message, including rate-limit headers and error status handling, only on the first body message.
- Continued forwarding every body message unchanged.
- Added a regression test using FastAPI and `StreamingResponse` with three chunks.

## Verification

- Before the fix, the regression test failed with `assert 4 == 1` because four response-start messages were emitted.
- After the fix, `pytest tests/test_streaming.py -q` passed: `1 passed`.
- The full suite after the fix reported `92 passed, 12 failed`.
- All 12 failures were the same pre-existing Starlette compatibility failure: `AttributeError: 'Starlette' object has no attribute 'route'` in `tests/test_starlette_extension.py`.

## Scope

No unrelated Starlette compatibility failures were changed. The fix is limited to ensuring that an ASGI response-start message is sent exactly once for streaming responses.
