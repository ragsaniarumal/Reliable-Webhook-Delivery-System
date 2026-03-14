# Experiments

## Failure-recovery benchmark

Run:

```bash
python scripts/run_failure_benchmark.py \
  --events 60 \
  --output experiments/failure_recovery_summary.json
```

The benchmark creates:

```text
20 immediate-success events
20 transient-failure events
20 permanent-failure events
```

Transient events return two 503 responses and then succeed.

Permanent failures exhaust four attempts and enter the dead-letter state.

One dead-letter delivery is then replayed after the simulated receiver becomes healthy.

This experiment uses an injected deterministic transport and does not make a throughput claim.

## Real local delivery

Start the API:

```bash
python scripts/run_api.py \
  --db data/hookrelay.db \
  --port 8080
```

In another terminal:

```bash
python scripts/run_worker.py \
  --db data/hookrelay.db
```

Create a destination:

```bash
curl -X POST http://127.0.0.1:8080/endpoints \
  -H "content-type: application/json" \
  -d '{
    "name": "local receiver",
    "url": "http://127.0.0.1:9000/webhook",
    "secret": "development-secret"
  }'
```

Then publish an event with an idempotency key.
