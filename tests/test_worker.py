from hookrelay.db import Database
from hookrelay.models import SendResult
from hookrelay.service import HookRelayService
from hookrelay.worker import DeliveryWorker

class Clock:
    def __init__(self):
        self.t = 1000.0
    def __call__(self):
        return self.t
    def advance(self, n):
        self.t += n

class SequenceTransport:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
    def send(self, **kwargs):
        ok = self.outcomes[self.calls]
        self.calls += 1
        if ok:
            return SendResult(True, 200, "ok", None)
        return SendResult(False, 503, "down", "HTTP 503")

def setup(tmp_path, clock):
    db = Database(tmp_path / "worker.db")
    service = HookRelayService(db)
    endpoint = service.create_endpoint("x", "http://example.test", "12345678")
    service.publish_event(
        "test",
        {"x": 1},
        endpoint_ids=[endpoint],
        event_id="evt",
    )
    with db.connect() as conn:
        conn.execute("UPDATE deliveries SET next_attempt_at = ?", (clock(),))
    return db, service

def test_retry_then_success(tmp_path):
    clock = Clock()
    db, service = setup(tmp_path, clock)
    worker = DeliveryWorker(
        db,
        SequenceTransport([False, True]),
        max_attempts=3,
        base_delay_seconds=2,
        clock=clock,
    )

    first = worker.process_one()
    assert first["ok"] is False
    d = service.list_deliveries()[0]
    assert d["status"] == "retry"

    clock.advance(2)
    second = worker.process_one()
    assert second["ok"] is True
    d = service.list_deliveries()[0]
    assert d["status"] == "delivered"
    assert d["attempt_count"] == 2
    attempts = service.list_attempts(d["id"])
    assert [x["status_code"] for x in attempts] == [503, 200]

def test_permanent_failure_goes_dead(tmp_path):
    clock = Clock()
    db, service = setup(tmp_path, clock)
    worker = DeliveryWorker(
        db,
        SequenceTransport([False, False]),
        max_attempts=2,
        base_delay_seconds=1,
        clock=clock,
    )

    worker.process_one()
    clock.advance(1)
    worker.process_one()
    d = service.list_deliveries()[0]
    assert d["status"] == "dead"
    assert d["attempt_count"] == 2
