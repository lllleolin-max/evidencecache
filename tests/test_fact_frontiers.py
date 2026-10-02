"""Independent Boolean subset oracle including shared fact obligations.

The oracle evaluates raw fixtures under hypothetical completed tasks. It never
calls the antichain implementation, `_frontier`, or engine task-ID helpers.
"""
from copy import deepcopy
from itertools import combinations
import json
import random
import unittest

from evidencecache import Manifest, PlanningLimitError, Snapshot
from evidencecache.fixtures import AS_OF


def fact(key="price", value=10):
    return dict(subject="plan", predicate=key, scope="eu", value=value)


def evidence(source):
    return {"evidence": {"source": source, "version": "v1"}}


def task_id(prefix, items):
    return prefix + json.dumps(items, separators=(",", ":"), ensure_ascii=False)


def minimal_oracle(data, answer_id):
    """Exhaustively evaluate all obligation subsets, then compare set inclusion.

    Fixtures deliberately contain only v1 at a fixed UTC instant with TTL equal
    to one or two days. Lifecycle behavior is tested separately; this oracle
    checks Boolean/fact composition without duplicating the optimizer.
    """
    fresh = {s["id"] for s in data["sources"] if s["versions"][0]["ttl_seconds"] > 86400}
    claims = {c["id"]: c for c in data["claims"]}
    answer = next(a for a in data["answers"] if a["id"] == answer_id)
    assertions = {}
    for source in data["sources"]:
        if source["id"] not in fresh:
            continue
        for value in source["versions"][0]["facts"]:
            key = tuple(value[k] for k in ("subject", "predicate", "scope"))
            assertions.setdefault(key, set()).add(json.dumps(value["value"]))
    blockers = {}
    for claim in claims.values():
        if "fact" not in claim:
            continue
        key = tuple(claim["fact"][k] for k in ("subject", "predicate", "scope"))
        values = assertions.get(key, set())
        if len(values) > 1 or (values and json.dumps(claim["fact"]["value"]) not in values):
            blockers[claim["id"]] = task_id("resolve:", list(key))
    universe = sorted({task_id("refresh:", [s["id"], "v1"]) for s in data["sources"] if s["id"] not in fresh}
                      | set(blockers.values()))

    def evaluate(expr, chosen, memo):
        if "evidence" in expr:
            source = expr["evidence"]["source"]
            return source in fresh or task_id("refresh:", [source, "v1"]) in chosen
        if "claim" in expr:
            key = expr["claim"]
            if key not in memo:
                memo[key] = evaluate(claims[key]["support"], chosen, memo) and (
                    key not in blockers or blockers[key] in chosen)
            return memo[key]
        operator = "all" if "all" in expr else "any"
        return (all if operator == "all" else any)(evaluate(child, chosen, memo) for child in expr[operator])

    satisfying = []
    for size in range(len(universe) + 1):
        for subset in combinations(universe, size):
            chosen = frozenset(subset)
            if evaluate(answer["support"], chosen, {}) and not any(prior < chosen for prior in satisfying):
                satisfying.append(chosen)
    return set(satisfying)


def shared_fact_fixture(nested=False, second_key=False, duplicate=False):
    data = dict(schema_version=1, sources=[
        dict(id=name, uri="urn:oracle:" + name, versions=[dict(
            id="v1", observed_at="2026-01-01T00:00:00Z", ttl_seconds=ttl,
            facts=[fact("price", value), fact("retention", retention)])])
        for name, ttl, value, retention in (("fresh", 172800, 10, 30), ("opponent", 172800, 20, 45),
                                            ("stale", 86400, 10, 30))], claims=[], answers=[])
    data["claims"].append(dict(id="inner", text="Declared price", fact=fact(), support=evidence("fresh")))
    alternative = {"claim": "inner"} if duplicate else evidence("stale")
    support = {"any": [{"claim": "inner"}, alternative]}
    if nested:
        support = {"all": [support, {"any": [evidence("fresh"), evidence("stale")]}]}
    data["claims"].append(dict(id="outer", text="Declared fact", fact=fact("retention", 30) if second_key else fact(),
                               support=support))
    data["answers"] = [dict(id="direct", text="Direct claim leaf", support={"claim": "outer"}),
                       dict(id="nested", text="Nested answer", support={"all": [
                           {"claim": "outer"}, {"any": [{"claim": "inner"}, {"claim": "outer"}]}]})]
    return data


class FactFrontierTests(unittest.TestCase):
    def assert_oracle(self, data):
        snap = Snapshot(Manifest.from_dict(data), AS_OF)
        for answer in data["answers"]:
            result = snap.plan(answer["id"])
            plans = [frozenset(p["task_ids"]) for p in result["plans"]]
            with self.subTest(answer=answer["id"]):
                self.assertTrue(result["exact"])
                self.assertEqual(set(plans), minimal_oracle(data, answer["id"]))
                self.assertEqual(len(plans), len(set(plans)), "No duplicate obligation sets")
                self.assertFalse(any(a < b for a in plans for b in plans), "No strict supersets")

    def test_reviewed_shared_fact_case_requires_only_one_resolution(self):
        data = shared_fact_fixture()
        self.assert_oracle(data)
        plan = Snapshot(Manifest.from_dict(data), AS_OF).plan("direct")
        expected = task_id("resolve:", ["plan", "price", "eu"])
        self.assertEqual([p["task_ids"] for p in plan["plans"]], [[expected]])

    def test_nested_and_or_shared_fact_obligation(self):
        self.assert_oracle(shared_fact_fixture(nested=True))

    def test_equal_unions_are_deduplicated(self):
        self.assert_oracle(shared_fact_fixture(duplicate=True))

    def test_shared_contradicted_fact_obligation_is_also_minimal(self):
        data = shared_fact_fixture()
        # One fresh value contradicts a producer-declared derived fact. Both
        # nested claims share its resolution obligation, without a multi-value
        # conflict. The alternative directly cites a stale matching assertion.
        data["sources"] = [s for s in data["sources"] if s["id"] != "opponent"]
        data["sources"][-1]["versions"][0]["facts"][0]["value"] = 20
        data["claims"].insert(0, dict(id="base", text="Producer premise", support=evidence("fresh")))
        data["claims"][1]["support"] = {"claim": "base"}
        for claim in data["claims"][1:]:
            claim["fact"]["value"] = 20
        self.assert_oracle(data)
        snap = Snapshot(Manifest.from_dict(data), AS_OF)
        self.assertEqual(snap.plan("direct")["plans"][0]["tasks"][0]["reason"], "CONTRADICTED")
        self.assertEqual(snap.witnesses("direct")["witnesses"], [])

    def test_different_fact_obligations_keep_incomparable_alternatives(self):
        data = shared_fact_fixture(second_key=True)
        self.assert_oracle(data)
        plans = Snapshot(Manifest.from_dict(data), AS_OF).plan("direct")["plans"]
        self.assertEqual(len(plans), 2)
        self.assertEqual({len(p["task_ids"]) for p in plans}, {2})

    def test_blocker_union_minimization_spends_query_budget(self):
        # Single fact-bearing leaf has no AND/OR work: adding its resolution
        # obligation must now count as one candidate, even without an answer op.
        data = shared_fact_fixture()
        data["claims"] = data["claims"][:1]
        data["answers"] = [dict(id="a", text="Single claim", support={"claim": "inner"})]
        plan = Snapshot(Manifest.from_dict(data), AS_OF).plan("a", max_work=1)
        self.assertEqual(plan["candidates_examined"], 1)
        snap = Snapshot(Manifest.from_dict(shared_fact_fixture()), AS_OF)
        with self.assertRaises(PlanningLimitError):
            snap.plan("direct", max_work=3)
        self.assert_oracle(shared_fact_fixture())

    def test_permutation_preserves_shared_fact_frontier(self):
        data = shared_fact_fixture(nested=True)
        other = deepcopy(data)
        for key in ("sources", "claims", "answers"):
            other[key].reverse()
        old = Snapshot(Manifest.from_dict(data), AS_OF).plan("direct")["plans"]
        new = Snapshot(Manifest.from_dict(other), AS_OF).plan("direct")["plans"]
        self.assertEqual(old, new)

    def test_random_fact_dags_against_independent_truth_table(self):
        for seed in range(100):
            rng = random.Random(seed)
            data = shared_fact_fixture()
            data["claims"] = []
            data["sources"].append(dict(id="stale2", uri="urn:oracle:stale2", versions=[dict(
                id="v1", observed_at="2026-01-01T00:00:00Z", ttl_seconds=86400,
                facts=[fact(), fact("retention", 30)])]))
            # Vary active conflict keys while retaining one always-fresh source.
            opponent = data["sources"][1]["versions"][0]
            opponent["ttl_seconds"] = rng.choice((86400, 172800))
            opponent["facts"][0]["value"] = rng.choice((10, 20))
            opponent["facts"][1]["value"] = rng.choice((30, 45))
            for i in range(6):
                leaves = [evidence(rng.choice(("fresh", "stale", "stale2"))) for _ in range(2)]
                if i:
                    leaves.extend({"claim": f"c{rng.randrange(i)}"} for _ in range(2))
                support = {rng.choice(("all", "any")): [
                    {rng.choice(("all", "any")): leaves[:2]}, *leaves[2:]]}
                claim = dict(id=f"c{i}", text="Oracle declaration", support=support)
                chosen = rng.choice((None, "price", "retention"))
                if chosen:
                    claim["fact"] = fact(chosen, 10 if chosen == "price" else 30)
                # Include the audited shared-obligation motif in diverse later
                # graphs, and independently query every intermediate claim.
                if i == 0:
                    claim.update(fact=fact(), support=evidence("fresh"))
                elif i == 1:
                    claim.update(fact=fact(), support={"any": [{"claim": "c0"}, evidence("stale")]})
                data["claims"].append(claim)
            data["answers"] = [dict(id=f"direct{i}", text="Direct", support={"claim": f"c{i}"}) for i in range(6)] + [
                dict(id="all", text="Nested conjunction", support={"all": [{"claim": "c5"},
                    {"any": [{"claim": "c3"}, {"claim": "c4"}]}]}),
                dict(id="any", text="Nested alternatives", support={"any": [{"claim": "c5"},
                    {"all": [{"claim": "c3"}, {"claim": "c4"}]}]})]
            with self.subTest(seed=seed):
                self.assert_oracle(data)


if __name__ == "__main__":
    unittest.main()
