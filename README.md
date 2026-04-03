# HookRelay

**Reliable webhook delivery with retries, idempotency and replay**

HookRelay asks:

> **What should happen when a webhook receiver is temporarily down, a producer retries the same event, or a delivery worker crashes halfway through processing?**

The project builds a small webhook delivery service around those failure cases instead of treating HTTP `POST` as inherently reliable.

## Core architecture

```text
Producer
   |
   | POST /events
   v
HookRelay API
   |
   | durable transaction
   v
SQLite
events + deliveries + attempts
   |
   | claim due work
   v
Delivery worker
   |
   | HMAC-signed POST
   v
Receiver
```

A delivery moves through:

```text
pending
   ↓
processing
   ↓
 ┌───────────────┐
2xx             failure
 ↓                 ↓
delivered         retry
                    ↓
               processing
                    ↓
              max attempts
                    ↓
                   dead
                    ↓
                  replay
```

## What this project demonstrates

### 1. Producer idempotency

A client can retry event creation using the same key:

```text
POST event
   ↓ timeout

POST same event again
with same idempotency_key
```

HookRelay returns the original event instead of creating another logical event or another set of deliveries.

### 2. At-least-once delivery

The service does **not** claim exactly-once webhook delivery.

Consider:

```text
worker sends webhook
        ↓
receiver commits side effect
        ↓
receiver returns 200
        ↓
worker crashes before recording success
```

After the worker lease expires, HookRelay sends the event again.

That is the correct recovery behavior when the sender cannot know whether the receiver committed the first request.

The receiver should de-duplicate using:

```text
X-HookRelay-Event-Id
```

### 3. Processing leases

Workers atomically claim due deliveries:

```text
pending/retry
     ↓
processing
lease_until = ...
```

If a worker disappears, the delivery becomes claimable again after its lease expires.

### 4. Exponential backoff

Failures retry using:

```text
2s → 4s → 8s → 16s → ...
```

up to the configured cap.

The base implementation keeps backoff deterministic for reproducible tests.

### 5. Dead-lettering

After the configured maximum number of attempts:

```text
status = dead
```

The event is not deleted.

Operators can inspect the failure and manually replay it after the receiver is fixed.

### 6. Signed payloads

Every outgoing request carries:

```text
X-HookRelay-Event-Id
X-HookRelay-Event-Type
X-HookRelay-Attempt
X-HookRelay-Timestamp
X-HookRelay-Signature
```

The body is signed with HMAC-SHA256.

## API

Start the API:

```bash
python scripts/run_api.py \
  --db data/hookrelay.db \
  --port 8080
```

Start a delivery worker in another terminal:

```bash
python scripts/run_worker.py \
  --db data/hookrelay.db
```

### Register a destination

```bash
curl -X POST http://127.0.0.1:8080/endpoints \
  -H "content-type: application/json" \
  -d '{
    "name": "orders-service",
    "url": "http://127.0.0.1:9000/webhook",
    "secret": "development-secret"
  }'
```

### Publish

```bash
curl -X POST http://127.0.0.1:8080/events \
  -H "content-type: application/json" \
  -d '{
    "event_type": "order.completed",
    "payload": {
      "order_id": "ORD-17",
      "amount": 1499
    },
    "idempotency_key": "checkout-ORD-17-completed"
  }'
```

### Inspect

```bash
curl http://127.0.0.1:8080/deliveries
```

Inspect the complete attempt history for one delivery:

```bash
curl http://127.0.0.1:8080/deliveries/12/attempts
```

### Replay a dead delivery

```bash
curl -X POST \
  http://127.0.0.1:8080/deliveries/12/replay
```

## Controlled failure benchmark

The repository contains a deterministic recovery experiment:

```bash
python scripts/run_failure_benchmark.py \
  --events 60 \
  --output experiments/failure_recovery_summary.json
```

The 60 logical events are split evenly:

```text
20 immediate success
20 fail twice, then recover
20 fail permanently
```

The benchmark checks:

- duplicate event creation is suppressed by idempotency;
- transient failures eventually reach `delivered`;
- permanent failures reach `dead`;
- one dead delivery can be manually replayed after recovery.

A complete 60-event run produced:

```text
Logical events                         60
Delivery rows after duplicate publish 60
Idempotent duplicate detected          yes

Immediate-success events               20
Transient failures recovered           20
Permanent failures dead-lettered       20
Dead-letter replay recovered            yes
```

So the duplicate publish did **not** create a 61st delivery, every transient outage recovered through retry, every permanent outage exhausted the configured attempt budget, and replay succeeded once the simulated receiver became healthy.

This benchmark validates state-machine behavior. It is **not** presented as a production throughput benchmark.

## Why not use Celery/Kafka immediately?

Because the project is about understanding the reliability mechanics.

The code explicitly exposes:

```text
event persistence
delivery rows
claim lease
attempt history
retry schedule
dead-letter state
manual replay
```

rather than hiding those ideas behind a queue framework.

That makes it much easier to explain what happens in the important crash window.

## Persistence model

```text
endpoints
  |
  └── id, URL, secret

events
  |
  └── event_type, payload, idempotency_key

deliveries
  |
  └── event × endpoint state machine

attempts
  |
  └── one row per HTTP attempt
```

SQLite runs in WAL mode and event creation uses a transaction.

## Repository layout

```text
.
├── configs/
│   └── default.json
├── docs/
│   ├── methodology.md
│   ├── failure_semantics.md
│   └── limitations.md
├── experiments/
│   ├── README.md
│   └── failure_recovery_summary.json
├── scripts/
│   ├── run_api.py
│   ├── run_worker.py
│   ├── run_failure_benchmark.py
│   └── verify_signature.py
├── src/hookrelay/
│   ├── api.py
│   ├── backoff.py
│   ├── db.py
│   ├── models.py
│   ├── service.py
│   ├── signatures.py
│   ├── transport.py
│   └── worker.py
└── tests/
```

## Installation

```bash
python -m pip install -e ".[dev]"
pytest -q
```

## Useful interview discussion

A central question is:

> **What if the receiver returns 200, but the worker crashes before marking the delivery successful?**

HookRelay's answer is:

```text
we cannot prove the side effect did not happen
        ↓
lease expires
        ↓
send again
        ↓
at-least-once delivery
        ↓
receiver must de-duplicate by stable event ID
```

That distinction is more important than simply saying the project "supports retries."

## Limitations

- SQLite keeps the project single-node.
- retry jitter is omitted from the deterministic base implementation;
- secrets are plaintext in the local database;
- authentication is not part of the control-plane API;
- true end-to-end exactly-once delivery is not claimed;
- the committed benchmark measures correctness under injected failures, not throughput.

See [`docs/limitations.md`](docs/limitations.md).
