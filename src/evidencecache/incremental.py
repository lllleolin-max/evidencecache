"""In-memory evaluation reuse within one caller-declared trust domain.

Validation, immutable map copies and index maintenance still have linear costs.
Only lifecycle and state evaluation are restricted to affected dependencies.
"""
from __future__ import annotations

from bisect import bisect_right
from heapq import heappop, heappush
from types import MappingProxyType

from .engine import Snapshot, State, _freeze
from .events import apply_event
from .model import Evidence, Manifest, ManifestError, canonical, iso, timestamp


def _shape(claim):
    """Version rebinds keep dependencies; other definition edits use full evaluation."""
    def expr(node):
        if node.op == "evidence":
            return (node.op, node.evidence.source)
        if node.op == "claim":
            return (node.op, node.claim)
        return (node.op, tuple(expr(child) for child in node.children))
    return claim.id, claim.text, claim.fact, expr(claim.support)


class SnapshotCache:
    """Single-writer, process-local cache of immutable SDK snapshots.

    Pass the same explicit trust_domain on every operation. The label prevents
    accidental cache reuse; it does not authenticate a manifest or its publisher.
    Use validated Manifest objects. Returned snapshots remain independent of
    later updates. CLI, persistence and frontier enumeration are unchanged.
    """

    def __init__(self, manifest: Manifest, as_of: str, *, trust_domain: str):
        if type(trust_domain) is not str or not trust_domain.strip() or len(trust_domain) > 256:
            raise ManifestError("trust_domain must be a nonempty string of at most 256 characters")
        self._trust_domain = trust_domain
        self._snapshot = Snapshot(manifest, as_of)
        self._index()

    @property
    def trust_domain(self):
        return self._trust_domain

    @property
    def snapshot(self):
        return self._snapshot

    def _domain(self, value):
        if type(value) is not str or value != self._trust_domain:
            raise ManifestError("snapshot cache trust_domain mismatch")

    def _index(self):
        snap = self._snapshot
        self._sources = {source.id: source for source in snap.manifest.sources}
        self._direct, self._followers, self._answer_users, self._fact_users = {}, {}, {}, {}
        for claim in snap.manifest.claims:
            for leaf in claim.support.leaves():
                target = self._direct if leaf.op == "evidence" else self._followers
                key = leaf.evidence.source if leaf.op == "evidence" else leaf.claim
                target.setdefault(key, set()).add(claim.id)
            if claim.fact:
                self._fact_users.setdefault(claim.fact.key, set()).add(claim.id)
        for answer in snap.manifest.answers:
            for leaf in answer.support.leaves():
                self._answer_users.setdefault(leaf.claim, set()).add(answer.id)
        self._rank = {key: i for i, key in enumerate(snap.manifest.order)}
        self._source_facts = {}
        self._key_sources = {}
        for key, rows in snap.facts.items():
            for row in rows:
                self._source_facts.setdefault(row["source"], {}).setdefault(key, []).append(row)
                self._key_sources.setdefault(key, set()).add(row["source"])
        self._boundaries = {key: self._times(source) for key, source in self._sources.items()}
        self._calendar = sorted((at, key) for key, times in self._boundaries.items() for at in times)
        self._dates = [at for at, _ in self._calendar]

    @staticmethod
    def _times(source):
        return tuple(at for version in source.versions
                     for at in (version.observed_at, version.expires_at, version.revoked_at) if at is not None)

    def advance(self, as_of: str, *, trust_domain: str):
        """Evaluate crossed observation/expiry/revocation boundaries, in either direction."""
        return self.update(self.snapshot.manifest, as_of, trust_domain=trust_domain)

    def apply_event(self, event: dict, *, trust_domain: str, as_of: str | None = None):
        """Fully validate a publish/revoke event before committing a cache update."""
        self._domain(trust_domain)
        return self.update(apply_event(self.snapshot.manifest, event),
                           iso(self.snapshot.as_of) if as_of is None else as_of,
                           trust_domain=trust_domain)

    def update(self, manifest: Manifest, as_of: str, *, trust_domain: str):
        """Use source indexes, or fall back to full evaluation for graph/claim edits.

        A newly added source participates in global fact-key checks even if no
        claim cites it. Version-only reviewed rebinds preserve graph indexes.
        Validation of a new wire manifest belongs to Manifest.from_dict/loads.
        """
        self._domain(trust_domain)
        instant = timestamp(as_of)
        old = self.snapshot
        claim_models = {claim.id: claim for claim in manifest.claims}
        compatible = (manifest.order == old.manifest.order and manifest.answers == old.manifest.answers
                      and claim_models.keys() == old.claim_by_id.keys()
                      and all(claim == old.claim_by_id[key] or _shape(claim) == _shape(old.claim_by_id[key])
                              for key, claim in claim_models.items()))
        if not compatible:
            # Build a complete candidate first, so failures cannot alter the old cache.
            replacement = SnapshotCache(manifest, as_of, trust_domain=self.trust_domain)
            self.__dict__.update(replacement.__dict__)
            return self.snapshot
        sources = {source.id: source for source in manifest.sources}
        changed = {key for key in sources.keys() | self._sources.keys()
                   if sources.get(key) != self._sources.get(key)}
        lo, hi = sorted((old.as_of, instant))
        first, last = bisect_right(self._dates, lo), bisect_right(self._dates, hi)
        dirty = changed | {key for _, key in self._calendar[first:last]}
        partial = Snapshot(Manifest(tuple(sources[key] for key in sorted(dirty) if key in sources), (), (), ()), as_of)
        work = dict(partial.work, mode="incremental", source_definitions_compared=len(sources.keys() | self._sources.keys()),
                    claim_definitions_compared=len(claim_models), boundary_entries_crossed=last - first,
                    index_boundary_entries_rebuilt=0, map_entries_copied=0)
        def copy(name):
            value = getattr(old, name)
            work["map_entries_copied"] += len(value)
            return dict(value)
        versions, evidence, tasks, facts = (copy(name) for name in ("versions", "evidence", "tasks", "facts"))
        for key in dirty:
            for version in self._sources[key].versions if key in self._sources else ():
                ref = Evidence(key, version.id)
                versions.pop(ref, None)
                evidence.pop(ref, None)
                tasks.pop(Snapshot.refresh_id(ref), None)
        versions.update(partial.versions)
        evidence.update(partial.evidence)
        tasks.update(partial.tasks)
        source_facts, key_sources = dict(self._source_facts), dict(self._key_sources)
        affected_keys = set()
        for key in dirty:
            for fact_key in source_facts.pop(key, {}):
                affected_keys.add(fact_key)
                key_sources[fact_key] = key_sources[fact_key] - {key}
        for fact_key, rows in partial.facts.items():
            affected_keys.add(fact_key)
            for row in rows:
                key = row["source"]
                source_facts.setdefault(key, {}).setdefault(fact_key, []).append(row)
                key_sources[fact_key] = key_sources.get(fact_key, set()) | {key}
        for key in affected_keys:
            rows = tuple(row for source in sorted(key_sources.get(key, ())) for row in source_facts[source][key])
            if rows:
                facts[key] = rows
            else:
                facts.pop(key, None)
                key_sources.pop(key, None)
        blockers = copy("fact_blockers")
        pending = set()
        for key in affected_keys:
            rows = facts.get(key, ())
            values = {row["value_json"] for row in rows}
            task_id = "resolve:" + canonical(list(key))
            tasks.pop(task_id, None)
            for claim_id in self._fact_users.get(key, ()):
                work["fact_claims_evaluated"] += 1
                claim = claim_models[claim_id]
                blockers.pop(claim_id, None)
                pending.add(claim_id)
                if len(values) > 1 or (values and claim.fact.value_json not in values):
                    blockers[claim_id] = task_id
                    tasks[task_id] = _freeze(dict(id=task_id, kind="resolve_fact",
                        reason="CONFLICT" if len(values) > 1 else "CONTRADICTED", fact_key=list(key),
                        provenance=[{k: v for k, v in row.items() if k != "value_json"} for row in rows],
                        instruction="Reconcile authoritative values; revoke/correct bad evidence or regenerate claims, then evaluate again."))
        for key in dirty:
            pending.update(self._direct.get(key, ()))
        pending.update(key for key, claim in claim_models.items() if claim != old.claim_by_id[key])
        claims, answers = copy("claims"), copy("answers")
        result = object.__new__(Snapshot)
        for name, value in dict(manifest=manifest, as_of=instant, evidence=evidence, claims=claims).items():
            object.__setattr__(result, name, value)
        queue = []
        for key in pending:
            heappush(queue, (self._rank[key], key))
        answer_users = set()
        while queue:
            _, key = heappop(queue)
            pending.remove(key)
            work["claims_evaluated"] += 1
            state = result._state(claim_models[key].support)
            if key in blockers:
                state = State(False, state.blockers | {blockers[key]})
            if state != claims[key]:
                claims[key] = state
                answer_users.update(self._answer_users.get(key, ()))
                for child in self._followers.get(key, ()):
                    if child not in pending:
                        pending.add(child)
                        heappush(queue, (self._rank[child], child))
        for key in answer_users:
            work["answers_evaluated"] += 1
            answers[key] = result._state(old.answer_by_id[key].support)
        for name, value in dict(versions=versions, evidence=evidence, facts=facts, tasks=tasks,
                                claims=claims, answers=answers, fact_blockers=blockers,
                                claim_by_id=claim_models, answer_by_id=old.answer_by_id).items():
            object.__setattr__(result, name, value if isinstance(value, MappingProxyType) else MappingProxyType(value))
        boundaries = self._boundaries
        calendar, dates = self._calendar, self._dates
        if changed:
            boundaries = dict(boundaries)
            for key in changed:
                if key in sources:
                    boundaries[key] = self._times(sources[key])
                else:
                    boundaries.pop(key, None)
            calendar = sorted((at, key) for key, times in boundaries.items() for at in times)
            dates = [at for at, _ in calendar]
            work["index_boundary_entries_rebuilt"] = len(calendar)
        object.__setattr__(result, "work", _freeze(work))
        self._sources, self._source_facts, self._key_sources = sources, source_facts, key_sources
        self._boundaries, self._calendar, self._dates = boundaries, calendar, dates
        self._snapshot = result
        return result
