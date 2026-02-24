# Failure Semantics

## Case 1: Receiver returns 503

```text
send
 ↓
503
 ↓
record attempt
 ↓
retry at backoff deadline
```

No event is recreated.

## Case 2: Receiver is unreachable

Transport exceptions are recorded as failed attempts and use the same retry policy.

## Case 3: Worker crashes before sending

The row remains `processing`.

When the lease expires another worker can reclaim it.

No external duplicate has occurred because the first worker never sent.

## Case 4: Worker crashes after receiver accepted the webhook

This is the important ambiguity:

```text
receiver returned 200
        ↓
worker died before DB commit
```

HookRelay cannot know whether the external side effect happened.

The safe recovery behavior is to send again after lease expiry.

That creates **at-least-once**, not exactly-once, semantics.

The destination should de-duplicate using `X-HookRelay-Event-Id`.

## Case 5: Producer retries event creation

The producer may have timed out after HookRelay committed the event.

Using the same producer idempotency key returns the original event instead of inserting another one.

## Case 6: Permanent receiver failure

After `max_attempts`:

```text
retry -> dead
```

The delivery is preserved for inspection and explicit replay.

## Case 7: Replay after endpoint recovery

Manual replay resets:

```text
status
attempt_count
next_attempt_at
last error
```

while keeping the same event and delivery identity.

The receiver can therefore still detect that the logical event is not new.
