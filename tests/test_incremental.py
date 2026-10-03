from copy import deepcopy
from datetime import datetime, timedelta, timezone
import random
import unittest

from evidencecache import Manifest, ManifestError, PlanningLimitError, Snapshot, SnapshotCache, apply_event
from evidencecache.fixtures import AS_OF, fixture


DOMAIN = "synthetic-curated-domain"


def branches(count):
    data = dict(schema_version=1, sources=[], claims=[], answers=[])
    for i in range(count):
        key = f"b{i:03d}"
        fact = dict(subject=key, predicate="value", scope=DOMAIN, value=i)
        data["sources"].append(dict(id=key, uri="urn:synthetic:" + key, versions=[dict(
            id="v1", observed_at="2026-01-01T00:00:00Z", ttl_seconds=259200, facts=[fact])]))
        data["claims"].append(dict(id=key, text="Declared value", fact=fact,
            support={"evidence": dict(source=key, version="v1")}))
        data["answers"].append(dict(id=key, text="Declared answer", support={"claim": key}))
    return data


def same(test, candidate):
    full = Snapshot(candidate.manifest, candidate.as_of.isoformat())
    for name in ("versions", "evidence", "facts", "tasks", "claims", "answers", "fact_blockers",
                 "claim_by_id", "answer_by_id"):
        test.assertEqual(getattr(candidate, name), getattr(full, name), name)
    test.assertEqual(candidate.report(), full.report())
    for key in candidate.answers:
        for operation in ("plan", "witnesses"):
            for budget in (1, 4, 5, 100000):
                def invoke(snapshot):
                    try:
                        return getattr(snapshot, operation)(key, budget)
                    except PlanningLimitError:
                        return "UNKNOWN:PlanningLimitError"
                test.assertEqual(invoke(candidate), invoke(full), (operation, key, budget))


class IncrementalTests(unittest.TestCase):
    def test_one_branch_evaluation_and_identity_reuse(self):
        data = branches(300)
        cache = SnapshotCache(Manifest.from_dict(data), AS_OF, trust_domain=DOMAIN)
        before = cache.snapshot
        event = dict(kind="publish", source="b000", version=dict(id="v2", observed_at=AS_OF,
            ttl_seconds=259200, facts=data["sources"][0]["versions"][0]["facts"]))
        after = cache.apply_event(event, trust_domain=DOMAIN)
        self.assertEqual({key: after.work[key] for key in ("sources_evaluated", "versions_evaluated",
                         "claims_evaluated", "answers_evaluated")}, dict(sources_evaluated=1,
                         versions_evaluated=2, claims_evaluated=1, answers_evaluated=1))
        for key in ("b001", "b299"):
            self.assertIs(before.claims[key], after.claims[key])
            self.assertIs(before.answers[key], after.answers[key])
        self.assertTrue(before.answers["b000"].valid)
        self.assertFalse(after.answers["b000"].valid)
        same(self, after)

    def test_uncited_new_global_conflict_and_removal(self):
        data = branches(2)
        cache = SnapshotCache(Manifest.from_dict(data), AS_OF, trust_domain=DOMAIN)
        source = deepcopy(data["sources"][0])
        source.update(id="uncited", uri="urn:synthetic:uncited")
        source["versions"][0]["facts"][0]["value"] = 999
        data["sources"].append(source)
        after = cache.update(Manifest.from_dict(data), AS_OF, trust_domain=DOMAIN)
        self.assertFalse(after.answers["b000"].valid)
        self.assertEqual(after.work["sources_evaluated"], 1)
        self.assertEqual(after.work["claims_evaluated"], 1)
        task = next(row for row in after.tasks.values() if row["kind"] == "resolve_fact")
        self.assertEqual([row["source"] for row in task["provenance"]], ["b000", "uncited"])
        same(self, after)
        data["sources"].pop()
        same(self, cache.update(Manifest.from_dict(data), AS_OF, trust_domain=DOMAIN))
        self.assertTrue(cache.snapshot.answers["b000"].valid)

    def test_time_boundaries_both_directions_and_no_fallback(self):
        data = branches(1)
        data["sources"][0]["versions"] += [dict(id="v2", observed_at=AS_OF, ttl_seconds=0,
            revoked_at="2026-01-02T01:00:00Z", facts=[])]
        cache = SnapshotCache(Manifest.from_dict(data), "2026-01-01T23:59:59.999999Z", trust_domain=DOMAIN)
        for instant in (AS_OF, "2026-01-02T01:00:00Z", "2026-01-01T23:59:59.999999Z",
                        "2026-01-04T00:00:00Z", "2025-12-31T23:59:59Z", AS_OF):
            same(self, cache.advance(instant, trust_domain=DOMAIN))

    def test_rebind_mutation_domain_and_atomic_failures(self):
        data = branches(2)
        cache = SnapshotCache(Manifest.from_dict(data), AS_OF, trust_domain=DOMAIN)
        before = cache.snapshot
        event = dict(kind="publish", source="b000", rebind_from="v1", version=dict(id="v2",
            observed_at=AS_OF, ttl_seconds=172800, facts=deepcopy(data["sources"][0]["versions"][0]["facts"])))
        after = cache.apply_event(event, trust_domain=DOMAIN)
        self.assertTrue(after.answers["b000"].valid)
        self.assertEqual(after.work["mode"], "incremental")
        same(self, after)
        event["version"]["facts"][0]["value"] = 123
        data["sources"].clear()
        report = before.report()
        report["answers"].clear()
        self.assertEqual(len(before.report()["answers"]), 2)
        self.assertEqual(after.claim_by_id["b000"].fact.to_dict()["value"], 0)
        for action in (lambda: cache.advance(AS_OF, trust_domain="foreign"),
                       lambda: cache.advance("invalid-time", trust_domain=DOMAIN),
                       lambda: cache.apply_event(event, trust_domain=DOMAIN)):
            current = cache.snapshot
            with self.assertRaises(ManifestError):
                action()
            self.assertIs(current, cache.snapshot)
        with self.assertRaises(AttributeError):
            cache.trust_domain = "foreign"

    def test_graph_edit_falls_back(self):
        data = branches(2)
        cache = SnapshotCache(Manifest.from_dict(data), AS_OF, trust_domain=DOMAIN)
        data["answers"][0]["support"] = {"all": [{"claim": "b000"}, {"claim": "b001"}]}
        after = cache.update(Manifest.from_dict(data), AS_OF, trust_domain=DOMAIN)
        self.assertEqual(after.work["mode"], "full")
        same(self, after)

    def test_100_seeded_event_time_compositions(self):
        rng = random.Random(62120261003)
        origin = datetime(2026, 1, 2, tzinfo=timezone.utc)
        for sequence in range(100):
            cache = SnapshotCache(Manifest.from_dict(fixture()), AS_OF, trust_domain=DOMAIN)
            for step in range(8):
                manifest = cache.snapshot.manifest
                choice = rng.randrange(5)
                if choice == 0:
                    instant = origin + timedelta(hours=rng.randrange(-25, 73))
                    result = cache.advance(instant.isoformat(), trust_domain=DOMAIN)
                elif choice == 1:
                    source = rng.choice(manifest.sources)
                    version = source.versions[-1]
                    new_at = max(origin + timedelta(hours=step + 1), version.observed_at + timedelta(seconds=1))
                    event = dict(kind="publish", source=source.id, version=dict(id=f"p{step}",
                        observed_at=new_at.isoformat(), ttl_seconds=rng.choice((0, 3600, 172800)),
                        facts=[fact.to_dict() for fact in version.facts]))
                    if rng.randrange(2):
                        event["rebind_from"] = version.id
                    result = cache.apply_event(event, trust_domain=DOMAIN)
                elif choice == 2:
                    candidates = [(source, version) for source in manifest.sources for version in source.versions
                                  if version.revoked_at is None]
                    if candidates:
                        source, version = rng.choice(candidates)
                        result = cache.apply_event(dict(kind="revoke", source=source.id, version=version.id,
                            at=max(origin, version.observed_at).isoformat()), trust_domain=DOMAIN)
                    else:
                        result = cache.advance(origin.isoformat(), trust_domain=DOMAIN)
                elif choice == 3:
                    data = manifest.to_dict()
                    source = deepcopy(data["sources"][0])
                    source.update(id=f"uncited{step}", uri="urn:synthetic:uncited")
                    source["versions"] = [dict(id="v1", observed_at=AS_OF, ttl_seconds=172800,
                        facts=[dict(subject="team-0", predicate="retention_days", scope="default", value=999)])]
                    # Use an existing declared key, rather than assuming fixture spelling.
                    source["versions"][0]["facts"] = [dict(manifest.claims[0].fact.to_dict(), value=999)]
                    data["sources"].append(source)
                    result = cache.update(Manifest.from_dict(data), cache.snapshot.as_of.isoformat(), trust_domain=DOMAIN)
                else:
                    data = manifest.to_dict()
                    data["answers"][0]["text"] = f"Regenerated {sequence}:{step}"
                    result = cache.update(Manifest.from_dict(data), cache.snapshot.as_of.isoformat(), trust_domain=DOMAIN)
                with self.subTest(sequence=sequence, step=step):
                    same(self, result)


if __name__ == "__main__":
    unittest.main()
