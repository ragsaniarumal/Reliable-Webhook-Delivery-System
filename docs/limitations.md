# Limitations

## At-least-once means duplicates are possible

HTTP delivery cannot provide true end-to-end exactly-once semantics when the sender can crash after the receiver commits its side effect.

Destinations need idempotent handling.

## SQLite is a single-node choice

The repository uses SQLite to keep the project runnable and inspectable.

It is not intended as a horizontally scaled production queue.

## No retry jitter

Backoff is deterministic so automated tests remain reproducible.

Production retry systems should usually add jitter to avoid synchronized retry spikes.

## Endpoint secrets are stored in plaintext

This is acceptable for a local educational project but not for production. A deployed service should use a secret manager or encrypted-at-rest credentials.

## No authentication/authorization layer

The API exposes endpoint creation, publishing, inspection and replay without user accounts.

Authentication is outside the project's reliability focus.

## Replay resets attempt numbering

The replay operation is modeled as a new delivery cycle on the same logical delivery row. Production systems may instead preserve a monotonic lifetime attempt counter in addition to per-cycle counters.

## Throughput is not benchmarked

The committed experiment injects deterministic failures to verify correctness. It does not claim requests-per-second performance or multi-node scalability.
