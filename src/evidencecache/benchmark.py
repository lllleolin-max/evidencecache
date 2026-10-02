"""Reproducible policy contrast, not a throughput or competitor benchmark."""
from __future__ import annotations

from copy import deepcopy

from .engine import Snapshot, compare
from .events import apply_event
from .fixtures import AS_OF, fixture
from .model import Evidence, Manifest, ManifestError


def _references(manifest: Manifest) -> dict[str, set[Evidence]]:
    claims = {c.id: c for c in manifest.claims}
    refs = {}
    for key in manifest.order:
        refs[key] = set()
        for leaf in claims[key].support.leaves():
            refs[key].update({leaf.evidence} if leaf.op == "evidence" else refs[leaf.claim])
    return {a.id: set().union(*(refs[x.claim] for x in a.support.leaves())) for a in manifest.answers}


def benchmark(groups: int = 100) -> dict:
    if type(groups) is not int or not 1 <= groups <= 1000:
        raise ManifestError("groups must be an integer in [1, 1000]")
    data = fixture(groups)
    manifest = Manifest.from_dict(data)
    snap = Snapshot(manifest, AS_OF)
    refs = _references(manifest)
    # Stronger than bare timestamp TTL: these baselines also honor version replacement/revocation.
    flat = {answer: all(snap.evidence[r]["status"] == "FRESH" for r in dependencies)
            for answer, dependencies in refs.items()}
    whole_gate = all(flat.values())
    whole = {answer: whole_gate for answer in flat}
    expected = {a.id: not a.id.endswith("-conflict") for a in manifest.answers}
    measured = {k: s.valid for k, s in snap.answers.items()}
    if expected != measured:
        raise AssertionError("engine disagrees with fixture's independently declared scenario labels")
    no_conflicts = deepcopy(data)
    for claim in no_conflicts["claims"]:
        claim.pop("fact", None)
    no_or = deepcopy(data)
    for claim in no_or["claims"]:
        if "any" in claim["support"]:
            claim["support"] = {"all": claim["support"]["any"]}
    variants = dict(evidencecache=measured, whole_corpus_ttl=whole, flat_per_source_ttl=flat,
                    without_fact_checks={k: s.valid for k, s in Snapshot(Manifest.from_dict(no_conflicts), AS_OF).answers.items()},
                    without_alternative_support={k: s.valid for k, s in Snapshot(Manifest.from_dict(no_or), AS_OF).answers.items()})
    rows = []
    for name, prediction in variants.items():
        rows.append(dict(policy=name, valid=sum(prediction.values()), blocked=len(prediction) - sum(prediction.values()),
                         unnecessary_invalidations=sum(expected[k] and not prediction[k] for k in prediction),
                         unsafe_reuses=sum(not expected[k] and prediction[k] for k in prediction)))
    event = dict(kind="publish", source="g0000-status", version=dict(id="v2", observed_at=AS_OF, ttl_seconds=172800,
                  facts=data["sources"][2]["versions"][0]["facts"]))
    after = Snapshot(apply_event(manifest, event), AS_OF)
    impact = compare(snap, after)
    return dict(schema_version=1, fixture="synthetic repeated EU support policies; labels encoded independently by scenario",
                groups=groups, sources=len(manifest.sources), answers=len(manifest.answers), as_of=AS_OF,
                results=rows, single_source_replacement=impact,
                claims="Policy decisions only. No measured latency, money saved, production accuracy or competitor runtime.")
