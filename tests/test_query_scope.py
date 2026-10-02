import unittest

from evidencecache import Manifest, ManifestError, PlanningLimitError, Snapshot
from evidencecache.fixtures import AS_OF, evidence, fixture


def unrelated_frontier(fresh: bool) -> dict:
    data = dict(schema_version=1, sources=[], claims=[], answers=[])
    for i in range(25):
        data["sources"].append(dict(id=f"s{i}", uri=f"urn:test:{i}", versions=[
            dict(id="v1", observed_at="2026-01-01T00:00:00Z",
                 ttl_seconds=172800 if fresh else 86400, facts=[])]))
    data["claims"] = [
        dict(id="simple", text="Independent answer", support=evidence("s24")),
        dict(id="unrelated", text="Unrelated conjunction", support={"all": [
            {"any": [evidence(f"s{i}"), evidence(f"s{i+1}")]} for i in range(0, 24, 2)]})]
    data["answers"] = [dict(id="simple", text="One citation", support={"claim": "simple"}),
                       dict(id="expensive", text="Many citations", support={"claim": "unrelated"})]
    return data


class QueryScopeTests(unittest.TestCase):
    def test_one_task_plan_ignores_unrelated_exponential_frontier(self):
        snap = Snapshot(Manifest.from_dict(unrelated_frontier(False)), AS_OF)
        plan = snap.plan("simple", max_work=100)
        self.assertTrue(plan["exact"])
        self.assertEqual(plan["minimum_task_count"], 1)
        self.assertEqual([task["source"] for task in plan["plans"][0]["tasks"]], ["s24"])
        with self.assertRaises(PlanningLimitError):
            snap.plan("expensive", max_work=100)

    def test_one_leaf_witness_ignores_unrelated_exponential_frontier(self):
        snap = Snapshot(Manifest.from_dict(unrelated_frontier(True)), AS_OF)
        self.assertEqual(snap.witnesses("simple", max_work=100)["witnesses"], [[dict(source="s24", version="v1")]])
        with self.assertRaises(PlanningLimitError):
            snap.witnesses("expensive", max_work=100)

    def test_transitive_diamond_claim_dependencies_remain_in_scope(self):
        data = unrelated_frontier(False)
        data["claims"].extend([
            dict(id="left", text="Left derivative", support={"claim": "simple"}),
            dict(id="right", text="Right derivative", support={"claim": "simple"}),
            dict(id="joined", text="Shared proof", support={"all": [{"claim": "left"}, {"claim": "right"}]})])
        data["answers"][0]["support"] = {"claim": "joined"}
        plan = Snapshot(Manifest.from_dict(data), AS_OF).plan("simple", max_work=100)
        self.assertEqual(plan["minimum_task_count"], 1)
        self.assertEqual([task["source"] for task in plan["plans"][0]["tasks"]], ["s24"])

    def test_global_uncited_fact_conflicts_are_not_pruned(self):
        snap = Snapshot(Manifest.from_dict(fixture(2)), AS_OF)
        plan = snap.plan("g0000-conflict", max_work=1)
        task = plan["plans"][0]["tasks"][0]
        self.assertEqual(task["kind"], "resolve_fact")
        self.assertEqual({p["source"] for p in task["provenance"]}, {"g0000-price", "g0000-billing"})
        self.assertEqual(snap.witnesses("g0000-conflict", max_work=1)["witnesses"], [])

    def test_invalid_bound_and_unknown_answer_still_raise_domain_error(self):
        snap = Snapshot(Manifest.from_dict(fixture()), AS_OF)
        for bound in (0, -1, True, 1.5):
            with self.subTest(bound=bound), self.assertRaises(ManifestError):
                snap.plan("g0000-conflict", max_work=bound)
        with self.assertRaises(ManifestError):
            snap.witnesses("unknown", max_work=1)


if __name__ == "__main__":
    unittest.main()
