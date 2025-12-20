#!/usr/bin/env python
from __future__ import annotations

import argparse
import time

from hookrelay.db import Database
from hookrelay.transport import HTTPTransport
from hookrelay.worker import DeliveryWorker


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/hookrelay.db")
    p.add_argument("--poll-seconds", type=float, default=0.5)
    p.add_argument("--max-attempts", type=int, default=5)
    p.add_argument("--base-delay", type=float, default=2.0)
    p.add_argument("--max-delay", type=float, default=60.0)
    p.add_argument("--timeout", type=float, default=5.0)
    args = p.parse_args()

    worker = DeliveryWorker(
        Database(args.db),
        HTTPTransport(timeout_seconds=args.timeout),
        max_attempts=args.max_attempts,
        base_delay_seconds=args.base_delay,
        max_delay_seconds=args.max_delay,
    )

    print("HookRelay worker started. Ctrl+C to stop.")
    try:
        while True:
            result = worker.process_one()
            if result is None:
                time.sleep(args.poll_seconds)
            else:
                print(result)
    except KeyboardInterrupt:
        print("\nworker stopped")


if __name__ == "__main__":
    main()
