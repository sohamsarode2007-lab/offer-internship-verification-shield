"""Rate-limit counters shared through Redis (RATE_LIMIT_STORAGE_URI). Runs only when REDIS_TEST_URL points at a Redis
server (CI starts one); otherwise it is reported as skipped, never as passed."""
import os
import uuid

import pytest
from limits import parse
from limits.strategies import FixedWindowRateLimiter

from app.api.limiter import build_limiter

REDIS_URL = os.getenv("REDIS_TEST_URL", "")

@pytest.mark.skipif(not REDIS_URL, reason="REDIS_TEST_URL not set")
def test_two_workers_share_one_counter_through_redis(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", REDIS_URL)
    worker_a, worker_b = build_limiter(), build_limiter()          # two separate processes would each build their own
    item = parse("3/minute")
    key = f"shared-test-{uuid.uuid4()}"
    hits = [FixedWindowRateLimiter(w._storage).hit(item, key) for w in (worker_a, worker_b, worker_a, worker_b)]
    assert hits == [True, True, True, False]       # the 4th hit is refused even though it came from the other worker


def test_without_a_storage_uri_each_worker_counts_alone(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_STORAGE_URI", raising=False)
    worker_a, worker_b = build_limiter(), build_limiter()
    item = parse("1/minute")
    key = f"alone-test-{uuid.uuid4()}"
    assert FixedWindowRateLimiter(worker_a._storage).hit(item, key) is True
    assert FixedWindowRateLimiter(worker_b._storage).hit(item, key) is True      # not shared: documented limit
