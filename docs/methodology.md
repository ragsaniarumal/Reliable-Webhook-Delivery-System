# Methodology

## Research question

How should a webhook delivery service behave when receivers are slow, temporarily unavailable, duplicated, or recovered later?

HookRelay is deliberately centered on **delivery semantics**, not on building a large microservice stack.

## Delivery lifecycle

Every published event creates one delivery row per target endpoint:

```text
pending
  ↓ claim
processing
  ↓
 ┌───────────────┐
 │               │
2xx             failure
 │               │
delivered      retry
                 ↓
             processing
                 ↓
        max attempts reached
                 ↓
                dead
```

A dead-letter delivery can be manually replayed:

```text
dead
 ↓ replay
pending
```

## At-least-once semantics

HookRelay intentionally implements **at-least-once delivery**.

A worker can crash in this window:

```text
receiver accepted request
        ↓
worker process crashes
        ↓
success not recorded locally
```

After the processing lease expires, another worker reclaims the delivery and sends it again.

Therefore duplicates are possible.

The receiver should treat the stable event ID:

```text
X-HookRelay-Event-Id
```

as an idempotency key.

This tradeoff is explicit rather than pretending exactly-once HTTP delivery exists.

## Durable ingestion

Event creation and delivery-row creation happen in one SQLite transaction:

```text
BEGIN IMMEDIATE
insert event
insert delivery rows
COMMIT
```

A successfully acknowledged publish request therefore cannot leave an event without its intended delivery records.

## Producer idempotency

A producer may retry:

```text
POST /events
```

after a timeout without knowing whether the first request succeeded.

If it sends the same `idempotency_key`, HookRelay returns the original event and does not create duplicate delivery rows.

## Worker claim lease

A worker atomically claims one due delivery by changing:

```text
pending/retry
→ processing
```

and assigning:

```text
lease_until = now + lease_seconds
```

A stale `processing` row becomes reclaimable after the lease expires.

This distinguishes:

```text
slow/in-flight worker
from
abandoned work after worker crash
```

## Retry policy

Failed requests use deterministic exponential backoff:

```text
delay_n = min(
    base_delay * 2^(n-1),
    max_delay
)
```

Example with base 2 seconds and cap 60 seconds:

```text
attempt 1 -> 2 s
attempt 2 -> 4 s
attempt 3 -> 8 s
attempt 4 -> 16 s
attempt 5 -> 32 s
```

A production service would normally add jitter to prevent many deliveries retrying at exactly the same moment. The base project keeps the schedule deterministic for reproducible tests.

## HMAC signatures

Every HTTP delivery includes:

```text
X-HookRelay-Event-Id
X-HookRelay-Event-Type
X-HookRelay-Attempt
X-HookRelay-Timestamp
X-HookRelay-Signature
```

The signature is:

```text
HMAC-SHA256(
  secret,
  timestamp + "." + raw_body
)
```

The comparison function uses constant-time `hmac.compare_digest`.

## Dead-letter queue

After `max_attempts` unsuccessful sends:

```text
status = dead
```

The delivery stays queryable with its:

- last status code
- last error
- attempt count
- full attempt history

The operator can replay it after fixing the destination.

## Controlled failure benchmark

The included benchmark creates 60 events divided equally into:

```text
immediate success
two failures then success
permanent failure
```

A deterministic injected transport returns 503 or 200 according to the schedule.

The benchmark verifies:

- producer idempotency
- retry recovery
- maximum-attempt dead-lettering
- manual replay

It is a correctness/recovery benchmark, not a throughput claim.

## Why SQLite?

SQLite makes the repository runnable on one laptop while still supporting:

- transactions
- uniqueness constraints
- WAL mode
- durable rows
- atomic claim operations

For a multi-host deployment, the same state machine would normally move to a server database such as PostgreSQL and the claim query would use database-native concurrent worker patterns.
