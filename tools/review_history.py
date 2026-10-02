"""Reproduce review findings against exact local Git revisions without checkout.

Run: python tools/review_history.py --revision 5f80a13 --probe ingress
Archives trusted repository files into a temporary directory; no source mutation.
The printed observations are evidence, not a passing test or a current score.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile


def probe(name: str) -> dict:
    from evidencecache import Manifest, Snapshot, apply_event
    from evidencecache.fixtures import AS_OF, evidence, fixture
    from evidencecache.model import timestamp

    if name == "ingress":
        observations = {}
        for offset in ("+00:60", "-00:00"):
            try:
                observations[offset] = str(timestamp("2026-01-02T00:00:00" + offset))
            except Exception as exc:
                observations[offset] = type(exc).__name__
        try:
            apply_event(Manifest.from_dict(fixture()), dict(kind="revoke", source=[], version="v1", at=AS_OF))
            observations["malformed_source"] = "accepted"
        except Exception as exc:
            observations["malformed_source"] = type(exc).__name__
        return observations
    if name == "isolation":
        snap = Snapshot(Manifest.from_dict(fixture()), AS_OF)
        report = snap.report()
        report["evidence"][0]["status"] = "FORGED"
        plan = snap.plan("g0000-conflict")
        task_id = plan["plans"][0]["task_ids"][0]
        plan["plans"][0]["tasks"][0]["reason"] = "FORGED"
        return dict(later_evidence_status=snap.report()["evidence"][0]["status"],
                    later_task_reason=snap.tasks[task_id]["reason"])
    if name == "fact_frontier":
        # Minimal reproduction independently discovered during external review:
        # ((resolve R OR refresh X) AND resolve R) has only {R} as a
        # subset-minimal set. Query a direct claim leaf to expose the invariant.
        value = lambda price: dict(subject="plan", predicate="price", scope="eu", value=price)
        data = dict(schema_version=1, sources=[
            dict(id=key, uri="urn:review:" + key, versions=[dict(id="v1",
                 observed_at="2026-01-01T00:00:00Z", ttl_seconds=ttl, facts=[value(price)])])
            for key, ttl, price in (("fresh", 172800, 10), ("opponent", 172800, 20), ("stale", 86400, 10))],
            claims=[dict(id="inner", text="Declared price", fact=value(10), support=evidence("fresh")),
                    dict(id="outer", text="Declared price", fact=value(10),
                         support={"any": [{"claim": "inner"}, evidence("stale")]})],
            answers=[dict(id="a", text="Declared price", support={"claim": "outer"})])
        result = Snapshot(Manifest.from_dict(data), AS_OF).plan("a")
        sets = [frozenset(p["task_ids"]) for p in result["plans"]]
        return dict(exact=result["exact"], plans=[sorted(p) for p in sets],
                    strict_supersets_returned=[sorted(p) for p in sets if any(q < p for q in sets)])
    # Query a one-leaf answer beside an unrelated 2^12 frontier. Expired
    # alternatives explode repair sets; fresh alternatives explode witnesses.
    results = {}
    for operation in ("plan", "witnesses"):
        fresh = operation == "witnesses"
        data = dict(schema_version=1, sources=[], claims=[], answers=[])
        for i in range(25):
            data["sources"].append(dict(id=f"s{i}", uri=f"urn:review:{i}", versions=[
                dict(id="v1", observed_at="2026-01-01T00:00:00Z",
                     ttl_seconds=172800 if fresh else 86400, facts=[])]))
        data["claims"] = [
            dict(id="simple", text="Independent answer", support=evidence("s24")),
            dict(id="unrelated", text="Unrelated conjunction of alternatives", support={"all": [
                {"any": [evidence(f"s{i}"), evidence(f"s{i+1}")]} for i in range(0, 24, 2)]})]
        data["answers"] = [dict(id="simple", text="One citation", support={"claim": "simple"})]
        snap = Snapshot(Manifest.from_dict(data), AS_OF)
        try:
            result = getattr(snap, operation)("simple", max_work=100)
            results[operation] = dict(exact=result["exact"], candidates_examined=result["candidates_examined"])
        except Exception as exc:
            results[operation] = type(exc).__name__
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", required=True, help="Exact local Git commit/ref; archived read-only")
    parser.add_argument("--probe", choices=("ingress", "isolation", "planning", "fact_frontier"), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sha = subprocess.check_output(["git", "rev-parse", args.revision], cwd=root, text=True).strip()
    archive = subprocess.check_output(["git", "archive", "--format=zip", sha], cwd=root)
    with tempfile.TemporaryDirectory(prefix="evidencecache-review-") as directory:
        with ZipFile(BytesIO(archive)) as files:
            files.extractall(directory)
        sys.path.insert(0, str(Path(directory) / "src"))
        print(json.dumps(dict(revision=sha, probe=args.probe, observations=probe(args.probe)), indent=2))


if __name__ == "__main__":
    main()
