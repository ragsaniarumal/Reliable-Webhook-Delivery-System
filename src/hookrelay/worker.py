from __future__ import annotations

import json
import time

from .backoff import exponential_backoff
from .db import Database
from .models import Delivery


class DeliveryWorker:
    """Claims and delivers one webhook at a time.

    The lease makes a crashed in-flight delivery eligible again after expiry.
    Because a receiver may have accepted the request before the worker crashes,
    this is intentionally at-least-once delivery.
    """

    def __init__(
        self,
        db: Database,
        transport,
        *,
        max_attempts: int = 5,
        base_delay_seconds: float = 2.0,
        max_delay_seconds: float = 60.0,
        lease_seconds: float = 30.0,
        clock=time.time,
    ):
        self.db = db
        self.transport = transport
        self.max_attempts = int(max_attempts)
        self.base_delay_seconds = float(base_delay_seconds)
        self.max_delay_seconds = float(max_delay_seconds)
        self.lease_seconds = float(lease_seconds)
        self.clock = clock

    def claim_next(self):
        now = float(self.clock())
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                """
                SELECT id, event_id, endpoint_id, status,
                       attempt_count, next_attempt_at, lease_until
                FROM deliveries
                WHERE
                    (
                        status IN ('pending', 'retry')
                        AND next_attempt_at <= ?
                    )
                    OR
                    (
                        status = 'processing'
                        AND lease_until IS NOT NULL
                        AND lease_until <= ?
                    )
                ORDER BY next_attempt_at ASC, id ASC
                LIMIT 1
                """,
                (now, now),
            ).fetchone()

            if row is None:
                conn.execute("COMMIT")
                return None

            next_attempt = int(row["attempt_count"]) + 1
            lease_until = now + self.lease_seconds

            updated = conn.execute(
                """
                UPDATE deliveries
                SET status = 'processing',
                    attempt_count = ?,
                    lease_until = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    next_attempt,
                    lease_until,
                    now,
                    int(row["id"]),
                ),
            )
            if updated.rowcount != 1:
                conn.execute("ROLLBACK")
                return None

            conn.execute("COMMIT")

        return Delivery(
            id=int(row["id"]),
            event_id=str(row["event_id"]),
            endpoint_id=int(row["endpoint_id"]),
            status="processing",
            attempt_count=next_attempt,
            next_attempt_at=float(row["next_attempt_at"]),
            lease_until=lease_until,
        )

    def _load_payload(self, delivery: Delivery):
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT e.event_type, e.payload_json,
                       p.url, p.secret, p.active
                FROM deliveries d
                JOIN events e ON e.id = d.event_id
                JOIN endpoints p ON p.id = d.endpoint_id
                WHERE d.id = ?
                """,
                (delivery.id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"delivery {delivery.id} not found")
        return {
            "event_type": str(row["event_type"]),
            "payload": json.loads(row["payload_json"]),
            "url": str(row["url"]),
            "secret": str(row["secret"]),
            "active": bool(row["active"]),
        }

    def process_one(self):
        delivery = self.claim_next()
        if delivery is None:
            return None

        details = self._load_payload(delivery)
        started = float(self.clock())

        if not details["active"]:
            result = type(
                "InactiveResult",
                (),
                {
                    "ok": False,
                    "status_code": None,
                    "response_excerpt": "",
                    "error": "endpoint inactive",
                },
            )()
        else:
            result = self.transport.send(
                url=details["url"],
                secret=details["secret"],
                event_id=delivery.event_id,
                event_type=details["event_type"],
                payload=details["payload"],
                attempt_number=delivery.attempt_count,
            )

        finished = float(self.clock())
        self.finalize(delivery, result, started, finished)

        return {
            "delivery_id": delivery.id,
            "event_id": delivery.event_id,
            "attempt_number": delivery.attempt_count,
            "ok": bool(result.ok),
            "status_code": result.status_code,
            "error": result.error,
        }

    def finalize(self, delivery, result, started_at, finished_at):
        now = float(finished_at)

        if result.ok:
            status = "delivered"
            next_attempt_at = now
            delivered_at = now
        elif delivery.attempt_count >= self.max_attempts:
            status = "dead"
            next_attempt_at = now
            delivered_at = None
        else:
            status = "retry"
            delay = exponential_backoff(
                delivery.attempt_count,
                base_delay_seconds=self.base_delay_seconds,
                max_delay_seconds=self.max_delay_seconds,
            )
            next_attempt_at = now + delay
            delivered_at = None

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            conn.execute(
                """
                INSERT INTO attempts(
                    delivery_id, attempt_number,
                    started_at, finished_at,
                    status_code, error, response_excerpt
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery.id,
                    delivery.attempt_count,
                    float(started_at),
                    float(finished_at),
                    result.status_code,
                    result.error,
                    str(result.response_excerpt)[:500],
                ),
            )

            conn.execute(
                """
                UPDATE deliveries
                SET status = ?,
                    next_attempt_at = ?,
                    lease_until = NULL,
                    last_status_code = ?,
                    last_error = ?,
                    delivered_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    next_attempt_at,
                    result.status_code,
                    result.error,
                    delivered_at,
                    now,
                    delivery.id,
                ),
            )

            conn.execute("COMMIT")

    def run_until_idle(self, max_iterations: int = 1000):
        processed = []
        for _ in range(int(max_iterations)):
            item = self.process_one()
            if item is None:
                break
            processed.append(item)
        return processed
