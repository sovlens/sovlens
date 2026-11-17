"""Shared plumbing: fast-failing AWS clients, parallel regions and progress output."""
from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from botocore.config import Config

# Fail fast: a region without a service endpoint should not stall the scan.
CONFIG = Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 3, "mode": "standard"})
MAX_WORKERS = 8

_lock = threading.Lock()
_quiet = False
_start = time.monotonic()


def set_quiet(value: bool) -> None:
    global _quiet
    _quiet = value


def client(session, name: str, region: str | None = None):
    # boto3 sessions are not thread-safe when creating clients; clients themselves are.
    with _lock:
        return session.client(name, region_name=region, config=CONFIG)


def say(message: str) -> None:
    if _quiet:
        return
    elapsed = int(time.monotonic() - _start)
    with _lock:
        print(f"[{elapsed // 60:02d}:{elapsed % 60:02d}] {message}", file=sys.stderr, flush=True)


def for_regions(regions: list[str], fn, what: str) -> list:
    """Run fn(region) for every region in parallel and report progress. Returns results in region order."""
    results: dict[str, object] = {}
    total = len(regions)
    if not total:
        return []
    say(f"{what}: 0/{total} regions")
    done = 0
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, total)) as pool:
        futures = {pool.submit(fn, r): r for r in regions}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
            done += 1
            if done == total or done % 4 == 0:
                say(f"{what}: {done}/{total} regions")
    return [results[r] for r in regions]
