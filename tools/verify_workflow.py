"""Execute the documented installed CLI/SDK workflow with disposable artifacts.

Run with the interpreter of a clean environment after `python -m pip install .`.
All data are synthetic; source/event files are asserted unchanged on invalid apply.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from evidencecache import Manifest, Snapshot
from evidencecache.fixtures import AS_OF, fixture


def cli(*args: str, expected: int = 0) -> dict:
    process = subprocess.run([sys.executable, "-m", "evidencecache", *map(str, args)],
                             capture_output=True, text=True, encoding="utf-8")
    if process.returncode != expected:
        raise AssertionError(f"{args}: exit={process.returncode}, expected={expected}: {process.stderr}")
    output = process.stderr if expected in (2, 3) else process.stdout
    return json.loads(output)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="evidencecache-workflow-") as directory:
        root = Path(directory)
        manifest, event, updated = root / "demo.json", root / "event.json", root / "next.json"
        cli("demo", "--output", manifest)
        original = manifest.read_bytes()
        validation = cli("validate", manifest)
        report = cli("evaluate", manifest, "--as-of", AS_OF, "--fail-on-blocked", expected=1)
        states = {a["id"]: a["status"] for a in report["answers"]}
        assert states == {"g0000-alternative": "VALID", "g0000-conflict": "BLOCKED", "g0000-steady": "VALID"}
        witness = cli("witness", manifest, "--as-of", AS_OF, "--answer", "g0000-alternative")
        assert witness["witnesses"] == [[dict(source="g0000-mirror", version="v1")]]
        plan = cli("plan", manifest, "--as-of", AS_OF, "--answer", "g0000-conflict")
        assert plan["minimum_task_count"] == 1
        assert plan["plans"][0]["tasks"][0]["kind"] == "resolve_fact"
        limited = cli("plan", manifest, "--as-of", AS_OF, "--answer", "g0000-alternative",
                      "--max-work", "1", expected=3)
        assert limited["error"] == "planning_limit" and limited["exact"] is False
        assert "plans" not in limited
        data = fixture()
        event.write_text(json.dumps(dict(kind="publish", source="g0000-status", version=dict(
            id="v2", observed_at=AS_OF, ttl_seconds=86400, facts=data["sources"][2]["versions"][0]["facts"]))), encoding="utf-8")
        cli("apply", manifest, event, "--output", updated)
        impact = cli("compare", manifest, updated, "--as-of", AS_OF)
        assert impact["invalidated_answers"] == ["g0000-steady"]
        assert manifest.read_bytes() == original
        event.write_text('{"kind":"revoke","kind":"publish"}', encoding="utf-8")
        previous = updated.read_bytes()
        rejected = cli("apply", manifest, event, "--output", updated, expected=2)
        assert "duplicate JSON key" in rejected["detail"]
        assert updated.read_bytes() == previous and manifest.read_bytes() == original
        policy = cli("benchmark", "--groups", "100")
        rows = {r["policy"]: (r["unnecessary_invalidations"], r["unsafe_reuses"]) for r in policy["results"]}
        assert rows == dict(evidencecache=(0, 0), whole_corpus_ttl=(200, 0), flat_per_source_ttl=(100, 100),
                            without_fact_checks=(0, 100), without_alternative_support=(100, 0))
        sdk = Snapshot(Manifest.from_dict(fixture()), AS_OF)
        assert sdk.answers["g0000-alternative"].valid
        # Release 0.1.1 regression: an outer price claim shares its fact
        # resolution task with an inner one and has a stale alternative. The
        # CLI must return {R}, never its unnecessary superset {R, refresh X}.
        shared = fixture()
        old_price = json.loads(json.dumps(next(s for s in shared["sources"] if s["id"] == "g0000-price")))
        old_price["id"] = "g0000-old-price"
        old_price["versions"][0]["ttl_seconds"] = 86400
        shared["sources"].append(old_price)
        declared = next(c["fact"] for c in shared["claims"] if c["id"] == "g0000-cost")
        shared["claims"].append(dict(id="outer-cost", text="Declared price", fact=declared,
            support={"any": [{"claim": "g0000-cost"}, {"evidence": {"source": "g0000-old-price", "version": "v1"}}]}))
        shared["answers"].append(dict(id="outer-answer", text="Declared price", support={"claim": "outer-cost"}))
        shared_file = root / "shared.json"
        shared_file.write_text(json.dumps(shared), encoding="utf-8")
        shared_plan = cli("plan", shared_file, "--as-of", AS_OF, "--answer", "outer-answer")
        assert shared_plan["exact"] and len(shared_plan["plans"]) == 1
        assert len(shared_plan["plans"][0]["task_ids"]) == 1
        assert shared_plan["plans"][0]["tasks"][0]["kind"] == "resolve_fact"
        print(json.dumps(dict(python=sys.version.split()[0], validation=validation,
                              answer_states=states, witness=witness["witnesses"],
                              minimum_conflict_tasks=plan["minimum_task_count"],
                              invalidated_answers=impact["invalidated_answers"],
                              invalid_input_exit=2, planning_limit_exit=3, partial_frontier_returned=False,
                              input_preserved=True, rejected_output_preserved=True,
                              shared_fact_frontier_exact=True, shared_fact_resolution_tasks=1,
                              synthetic_benchmark=[dict(policy=k, unnecessary_invalidations=v[0], unsafe_reuses=v[1])
                                                   for k, v in rows.items()], sdk_valid=True), indent=2))


if __name__ == "__main__":
    main()
