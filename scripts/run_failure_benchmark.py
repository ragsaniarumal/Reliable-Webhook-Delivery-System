#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from hookrelay.db import Database
from hookrelay.models import SendResult
from hookrelay.service import HookRelayService
from hookrelay.worker import DeliveryWorker


class FakeClock:
    def __init__(self, start=1_000_000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)


class PatternTransport:
    """Per-event failure schedule.

    failures_before_success[event_id] = N means attempts 1..N fail and N+1 succeeds.
    Use None to fail forever.
    """

    def __init__(self, failures_before_success):
        self.failures_before_success = dict(failures_before_success)
        self.calls = {}

    def send(self, *, event_id, attempt_number, **kwargs):
        self.calls[event_id] = self.calls.get(event_id, 0) + 1
        threshold = self.failures_before_success[event_id]

        if threshold is None or attempt_number <= threshold:
            return SendResult(
                ok=False,
                status_code=503,
                response_excerpt="temporary outage",
                error="HTTP 503",
            )

        return SendResult(
            ok=True,
            status_code=200,
            response_excerpt="ok",
            error=None,
        )


def force_due(db, clock):
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE deliveries
            SET next_attempt_at = ?
            WHERE status IN ('retry', 'pending')
            """,
            (clock(),),
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--events", type=int, default=60)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "benchmark.db")
        service = HookRelayService(db)
        endpoint_id = service.create_endpoint(
            "receiver",
            "http://receiver.invalid/webhook",
            "benchmark-secret",
        )

        schedule = {}
        event_ids = []

        # 1/3 immediate success, 1/3 succeed after two failures,
        # 1/3 fail permanently and dead-letter.
        for i in range(args.events):
            event_id = f"evt-{i:04d}"
            event_ids.append(event_id)

            if i % 3 == 0:
                schedule[event_id] = 0
            elif i % 3 == 1:
                schedule[event_id] = 2
            else:
                schedule[event_id] = None

            service.publish_event(
                "benchmark.event",
                {"index": i},
                endpoint_ids=[endpoint_id],
                idempotency_key=f"idem-{i:04d}",
                event_id=event_id,
            )

        # Verify duplicate publish does not create a second delivery.
        duplicate = service.publish_event(
            "benchmark.event",
            {"index": 0},
            endpoint_ids=[endpoint_id],
            idempotency_key="idem-0000",
            event_id="should-not-be-created",
        )

        clock = FakeClock()
        transport = PatternTransport(schedule)
        worker = DeliveryWorker(
            db,
            transport,
            max_attempts=4,
            base_delay_seconds=2,
            max_delay_seconds=8,
            lease_seconds=5,
            clock=clock,
        )

        # Initial event timestamps were real wall-clock values. Move due times to fake clock.
        with db.connect() as conn:
            conn.execute(
                "UPDATE deliveries SET next_attempt_at = ?",
                (clock(),),
            )

        for _ in range(6):
            while worker.process_one() is not None:
                pass
            force_due(db, clock)
            clock.advance(10)

        deliveries = service.list_deliveries()
        delivered = [x for x in deliveries if x["status"] == "delivered"]
        dead = [x for x in deliveries if x["status"] == "dead"]

        recovered_after_retry = [
            x for x in delivered if x["attempt_count"] > 1
        ]

        # Replay one dead delivery against a now-healthy receiver.
        replay_recovered = False
        if dead:
            target = dead[0]
            schedule[target["event_id"]] = 0
            transport.failures_before_success[target["event_id"]] = 0
            service.replay_delivery(target["id"])
            force_due(db, clock)
            result = worker.process_one()
            updated = service.get_delivery(target["id"])
            replay_recovered = bool(
                result
                and result["ok"]
                and updated["status"] == "delivered"
            )

        summary = {
            "benchmark_type": "controlled deterministic failure-recovery benchmark",
            "events": args.events,
            "delivery_rows_after_idempotent_duplicate": len(deliveries),
            "idempotent_duplicate_detected": bool(duplicate["duplicate"]),
            "delivered_before_manual_replay": len(delivered),
            "recovered_after_retry": len(recovered_after_retry),
            "dead_lettered_before_manual_replay": len(dead),
            "manual_replay_recovered_one_dead_letter": replay_recovered,
            "expected": {
                "immediate_success": len([i for i in range(args.events) if i % 3 == 0]),
                "retry_then_success": len([i for i in range(args.events) if i % 3 == 1]),
                "permanent_failure": len([i for i in range(args.events) if i % 3 == 2]),
            },
            "scope_note": (
                "This benchmark validates retry, idempotency, dead-letter and replay logic "
                "with an injected transport. It is not a production throughput benchmark."
            ),
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
