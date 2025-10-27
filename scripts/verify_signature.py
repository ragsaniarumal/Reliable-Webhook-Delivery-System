#!/usr/bin/env python
from __future__ import annotations

import argparse

from hookrelay.signatures import verify_signature


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--secret", required=True)
    p.add_argument("--timestamp", required=True, type=int)
    p.add_argument("--signature", required=True)
    p.add_argument("--body", required=True)
    args = p.parse_args()

    ok = verify_signature(
        args.secret,
        args.timestamp,
        args.body.encode("utf-8"),
        args.signature,
    )
    print("valid" if ok else "invalid")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
