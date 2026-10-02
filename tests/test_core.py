from copy import deepcopy
from itertools import combinations
import json
import random
import unittest

from evidencecache import Manifest, ManifestError, PlanningLimitError, Snapshot, apply_event, compare, loads
from evidencecache.fixtures import AS_OF, evidence, fixture
from evidencecache.model import Evidence, timestamp


def graph(support, fresh=(), count=6):
    return dict(schema_version=1,
                sources=[dict(id=f"s{i}", uri=f"urn:test:{i}", versions=[dict(id="v1", observed_at="2026-01-01T00:00:00Z",
                             ttl_seconds=172800 if i in fresh else 86400, facts=[])]) for i in range(count)],
                claims=[dict(id="c", text="An explicitly declared proposition.", support=support)],
                answers=[dict(id="a", text="An explicitly declared answer.", support={"claim": "c"})])


class TemporalTests(unittest.TestCase):
    def test_exact_half_open_ttl_and_offset(self):
        m = Manifest.from_dict(graph(evidence("s0"), count=1))
        for instant, expected in (("2026-01-01T23:59:59.999999Z", True), (AS_OF, False),
                                  ("2026-01-02T08:00:00+08:00", False), ("2026-01-01T19:00:00-05:00", False)):
            with self.subTest(instant=instant):
                self.assertEqual(Snapshot(m, instant).answers["a"].valid, expected)

    def test_future_not_available_and_zero_ttl(self):
        d = graph(evidence("s0"), count=1)
        d["sources"][0]["versions"][0]["ttl_seconds"] = 0
        m = Manifest.from_dict(d)
        self.assertEqual(Snapshot(m, "2025-12-31T23:59:59Z").evidence[Evidence("s0", "v1")]["status"], "NOT_YET_OBSERVED")
        self.assertEqual(Snapshot(m, "2026-01-01T00:00:00Z").evidence[Evidence("s0", "v1")]["status"], "EXPIRED")

    def test_no_fallback_after_new_version_revoked(self):
        d = graph(evidence("s0"), fresh=(0,), count=1)
        d["sources"][0]["versions"].append(dict(id="v2", observed_at="2026-01-01T12:00:00Z", ttl_seconds=86400,
                                                revoked_at="2026-01-01T18:00:00Z", facts=[]))
        m = Manifest.from_dict(d)
        self.assertTrue(Snapshot(m, "2026-01-01T11:59:59Z").answers["a"].valid)
        snap = Snapshot(m, AS_OF)
        self.assertEqual(snap.evidence[Evidence("s0", "v1")]["status"], "SUPERSEDED")
        self.assertEqual(snap.evidence[Evidence("s0", "v2")]["status"], "REVOKED")
        self.assertFalse(snap.answers["a"].valid)

    def test_future_revocation_and_exact_boundary(self):
        d = graph(evidence("s0"), fresh=(0,), count=1)
        d["sources"][0]["versions"][0]["revoked_at"] = AS_OF
        m = Manifest.from_dict(d)
        self.assertTrue(Snapshot(m, "2026-01-01T23:59:59.999999Z").answers["a"].valid)
        self.assertFalse(Snapshot(m, AS_OF).answers["a"].valid)

    def test_naive_invalid_date_and_overflow(self):
        for instant in ("2026-01-01T00:00:00", "2026-02-30T00:00:00Z", "today", "2026-01-01", "0001-01-01T00:00:00+12:00"):
            with self.subTest(instant=instant), self.assertRaises(ManifestError):
                timestamp(instant)


class ValidationTests(unittest.TestCase):
    def test_round_trip_and_permutation(self):
        d = fixture(3)
        m = Manifest.from_dict(d)
        for key in ("sources", "claims", "answers"):
            d[key].reverse()
        other = loads(json.dumps(d))
        self.assertEqual(m.fingerprint, other.fingerprint)
        self.assertEqual(Snapshot(m, AS_OF).report(), Snapshot(other, AS_OF).report())
        self.assertEqual(m, Manifest.from_dict(m.to_dict()))

    def test_unknown_fields_and_duplicate_json_keys(self):
        with self.assertRaises(ManifestError):
            loads('{"schema_version":1,"schema_version":1}')
        d = fixture()
        d["sources"][0]["tttl"] = 30
        with self.assertRaises(ManifestError):
            Manifest.from_dict(d)

    def test_dangling_evidence_claim_and_cycle(self):
        for mutation in (lambda d: d["claims"][0].update(support=evidence("unknown")),
                         lambda d: d["claims"][0].update(support={"claim": "unknown"}),
                         lambda d: d["claims"][0].update(support={"claim": d["claims"][0]["id"]})):
            d = fixture()
            mutation(d)
            with self.assertRaises(ManifestError):
                Manifest.from_dict(d)

    def test_duplicate_identifiers_and_instants(self):
        for variant in ("source", "claim", "version", "instant"):
            d = fixture()
            if variant == "source":
                d["sources"].append(deepcopy(d["sources"][0]))
            elif variant == "claim":
                d["claims"].append(deepcopy(d["claims"][0]))
            else:
                v = deepcopy(d["sources"][0]["versions"][0])
                v.update(id="v1" if variant == "version" else "v2", observed_at="2026-01-01T08:00:00+08:00")
                d["sources"][0]["versions"].append(v)
            with self.subTest(variant=variant), self.assertRaises(ManifestError):
                Manifest.from_dict(d)

    def test_empty_combinators_bool_ttl_and_nonfinite(self):
        for support in ({"all": []}, {"any": []}, {"all": [], "claim": "c"}):
            with self.assertRaises(ManifestError):
                Manifest.from_dict(graph(support))
        d = graph(evidence("s0"))
        d["sources"][0]["versions"][0]["ttl_seconds"] = True
        with self.assertRaises(ManifestError):
            Manifest.from_dict(d)
        with self.assertRaises(ManifestError):
            loads('{"bad":NaN}')

    def test_fact_pinning_and_scope(self):
        d = fixture()
        d["claims"][0]["fact"]["value"] = 999
        with self.assertRaises(ManifestError):
            Manifest.from_dict(d)
        d = fixture()
        d["sources"][-1]["versions"][0]["facts"][0]["scope"] = "region:us;tier:pro"
        self.assertTrue(Snapshot(Manifest.from_dict(d), AS_OF).answers["g0000-conflict"].valid)

    def test_deep_claim_chain_uses_no_graph_recursion(self):
        d = graph(evidence("s0"), fresh=(0,), count=1)
        for i in range(1200):
            d["claims"].append(dict(id=f"c{i}", text="Derived statement", support={"claim": "c" if i == 0 else f"c{i-1}"}))
        d["answers"][0]["support"] = {"claim": "c1199"}
        self.assertTrue(Snapshot(Manifest.from_dict(d), AS_OF).answers["a"].valid)


class EvaluationTests(unittest.TestCase):
    def test_alternative_evidence_keeps_answer_valid(self):
        s = Snapshot(Manifest.from_dict(fixture()), AS_OF)
        self.assertTrue(s.answers["g0000-alternative"].valid)
        self.assertEqual(s.plan("g0000-alternative")["plans"], [dict(task_ids=[], tasks=[])])
        self.assertEqual(s.witnesses("g0000-alternative")["witnesses"], [[dict(source="g0000-mirror", version="v1")]])

    def test_conflict_external_to_citation_cone(self):
        s = Snapshot(Manifest.from_dict(fixture()), AS_OF)
        self.assertFalse(s.answers["g0000-conflict"].valid)
        task = s.plan("g0000-conflict")["plans"][0]["tasks"][0]
        self.assertEqual(task["kind"], "resolve_fact")
        self.assertEqual({e["source"] for e in task["provenance"]}, {"g0000-price", "g0000-billing"})
        self.assertEqual(s.witnesses("g0000-conflict")["witnesses"], [])

    def test_stale_disagreement_does_not_block(self):
        d = fixture()
        d["sources"][-1]["versions"][0]["ttl_seconds"] = 86400
        self.assertTrue(Snapshot(Manifest.from_dict(d), AS_OF).answers["g0000-conflict"].valid)

    def test_fact_integer_and_boolean_are_distinct(self):
        d = fixture()
        d["sources"][-2]["versions"][0]["facts"][0]["value"] = 1
        d["sources"][-1]["versions"][0]["facts"][0]["value"] = True
        d["claims"][-1]["fact"]["value"] = 1
        self.assertFalse(Snapshot(Manifest.from_dict(d), AS_OF).answers["g0000-conflict"].valid)

    def test_single_source_replacement_minimal_blast_radius(self):
        m = Manifest.from_dict(fixture(4))
        event = dict(kind="publish", source="g0000-status", version=dict(id="v2", observed_at=AS_OF,
                     ttl_seconds=86400, facts=fixture()["sources"][2]["versions"][0]["facts"]))
        after = apply_event(m, event)
        result = compare(Snapshot(m, AS_OF), Snapshot(after, AS_OF))
        self.assertEqual(result["invalidated_answers"], ["g0000-steady"])
        self.assertEqual(len(result["still_valid_answers"]), 7)
        self.assertEqual(len(m.sources[2].versions), 1)

    def test_rebind_preserves_fact_and_rejects_changed_fact(self):
        m = Manifest.from_dict(fixture())
        event = dict(kind="publish", source="g0000-status", rebind_from="v1", version=dict(id="v2", observed_at=AS_OF,
                     ttl_seconds=86400, facts=fixture()["sources"][2]["versions"][0]["facts"]))
        after = apply_event(m, event)
        self.assertTrue(Snapshot(after, AS_OF).answers["g0000-steady"].valid)
        event["version"]["facts"][0]["value"] = "outage"
        with self.assertRaises(ManifestError):
            apply_event(m, event)

    def test_revoke_is_idempotent_but_cannot_be_retimed(self):
        m = Manifest.from_dict(fixture())
        event = dict(kind="revoke", source="g0000-billing", version="v1", at=AS_OF)
        updated = apply_event(m, event)
        self.assertTrue(Snapshot(updated, AS_OF).answers["g0000-conflict"].valid)
        self.assertEqual(updated.fingerprint, apply_event(updated, event).fingerprint)
        with self.assertRaises(ManifestError):
            apply_event(updated, dict(event, at="2026-01-02T01:00:00Z"))


class PlanningTests(unittest.TestCase):
    def test_shared_obligation_beats_independent_greedy_choice(self):
        support = {"all": [{"any": [evidence("s0"), evidence("s1")]}, {"any": [evidence("s1"), evidence("s2")]}]}
        s = Snapshot(Manifest.from_dict(graph(support)), AS_OF)
        plan = s.plan("a")
        self.assertEqual(plan["minimum_task_count"], 1)
        self.assertEqual([t["source"] for t in plan["plans"][0]["tasks"]], ["s1"])
        self.assertEqual([{t["source"] for t in p["tasks"]} for p in plan["plans"]], [{"s1"}, {"s0", "s2"}])

    def test_limit_never_returns_partial_exact_frontier(self):
        support = {"all": [{"any": [evidence("s0"), evidence("s1")]}, {"any": [evidence("s2"), evidence("s3")]}]}
        s = Snapshot(Manifest.from_dict(graph(support)), AS_OF)
        with self.assertRaises(PlanningLimitError):
            s.plan("a", max_work=2)

    def test_random_dags_against_exhaustive_boolean_oracle(self):
        # Independent solver enumerates all source assignments, not antichain products.
        for seed in range(60):
            rng = random.Random(seed)
            fresh = set(rng.sample(range(6), rng.randrange(4)))
            d = graph(evidence("s0"), fresh=fresh)
            claim_expr = {}
            for i in range(6):
                leaves = [evidence(f"s{rng.randrange(6)}") for _ in range(3)]
                if i:
                    leaves.append({"claim": f"c{i-1}"})
                claim_expr[f"c{i}"] = {rng.choice(["all", "any"]): leaves}
            d["claims"] = [dict(id=k, text="Oracle graph claim", support=v) for k, v in claim_expr.items()]
            d["answers"][0]["support"] = {"all": [{"claim": "c4"}, {"claim": "c5"}]}
            def oracle(expr, active):
                if "evidence" in expr:
                    return int(expr["evidence"]["source"][1:]) in active
                if "claim" in expr:
                    return oracle(claim_expr[expr["claim"]], active)
                op = next(iter(expr))
                return (all if op == "all" else any)(oracle(x, active) for x in expr[op])
            satisfying = []
            stale = set(range(6)) - fresh
            for size in range(7):
                for selected in combinations(sorted(stale), size):
                    chosen = set(selected)
                    if oracle(d["answers"][0]["support"], fresh | chosen) and not any(prev <= chosen for prev in satisfying):
                        satisfying.append(chosen)
            snap = Snapshot(Manifest.from_dict(d), AS_OF)
            result = [{int(task["source"][1:]) for task in p["tasks"]} for p in snap.plan("a")["plans"]]
            with self.subTest(seed=seed):
                self.assertEqual({frozenset(x) for x in result}, {frozenset(x) for x in satisfying})
                self.assertEqual(snap.answers["a"].valid, oracle(d["answers"][0]["support"], fresh))


if __name__ == "__main__":
    unittest.main()
