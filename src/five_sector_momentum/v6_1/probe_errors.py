from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


STATES = {
    "DATA", "APPLICATION_NO_PERMISSION", "RATE_LIMITED", "NETWORK_BLOCKED",
    "NETWORK_ERROR", "ENDPOINT_ERROR", "SILENT_EMPTY",
    "KNOWN_OUTSIDE_LISTING_RANGE", "KNOWN_NO_DATA_AFTER_POSITIVE_CONTROL", "NOT_TESTABLE",
}
RETRYABLE = {"RATE_LIMITED", "NETWORK_BLOCKED", "NETWORK_ERROR"}
BACKOFF_SECONDS = (1, 3, 9)


@dataclass(frozen=True)
class ErrorEvidence:
    classification: str
    layer: str
    exception_class: str
    winerror: int | None
    http_status: int | None
    safe_message_code: str
    message_fingerprint: str


def _walk_exception(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _fingerprint(text: str) -> str:
    redacted = re.sub(r"[A-Za-z0-9_-]{20,}", "[REDACTED]", text)
    return hashlib.sha256(redacted.encode("utf-8", errors="replace")).hexdigest()[:16]


def classify_exception(exc: BaseException, api_name: str) -> ErrorEvidence:
    chain = list(_walk_exception(exc))
    text = " | ".join(str(item) for item in chain)
    lower = text.lower()
    winerror = next((getattr(item, "winerror", None) for item in chain if getattr(item, "winerror", None) is not None), None)
    response = next((getattr(item, "response", None) for item in chain if getattr(item, "response", None) is not None), None)
    http_status = getattr(response, "status_code", None)
    classes = {item.__class__.__name__ for item in chain}
    is_transport = bool(classes & {"ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout", "SSLError", "ProxyError"})
    if requests is not None:
        is_transport = is_transport or any(isinstance(item, requests.exceptions.RequestException) for item in chain)

    if winerror == 10013 or "winerror 10013" in lower or "socket access" in lower and "forbidden" in lower:
        state, layer, code = "NETWORK_BLOCKED", "TRANSPORT", "TRANSPORT_SOCKET_FORBIDDEN"
    elif http_status == 429 or any(marker in text for marker in ("每分钟最多访问", "访问频率", "频率上限")):
        state, layer, code = "RATE_LIMITED", "HTTP_OR_APPLICATION", "ENDPOINT_RATE_LIMITED"
    elif is_transport:
        state, layer, code = "NETWORK_ERROR", "TRANSPORT", "TRANSPORT_CONNECTION_FAILURE"
    elif re.search(r"没有接口\([^)]*\)的访问权限|无权限访问接口|没有.*访问权限", text):
        state, layer, code = "APPLICATION_NO_PERMISSION", "TUSHARE_APPLICATION", f"TUSHARE_NO_PERMISSION_{api_name.upper()}"
    else:
        state, layer, code = "ENDPOINT_ERROR", "APPLICATION_OR_UNKNOWN", f"ENDPOINT_ERROR_{api_name.upper()}"
    return ErrorEvidence(state, layer, exc.__class__.__name__, winerror, http_status, code, _fingerprint(text))


def call_with_evidence(
    api_name: str,
    key: str,
    callback: Callable[[], Any],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[pd.DataFrame, str, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    # One initial call plus the three mandated retries after 1, 3 and 9 seconds.
    for number in range(1, 5):
        started = datetime.now().isoformat()
        try:
            result = callback()
            frame = result if isinstance(result, pd.DataFrame) else pd.DataFrame(result)
            state = "DATA" if not frame.empty else "SILENT_EMPTY"
            attempts.append({
                "api_name": api_name, "key": key, "attempt": number, "started_at": started,
                "finished_at": datetime.now().isoformat(), "classification": state,
                "layer": "SUCCESS_RESPONSE", "exception_class": "", "winerror": None,
                "http_status": None, "safe_message_code": state, "message_fingerprint": "",
                "row_count": len(frame), "will_retry": False,
            })
            return frame, state, attempts
        except Exception as exc:  # evidence is sanitized below
            evidence = classify_exception(exc, api_name)
            will_retry = evidence.classification in RETRYABLE and number < 4
            attempts.append({
                "api_name": api_name, "key": key, "attempt": number, "started_at": started,
                "finished_at": datetime.now().isoformat(), "classification": evidence.classification,
                "layer": evidence.layer, "exception_class": evidence.exception_class,
                "winerror": evidence.winerror, "http_status": evidence.http_status,
                "safe_message_code": evidence.safe_message_code,
                "message_fingerprint": evidence.message_fingerprint, "row_count": 0,
                "will_retry": will_retry,
            })
            if not will_retry:
                return pd.DataFrame(), evidence.classification, attempts
            sleep(BACKOFF_SECONDS[number - 1])
    raise AssertionError("unreachable")
