"""Synthetic SDK costs, with full validation and evaluation timed separately.

Run after a normal package install. Counts describe evaluation, not all CPU work.
Process peak RSS is lifetime-wide; tracemalloc peaks cover Python allocations only.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import statistics
import time
import tracemalloc

from evidencecache import Manifest, Snapshot, SnapshotCache, apply_event

AS_OF = "2026-01-02T00:00:00Z"
DOMAIN = "synthetic-benchmark"


def fixture(count):
    data = dict(schema_version=1, sources=[], claims=[], answers=[])
    for i in range(count):
        key = f"b{i:04d}"
        fact = dict(subject=key, predicate="value", scope=DOMAIN, value=i)
        data["sources"].append(dict(id=key, uri="urn:synthetic:" + key, versions=[dict(
            id="v1", observed_at="2026-01-01T00:00:00Z", ttl_seconds=259200, facts=[fact])]))
        data["claims"].append(dict(id=key, text="Declared value", fact=fact,
            support={"evidence": dict(source=key, version="v1")}))
        data["answers"].append(dict(id=key, text="Declared answer", support={"claim": key}))
    return data


def measure(operation, prepare=lambda: None, samples=7):
    times = []
    for _ in range(samples):
        prepared = prepare()
        start = time.perf_counter()
        operation(prepared)
        times.append((time.perf_counter() - start) * 1000)
    prepared = prepare()
    tracemalloc.start()
    operation(prepared)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return dict(milliseconds=times, median_ms=statistics.median(times), python_traced_peak_bytes=peak)


def peak_rss():
    try:
        import resource
        import sys
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except ImportError:
        # Windows PROCESS_MEMORY_COUNTERS: the second SIZE_T is PeakWorkingSetSize.
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("process memory query failed")
        return counters.PeakWorkingSetSize


def run(count):
    data = fixture(count)
    manifest = Manifest.from_dict(data)
    event = dict(kind="publish", source="b0000", version=dict(id="v2", observed_at=AS_OF,
        ttl_seconds=259200, facts=data["sources"][0]["versions"][0]["facts"]))
    new = apply_event(manifest, event)
    prepare = lambda: SnapshotCache(manifest, AS_OF, trust_domain=DOMAIN)
    initial = prepare()
    updated = initial.update(new, AS_OF, trust_domain=DOMAIN)
    full = Snapshot(new, AS_OF)
    assert updated.report() == full.report()
    assert [key for key, state in updated.answers.items() if not state.valid] == ["b0000"]
    for key in updated.answers:
        assert updated.plan(key) == full.plan(key)
        assert updated.witnesses(key) == full.witnesses(key)
    operations = dict(
        initial_full=measure(lambda _: Snapshot(manifest, AS_OF)),
        initial_cache=measure(lambda _: prepare()),
        updated_full_evaluation=measure(lambda _: Snapshot(new, AS_OF)),
        updated_cache_evaluation=measure(lambda cache: cache.update(new, AS_OF, trust_domain=DOMAIN), prepare),
        full_event_ingress_and_evaluation=measure(lambda _: Snapshot(apply_event(manifest, event), AS_OF)),
        cache_event_ingress_and_evaluation=measure(lambda cache: cache.apply_event(event, trust_domain=DOMAIN), prepare),
    )
    return dict(branches=count, initial_full_work=dict(Snapshot(manifest, AS_OF).work),
                updated_full_work=dict(full.work), updated_cache_work=dict(updated.work), timings=operations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branches", nargs="+", type=int, default=[1, 3, 300])
    args = parser.parse_args()
    if any(count < 1 or count > 3000 for count in args.branches):
        parser.error("branches must be between 1 and 3000")
    print(json.dumps(dict(scope="Synthetic one-source publish; prevalidated update vs fully validated event ingress",
        includes="Map copies, definition comparisons and index maintenance in both cache update timings",
        excludes="Planning/exports, input acquisition and cache preparation from update timing",
        cases=[run(count) for count in args.branches], process_lifetime_peak_rss_bytes=peak_rss()), indent=2))


if __name__ == "__main__":
    main()
