from __future__ import annotations

import hashlib
import hmac


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    signed = str(int(timestamp)).encode("utf-8") + b"." + body
    digest = hmac.new(
        secret.encode("utf-8"),
        signed,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    secret: str,
    timestamp: int,
    body: bytes,
    signature: str,
) -> bool:
    expected = sign_payload(secret, timestamp, body)
    return hmac.compare_digest(expected, str(signature))
