"""Optional raw HTTP logging for model API requests."""

import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

from src.qqbot.config import config


_WRITE_LOCK = threading.Lock()
_DEBUG_STATE_KEY = "qqbot_api_debug"
_IMAGE_DATA_KEYS = {"b64_json", "base64", "image_base64", "image_data", "image_bytes"}
_DATA_URL_PATTERN = re.compile(r"data:(image/[^;,]+);base64,([A-Za-z0-9+/=\r\n]+)")


def _enabled() -> bool:
    return bool(getattr(config, "ENABLE_LLM_API_DEBUG", False))


def _log_path() -> Path:
    return Path(config.LLM_API_DEBUG_FILE).expanduser()


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _image_placeholder(value: str) -> str:
    return f"[image data omitted: {len(value)} chars]"


def _sanitize_value(value, key=None):
    if isinstance(value, dict):
        return {item_key: _sanitize_value(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item, key) for item in value]
    if isinstance(value, str):
        key_name = str(key or "").lower()
        if key_name in _IMAGE_DATA_KEYS and len(value) > 128:
            return _image_placeholder(value)
        if _DATA_URL_PATTERN.fullmatch(value.strip()):
            return _image_placeholder(value)
    return value


def _limit(text: str) -> str:
    limit = max(0, int(getattr(config, "LLM_API_DEBUG_MAX_BODY_CHARS", 200000)))
    if not limit or len(text) <= limit:
        return text
    return f"{text[:limit]}\n[body truncated: original length {len(text)} chars]"


def _text(value: bytes) -> str:
    text = value.decode("utf-8", errors="replace")
    if getattr(config, "LLM_API_DEBUG_INCLUDE_IMAGE_DATA", False):
        return _limit(text)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        sanitized = _DATA_URL_PATTERN.sub(lambda match: _image_placeholder(match.group(0)), text)
    else:
        sanitized = json.dumps(
            _sanitize_value(parsed), ensure_ascii=False, separators=(",", ":"),
        )
    return _limit(sanitized)


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
