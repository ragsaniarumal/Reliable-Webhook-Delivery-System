from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Endpoint:
    id: int
    name: str
    url: str
    secret: str
    active: bool


@dataclass
class Delivery:
    id: int
    event_id: str
    endpoint_id: int
    status: str
    attempt_count: int
    next_attempt_at: float
    lease_until: float | None


@dataclass
class SendResult:
    ok: bool
    status_code: int | None
    response_excerpt: str
    error: str | None = None
    metadata: dict[str, Any] | None = None
