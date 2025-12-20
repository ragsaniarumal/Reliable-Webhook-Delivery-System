from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from .db import Database
from .service import HookRelayService


class EndpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    secret: str = Field(min_length=8)


class EventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    payload: dict
    endpoint_ids: list[int] | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)


def create_app(database_path: str | None = None):
    path = database_path or os.environ.get(
        "HOOKRELAY_DB",
        "data/hookrelay.db",
    )
    service = HookRelayService(Database(path))
    app = FastAPI(
        title="HookRelay",
        version="1.0.0",
        description="Reliable webhook event ingestion and delivery tracking.",
    )

    @app.post("/endpoints")
    def create_endpoint(body: EndpointCreate):
        endpoint_id = service.create_endpoint(
            body.name,
            str(body.url),
            body.secret,
        )
        return {"endpoint_id": endpoint_id}

    @app.get("/endpoints")
    def list_endpoints():
        return service.list_endpoints()

    @app.post("/events")
    def publish_event(body: EventCreate):
        return service.publish_event(
            event_type=body.event_type,
            payload=body.payload,
            endpoint_ids=body.endpoint_ids,
            idempotency_key=body.idempotency_key,
        )

    @app.get("/deliveries")
    def list_deliveries(status: str | None = None):
        return service.list_deliveries(status=status)

    @app.get("/deliveries/{delivery_id}")
    def get_delivery(delivery_id: int):
        item = service.get_delivery(delivery_id)
        if item is None:
            raise HTTPException(status_code=404, detail="delivery not found")
        return item

    @app.get("/deliveries/{delivery_id}/attempts")
    def list_attempts(delivery_id: int):
        if service.get_delivery(delivery_id) is None:
            raise HTTPException(status_code=404, detail="delivery not found")
        return service.list_attempts(delivery_id)

    @app.post("/deliveries/{delivery_id}/replay")
    def replay_delivery(delivery_id: int):
        if not service.replay_delivery(delivery_id):
            raise HTTPException(status_code=404, detail="delivery not found")
        return {"delivery_id": delivery_id, "status": "pending"}

    return app


app = create_app()
