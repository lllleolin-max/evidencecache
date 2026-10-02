import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from evidencecache.benchmark import benchmark
from evidencecache.cli import atomic_write, main
from evidencecache.fixtures import AS_OF, fixture


class CliTests(unittest.TestCase):
    def test_real_subprocess_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.json"
            for args in (["demo", "--output", str(path)], ["validate", str(path)],
                         ["plan", str(path), "--as-of", AS_OF, "--answer", "g0000-alternative"]):
                result = subprocess.run([sys.executable, "-m", "evidencecache", *args], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                json.loads(result.stdout)
            result = subprocess.run([sys.executable, "-m", "evidencecache", "evaluate", str(path), "--as-of", AS_OF,
                                     "--fail-on-blocked"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)["answers"]), 3)

    def test_invalid_input_structured_error(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(["validate", "this-manifest-does-not-exist.json"])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(err.getvalue())["error"], "invalid_input")
        self.assertEqual(out.getvalue(), "")

    def test_atomic_write_preserves_old_artifact_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            target.write_text("original", encoding="utf-8")
            with patch("evidencecache.cli.os.replace", side_effect=OSError("simulated I/O failure")):
                with self.assertRaises(OSError):
                    atomic_write(target, {"x": 1})
            self.assertEqual(target.read_text(), "original")
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_benchmark_distinction(self):
        data = benchmark(10)
        rows = {r["policy"]: r for r in data["results"]}
        self.assertEqual(rows["evidencecache"]["unsafe_reuses"], 0)
        self.assertEqual(rows["whole_corpus_ttl"]["unnecessary_invalidations"], 20)
        self.assertEqual(rows["flat_per_source_ttl"]["unsafe_reuses"], 10)
        self.assertEqual(rows["flat_per_source_ttl"]["unnecessary_invalidations"], 10)
        self.assertEqual(data["single_source_replacement"]["invalidated_answers"], ["g0000-steady"])


if __name__ == "__main__":
    unittest.main()
