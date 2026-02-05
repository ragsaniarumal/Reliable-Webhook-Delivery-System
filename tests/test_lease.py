from hookrelay.db import Database
from hookrelay.service import HookRelayService
from hookrelay.worker import DeliveryWorker

class Clock:
    def __init__(self): self.t = 500.0
    def __call__(self): return self.t
    def advance(self, n): self.t += n

class NeverUsed:
    def send(self, **kwargs):
        raise AssertionError("not used")

def test_expired_processing_lease_is_reclaimable(tmp_path):
    clock = Clock()
    db = Database(tmp_path / "lease.db")
    service = HookRelayService(db)
    endpoint = service.create_endpoint("x", "http://example.test", "12345678")
    service.publish_event("x", {}, endpoint_ids=[endpoint], event_id="evt")

    with db.connect() as conn:
        conn.execute(
            """
            UPDATE deliveries
            SET status='processing',
                attempt_count=1,
                next_attempt_at=?,
                lease_until=?
            """,
            (clock(), clock() - 1),
        )

    worker = DeliveryWorker(db, NeverUsed(), lease_seconds=10, clock=clock)
    claimed = worker.claim_next()
    assert claimed is not None
    assert claimed.attempt_count == 2
    assert claimed.status == "processing"
