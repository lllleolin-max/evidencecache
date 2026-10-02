from dataclasses import FrozenInstanceError
import json
import unittest

from evidencecache import Manifest, Snapshot, compare
from evidencecache.fixtures import AS_OF, fixture
from evidencecache.model import Evidence


class SnapshotIsolationTests(unittest.TestCase):
    def setUp(self):
        self.manifest = Manifest.from_dict(fixture())
        self.snapshot = Snapshot(self.manifest, AS_OF)

    def test_export_mutation_cannot_change_later_results(self):
        original = json.loads(json.dumps(self.snapshot.report()))
        report = self.snapshot.report()
        report["evidence"][0]["status"] = "FORGED"
        report["tasks"][0]["instruction"] = "Skip checking"
        for task in report["tasks"]:
            if task["kind"] == "resolve_fact":
                task["fact_key"][0] = "FORGED"
                task["provenance"][0]["value"] = "FORGED"
        self.assertEqual(self.snapshot.report(), original)

    def test_plan_exports_are_detached_even_at_nested_provenance(self):
        original = json.loads(json.dumps(self.snapshot.plan("g0000-conflict")))
        plan = self.snapshot.plan("g0000-conflict")
        task = plan["plans"][0]["tasks"][0]
        task["reason"] = "FORGED"
        task["provenance"].clear()
        self.assertEqual(self.snapshot.plan("g0000-conflict"), original)
        json.loads(json.dumps(original))  # Standard serializable lists/dicts.

    def test_all_snapshot_maps_and_nested_records_are_read_only(self):
        for name in ("versions", "evidence", "facts", "tasks", "claims", "answers", "claim_by_id", "answer_by_id", "fact_blockers"):
            mapping = getattr(self.snapshot, name)
            with self.subTest(name=name), self.assertRaises(TypeError):
                mapping["injected"] = None
        with self.assertRaises(TypeError):
            self.snapshot.evidence[Evidence("g0000-status", "v1")]["status"] = "FORGED"
        task = next(t for t in self.snapshot.tasks.values() if t["kind"] == "resolve_fact")
        with self.assertRaises(TypeError):
            task["provenance"][0]["value"] = "FORGED"
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            self.snapshot.as_of = None

    def test_mutating_manifest_export_preserves_snapshot_identity(self):
        data = self.manifest.to_dict()
        data["sources"][0]["versions"][0]["facts"].clear()
        self.assertEqual(self.snapshot.manifest.fingerprint, self.manifest.fingerprint)
        self.assertEqual(compare(self.snapshot, Snapshot(self.manifest, AS_OF))["changed_evidence"], [])


if __name__ == "__main__":
    unittest.main()
