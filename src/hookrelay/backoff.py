from __future__ import annotations


def exponential_backoff(
    attempt_number: int,
    base_delay_seconds: float = 2.0,
    max_delay_seconds: float = 60.0,
):
    """Deterministic exponential backoff; jitter is left to production deployments."""
    attempt_number = max(int(attempt_number), 1)
    delay = float(base_delay_seconds) * (2 ** (attempt_number - 1))
    return min(delay, float(max_delay_seconds))
