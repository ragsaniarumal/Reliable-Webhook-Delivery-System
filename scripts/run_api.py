#!/usr/bin/env python
from __future__ import annotations

import argparse
import os

import uvicorn


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/hookrelay.db")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()

    os.environ["HOOKRELAY_DB"] = args.db
    uvicorn.run(
        "hookrelay.api:app",
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
