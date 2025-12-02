from __future__ import annotations

import json
import time

import httpx

from .models import SendResult
from .signatures import sign_payload


class HTTPTransport:
    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout_seconds = float(timeout_seconds)

    def send(
        self,
        *,
        url: str,
        secret: str,
        event_id: str,
        event_type: str,
        payload: dict,
        attempt_number: int,
    ):
        body = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        timestamp = int(time.time())
        signature = sign_payload(secret, timestamp, body)

        headers = {
            "Content-Type": "application/json",
            "X-HookRelay-Event-Id": event_id,
            "X-HookRelay-Event-Type": event_type,
            "X-HookRelay-Attempt": str(attempt_number),
            "X-HookRelay-Timestamp": str(timestamp),
            "X-HookRelay-Signature": signature,
        }

        try:
            response = httpx.post(
                url,
                content=body,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            excerpt = response.text[:500]
            return SendResult(
                ok=200 <= response.status_code < 300,
                status_code=int(response.status_code),
                response_excerpt=excerpt,
                error=None if 200 <= response.status_code < 300 else f"HTTP {response.status_code}",
            )
        except Exception as exc:
            return SendResult(
                ok=False,
                status_code=None,
                response_excerpt="",
                error=f"{type(exc).__name__}: {exc}",
            )
