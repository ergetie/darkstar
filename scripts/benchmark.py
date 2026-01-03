#!/usr/bin/env python3
"""
Darkstar API Performance Benchmark

Measures baseline API performance for key endpoints.
Usage: python scripts/benchmark.py [--url URL] [--requests N]
"""

import argparse
import asyncio
import statistics
import time
from typing import NamedTuple

import httpx


class BenchmarkResult(NamedTuple):
    """Results for a single endpoint benchmark."""
    endpoint: str
    total_requests: int
    successful: int
    failed: int
    duration_s: float
    rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


async def benchmark_endpoint(
    client: httpx.AsyncClient,
    endpoint: str,
    num_requests: int,
    concurrency: int = 10,
) -> BenchmarkResult:
    """Benchmark a single endpoint with concurrent requests."""
    latencies: list[float] = []
    errors = 0

    async def make_request() -> float | None:
        nonlocal errors
        start = time.perf_counter()
        try:
            resp = await client.get(endpoint, timeout=10.0)
            if resp.status_code != 200:
                errors += 1
                return None
            return (time.perf_counter() - start) * 1000  # ms
        except Exception:
            errors += 1
            return None

    # Run requests in batches
    start_time = time.perf_counter()
    for i in range(0, num_requests, concurrency):
        batch_size = min(concurrency, num_requests - i)
        results = await asyncio.gather(*[make_request() for _ in range(batch_size)])
        latencies.extend([r for r in results if r is not None])
    
    total_duration = time.perf_counter() - start_time

    if not latencies:
        return BenchmarkResult(
            endpoint=endpoint,
            total_requests=num_requests,
            successful=0,
            failed=errors,
            duration_s=total_duration,
            rps=0,
            p50_ms=0,
            p95_ms=0,
            p99_ms=0,
        )

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    return BenchmarkResult(
        endpoint=endpoint,
        total_requests=num_requests,
        successful=len(latencies),
        failed=errors,
        duration_s=total_duration,
        rps=len(latencies) / total_duration,
        p50_ms=p50,
        p95_ms=p95,
        p99_ms=p99,
    )


def print_result(result: BenchmarkResult) -> None:
    """Print formatted benchmark result."""
    print(f"\n{'=' * 60}")
    print(f"Endpoint: {result.endpoint}")
    print(f"{'=' * 60}")
    print(f"  Total requests:  {result.total_requests}")
    print(f"  Successful:      {result.successful}")
    print(f"  Failed:          {result.failed}")
    print(f"  Duration:        {result.duration_s:.2f}s")
    print(f"  RPS:             {result.rps:.1f}")
    print(f"  Latency p50:     {result.p50_ms:.2f}ms")
    print(f"  Latency p95:     {result.p95_ms:.2f}ms")
    print(f"  Latency p99:     {result.p99_ms:.2f}ms")


async def main():
    parser = argparse.ArgumentParser(description="Darkstar API Benchmark")
    parser.add_argument("--url", default="http://localhost:5000", help="Base URL")
    parser.add_argument("--requests", type=int, default=100, help="Requests per endpoint")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent requests")
    args = parser.parse_args()

    endpoints = [
        "/api/health",           # Lightweight (health check)
        "/api/version",          # Lightweight (git describe)
        "/api/config",           # Medium (YAML + secrets merge)
        "/api/aurora/dashboard", # Heavy (DB query + ML status)
    ]

    print("=" * 60)
    print("Darkstar API Performance Benchmark")
    print("=" * 60)
    print(f"Base URL:    {args.url}")
    print(f"Requests:    {args.requests} per endpoint")
    print(f"Concurrency: {args.concurrency}")
    print("=" * 60)

    async with httpx.AsyncClient(base_url=args.url) as client:
        # Warmup
        print("\nWarming up...")
        for endpoint in endpoints:
            try:
                await client.get(endpoint, timeout=5.0)
            except Exception:
                print(f"  Warning: {endpoint} may not be available")

        # Benchmark
        results = []
        for endpoint in endpoints:
            print(f"\nBenchmarking {endpoint}...")
            result = await benchmark_endpoint(
                client, endpoint, args.requests, args.concurrency
            )
            results.append(result)
            print_result(result)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"{'Endpoint':<25} {'RPS':>8} {'p50':>10} {'p95':>10} {'p99':>10}")
    print("-" * 60)
    for r in results:
        print(f"{r.endpoint:<25} {r.rps:>8.1f} {r.p50_ms:>9.2f}ms {r.p95_ms:>9.2f}ms {r.p99_ms:>9.2f}ms")


if __name__ == "__main__":
    asyncio.run(main())
