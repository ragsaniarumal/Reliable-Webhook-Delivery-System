from hookrelay.db import Database
from hookrelay.service import HookRelayService

def test_idempotency_prevents_duplicate_event_and_delivery(tmp_path):
    db = Database(tmp_path / "test.db")
    service = HookRelayService(db)
    endpoint = service.create_endpoint("x", "http://example.test/hook", "12345678")

    first = service.publish_event(
        "order.created",
        {"id": 1},
        endpoint_ids=[endpoint],
        idempotency_key="abc",
        event_id="evt-1",
    )
    second = service.publish_event(
        "order.created",
        {"id": 1},
        endpoint_ids=[endpoint],
        idempotency_key="abc",
        event_id="evt-2",
    )

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["event_id"] == "evt-1"
    assert len(service.list_deliveries()) == 1
