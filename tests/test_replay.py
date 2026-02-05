from hookrelay.db import Database
from hookrelay.service import HookRelayService

def test_replay_resets_failed_delivery(tmp_path):
    db = Database(tmp_path / "replay.db")
    service = HookRelayService(db)
    endpoint = service.create_endpoint("x", "http://example.test", "12345678")
    service.publish_event("x", {}, endpoint_ids=[endpoint], event_id="evt")
    delivery = service.list_deliveries()[0]

    with db.connect() as conn:
        conn.execute(
            """
            UPDATE deliveries
            SET status='dead', attempt_count=5, last_error='boom'
            WHERE id=?
            """,
            (delivery["id"],),
        )

    assert service.replay_delivery(delivery["id"])
    updated = service.get_delivery(delivery["id"])
    assert updated["status"] == "pending"
    assert updated["attempt_count"] == 0
    assert updated["last_error"] is None


from hookrelay.models import SendResult
from hookrelay.worker import DeliveryWorker

class _Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t
    def advance(self, n): self.t += n

class _Sequence:
    def __init__(self, outcomes): self.outcomes = list(outcomes); self.i = 0
    def send(self, **kwargs):
        ok = self.outcomes[self.i]
        self.i += 1
        return (
            SendResult(True, 200, "ok", None)
            if ok else
            SendResult(False, 503, "down", "HTTP 503")
        )

def test_replay_preserves_previous_attempt_history(tmp_path):
    clock = _Clock()
    db = Database(tmp_path / "history.db")
    service = HookRelayService(db)
    endpoint = service.create_endpoint("x", "http://example.test", "12345678")
    service.publish_event("x", {}, endpoint_ids=[endpoint], event_id="evt")

    with db.connect() as conn:
        conn.execute("UPDATE deliveries SET next_attempt_at=?", (clock(),))

    worker = DeliveryWorker(
        db,
        _Sequence([False, True]),
        max_attempts=1,
        clock=clock,
    )
    worker.process_one()
    delivery = service.list_deliveries()[0]
    assert delivery["status"] == "dead"

    service.replay_delivery(delivery["id"])
    with db.connect() as conn:
        conn.execute(
            "UPDATE deliveries SET next_attempt_at=? WHERE id=?",
            (clock(), delivery["id"]),
        )
    worker.process_one()

    with db.connect() as conn:
        attempts = conn.execute(
            "SELECT attempt_number, status_code FROM attempts WHERE delivery_id=? ORDER BY id",
            (delivery["id"],),
        ).fetchall()

    assert len(attempts) == 2
    assert [row["status_code"] for row in attempts] == [503, 200]
