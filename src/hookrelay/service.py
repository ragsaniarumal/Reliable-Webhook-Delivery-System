from __future__ import annotations

import json
import time
import uuid

from .db import Database


class HookRelayService:
    def __init__(self, db: Database):
        self.db = db

    def create_endpoint(self, name: str, url: str, secret: str):
        now = time.time()
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO endpoints(name, url, secret, active, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (name, url, secret, now),
            )
            endpoint_id = int(cur.lastrowid)
        return endpoint_id

    def list_endpoints(self):
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, url, active, created_at
                FROM endpoints
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def publish_event(
        self,
        event_type: str,
        payload: dict,
        endpoint_ids: list[int] | None = None,
        idempotency_key: str | None = None,
        event_id: str | None = None,
    ):
        now = time.time()
        event_id = event_id or str(uuid.uuid4())

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            if idempotency_key:
                existing = conn.execute(
                    """
                    SELECT id FROM events
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    conn.execute("COMMIT")
                    return {
                        "event_id": str(existing["id"]),
                        "duplicate": True,
                        "delivery_count": self._delivery_count(str(existing["id"])),
                    }

            conn.execute(
                """
                INSERT INTO events(
                    id, event_type, payload_json,
                    idempotency_key, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    idempotency_key,
                    now,
                ),
            )

            if endpoint_ids is None:
                endpoints = conn.execute(
                    """
                    SELECT id FROM endpoints
                    WHERE active = 1
                    """
                ).fetchall()
                endpoint_ids = [int(row["id"]) for row in endpoints]
            else:
                endpoint_ids = [int(x) for x in endpoint_ids]

            for endpoint_id in endpoint_ids:
                conn.execute(
                    """
                    INSERT INTO deliveries(
                        event_id, endpoint_id, status,
                        attempt_count, next_attempt_at,
                        created_at, updated_at
                    )
                    VALUES (?, ?, 'pending', 0, ?, ?, ?)
                    """,
                    (event_id, endpoint_id, now, now, now),
                )

            conn.execute("COMMIT")

        return {
            "event_id": event_id,
            "duplicate": False,
            "delivery_count": len(endpoint_ids),
        }

    def _delivery_count(self, event_id: str):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM deliveries WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return int(row["n"])

    def get_delivery(self, delivery_id: int):
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT d.*, e.event_type, e.payload_json,
                       p.name AS endpoint_name, p.url AS endpoint_url
                FROM deliveries d
                JOIN events e ON e.id = d.event_id
                JOIN endpoints p ON p.id = d.endpoint_id
                WHERE d.id = ?
                """,
                (int(delivery_id),),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        return item

    def list_deliveries(self, status: str | None = None):
        sql = """
            SELECT d.id, d.event_id, d.endpoint_id, d.status,
                   d.attempt_count, d.next_attempt_at,
                   d.last_status_code, d.last_error,
                   d.delivered_at, d.created_at, d.updated_at,
                   e.event_type, p.name AS endpoint_name,
                   p.url AS endpoint_url
            FROM deliveries d
            JOIN events e ON e.id = d.event_id
            JOIN endpoints p ON p.id = d.endpoint_id
        """
        params = []
        if status:
            sql += " WHERE d.status = ?"
            params.append(status)
        sql += " ORDER BY d.id DESC"

        with self.db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


    def list_attempts(self, delivery_id: int):
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, delivery_id, attempt_number,
                       started_at, finished_at,
                       status_code, error, response_excerpt
                FROM attempts
                WHERE delivery_id = ?
                ORDER BY id ASC
                """,
                (int(delivery_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def replay_delivery(self, delivery_id: int):
        now = time.time()
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                UPDATE deliveries
                SET status = 'pending',
                    attempt_count = 0,
                    next_attempt_at = ?,
                    lease_until = NULL,
                    last_status_code = NULL,
                    last_error = NULL,
                    delivered_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, int(delivery_id)),
            )
            if cur.rowcount != 1:
                return False
        return True
