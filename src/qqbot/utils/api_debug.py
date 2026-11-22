"""Optional raw HTTP logging for model API requests."""

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

from src.qqbot.config import config


_WRITE_LOCK = threading.Lock()
_DEBUG_STATE_KEY = "qqbot_api_debug"


def _enabled() -> bool:
    return bool(getattr(config, "ENABLE_LLM_API_DEBUG", False))


def _log_path() -> Path:
    return Path(config.LLM_API_DEBUG_FILE).expanduser()


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _text(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _headers(headers: httpx.Headers) -> str:
    visible = {}
    for key, value in headers.items():
        visible[key] = (
            "[REDACTED]"
            if key.lower() in {"authorization", "api-key", "x-api-key"}
            else value
        )
    return json.dumps(visible, ensure_ascii=False, sort_keys=True)


def _request_body(request: httpx.Request) -> str:
    try:
        return _text(request.content)
    except Exception as error:
        return f"<request body unavailable: {type(error).__name__}: {error}>"


def _append(entry: str) -> None:
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(entry)
                stream.flush()
    except OSError:
        # Debug logging must not make a model request fail because the path is unavailable.
        return


def _request_entry(request: httpx.Request, request_id: str, sent_at: str) -> str:
    return (
        f"\n===== QQBOT API REQUEST {request_id} =====\n"
        f"sent_at: {sent_at}\n"
        f"method: {request.method}\n"
        f"url: {request.url}\n"
        f"headers: {_headers(request.headers)}\n"
        "body:\n"
        f"{_request_body(request)}\n"
        "===== END REQUEST =====\n"
    )


def _response_entry(response: httpx.Response, request_id: str, sent_at: str,
                    received_at: str, elapsed: float) -> str:
    return (
        f"\n===== QQBOT API RESPONSE {request_id} =====\n"
        f"sent_at: {sent_at}\n"
        f"received_at: {received_at}\n"
        f"elapsed_seconds: {elapsed:.3f}\n"
        f"status_code: {response.status_code}\n"
        f"headers: {_headers(response.headers)}\n"
        "body:\n"
        f"{_text(response.content)}\n"
        "===== END RESPONSE =====\n"
    )


def log_request(request: httpx.Request) -> None:
    """HTTPX request hook for the synchronous client."""
    if not _enabled():
        return
    request_id = uuid.uuid4().hex
    sent_at = _timestamp()
    request.extensions[_DEBUG_STATE_KEY] = {
        "request_id": request_id,
        "sent_at": sent_at,
        "started": time.perf_counter(),
    }
    _append(_request_entry(request, request_id, sent_at))


async def log_async_request(request: httpx.Request) -> None:
    """HTTPX request hook for the asynchronous client."""
    log_request(request)


def log_response(response: httpx.Response) -> None:
    """HTTPX response hook for the synchronous client."""
    if not _enabled():
        return
    state = response.request.extensions.get(_DEBUG_STATE_KEY, {})
    response.read()
    _append(_response_entry(
        response,
        state.get("request_id", "unknown"),
        state.get("sent_at", "unknown"),
        _timestamp(),
        time.perf_counter() - state.get("started", time.perf_counter()),
    ))


async def log_async_response(response: httpx.Response) -> None:
    """HTTPX response hook for the asynchronous client."""
    if not _enabled():
        return
    state = response.request.extensions.get(_DEBUG_STATE_KEY, {})
    await response.aread()
    _append(_response_entry(
        response,
        state.get("request_id", "unknown"),
        state.get("sent_at", "unknown"),
        _timestamp(),
        time.perf_counter() - state.get("started", time.perf_counter()),
    ))
