"""Machine-readable CLI. stdout is JSON; domain failures are JSON on stderr."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from .benchmark import benchmark
from .engine import PlanningLimitError, Snapshot, compare
from .events import apply_event
from .fixtures import fixture
from .model import Manifest, ManifestError, load, read_json


def emit(value: dict, stream=None) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False), file=stream or sys.stdout)


def atomic_write(path: Path, value: dict) -> None:
    """Atomic visibility of an artifact. No cross-process writer coordination."""
    content = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="evidencecache", description="Deterministic claim evidence gates and refresh frontiers")
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("validate", "evaluate", "plan", "witness", "compare", "apply"):
        c = sub.add_parser(command)
        c.add_argument("manifest", type=Path)
        if command in ("evaluate", "plan", "witness", "compare"):
            c.add_argument("--as-of", required=True)
        if command in ("plan", "witness"):
            c.add_argument("--answer", required=True)
            c.add_argument("--max-work", type=int, default=100_000)
        if command == "evaluate":
            c.add_argument("--answer")
            c.add_argument("--fail-on-blocked", action="store_true")
        if command == "compare":
            c.add_argument("after", type=Path)
            c.add_argument("--before-as-of")
        if command == "apply":
            c.add_argument("event", type=Path)
            c.add_argument("--output", type=Path, required=True)
    c = sub.add_parser("demo")
    c.add_argument("--output", type=Path)
    c = sub.add_parser("benchmark")
    c.add_argument("--groups", type=int, default=100)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            data = fixture()
            if args.output:
                atomic_write(args.output, data)
                emit(dict(written=str(args.output), manifest_sha256=Manifest.from_dict(data).fingerprint))
            else:
                emit(data)
            return 0
        if args.command == "benchmark":
            emit(benchmark(args.groups))
            return 0
        manifest = load(args.manifest)
        if args.command == "validate":
            emit(dict(valid=True, manifest_sha256=manifest.fingerprint, sources=len(manifest.sources),
                      claims=len(manifest.claims), answers=len(manifest.answers)))
            return 0
        if args.command == "apply":
            if args.output.resolve() == args.manifest.resolve():
                raise ManifestError("--output must differ from the input manifest; preserve the audit snapshot")
            event = read_json(args.event)
            updated = apply_event(manifest, event)
            atomic_write(args.output, updated.to_dict())
            emit(dict(written=str(args.output), before_sha256=manifest.fingerprint, after_sha256=updated.fingerprint))
            return 0
        snapshot = Snapshot(manifest, args.as_of)
        if args.command == "evaluate":
            result = snapshot.report(args.answer)
            emit(result)
            return 1 if args.fail_on_blocked and any(a["status"] == "BLOCKED" for a in result["answers"]) else 0
        if args.command == "plan":
            emit(snapshot.plan(args.answer, args.max_work))
        elif args.command == "witness":
            emit(snapshot.witnesses(args.answer, args.max_work))
        elif args.command == "compare":
            before = Snapshot(manifest, args.before_as_of or args.as_of)
            emit(compare(before, Snapshot(load(args.after), args.as_of)))
        return 0
    except PlanningLimitError as exc:
        emit(dict(error="planning_limit", detail=str(exc), exact=False), sys.stderr)
        return 3
    except (ManifestError, OSError, json.JSONDecodeError, UnicodeError) as exc:
        emit(dict(error="invalid_input", detail=str(exc)), sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
