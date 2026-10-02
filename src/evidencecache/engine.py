"""Snapshot evaluation and exact bounded monotone repair-frontier enumeration."""
from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from itertools import product
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .model import Answer, Claim, Evidence, Expr, Manifest, ManifestError, Version, canonical, iso, timestamp


class PlanningLimitError(ValueError):
    """Exact planning exceeded a work bound. No partial result is certified."""


@dataclass(frozen=True)
class State:
    valid: bool
    blockers: frozenset[str]


def _freeze(value: Any) -> Any:
    """Detach mutable records and expose recursively read-only snapshot state."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Fresh JSON-compatible exports; callers may annotate their own reports."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, init=False, eq=False)
class Snapshot:
    """Evaluate one immutable manifest at an explicit aware RFC3339 instant.

    A valid answer is supported under declared graph and structured-fact semantics,
    not certified true in the world. Source URIs are inert provenance strings.
    """

    manifest: Manifest
    as_of: datetime
    versions: Mapping[Evidence, Version]
    evidence: Mapping[Evidence, Mapping[str, Any]]
    facts: Mapping[tuple[str, str, str], tuple[Mapping[str, Any], ...]]
    tasks: Mapping[str, Mapping[str, Any]]
    claims: Mapping[str, State]
    answers: Mapping[str, State]
    claim_by_id: Mapping[str, Claim]
    answer_by_id: Mapping[str, Answer]
    fact_blockers: Mapping[str, str]

    def __init__(self, manifest: Manifest, as_of: str):
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "as_of", timestamp(as_of))
        object.__setattr__(self, "versions", {Evidence(s.id, v.id): v for s in manifest.sources for v in s.versions})
        object.__setattr__(self, "evidence", {})
        object.__setattr__(self, "facts", {})
        object.__setattr__(self, "tasks", {})
        object.__setattr__(self, "claims", {})
        object.__setattr__(self, "answers", {})
        object.__setattr__(self, "claim_by_id", {c.id: c for c in manifest.claims})
        object.__setattr__(self, "answer_by_id", {a.id: a for a in manifest.answers})
        for source in manifest.sources:
            known = [v for v in source.versions if v.observed_at <= self.as_of]
            current = known[-1] if known else None
            for version in source.versions:
                ref = Evidence(source.id, version.id)
                if version.observed_at > self.as_of:
                    status = "NOT_YET_OBSERVED"
                elif version.revoked_at and version.revoked_at <= self.as_of:
                    status = "REVOKED"
                elif current.id != version.id:
                    status = "SUPERSEDED"
                elif self.as_of >= version.expires_at:
                    status = "EXPIRED"
                else:
                    status = "FRESH"
                self.evidence[ref] = dict(**ref.to_dict(), status=status, uri=source.uri,
                                          observed_at=iso(version.observed_at), expires_at=iso(version.expires_at),
                                          current_version=current.id if current else None)
                if status == "FRESH":
                    for f in version.facts:
                        self.facts.setdefault(f.key, []).append(dict(**ref.to_dict(), uri=source.uri,
                                                                    value=f.to_dict()["value"], value_json=f.value_json))
                else:
                    task_id = self.refresh_id(ref)
                    self.tasks[task_id] = dict(id=task_id, kind="revalidate_evidence" if status == "EXPIRED" else "replace_evidence",
                                                **ref.to_dict(), reason=status,
                                                instruction="Fetch/verify current evidence, record a new version, and review/rebind affected claims.")
        object.__setattr__(self, "fact_blockers", {})
        for claim in manifest.claims:
            if claim.fact is None:
                continue
            entries = self.facts.get(claim.fact.key, [])
            values = {e["value_json"] for e in entries}
            if len(values) > 1 or (values and claim.fact.value_json not in values):
                kind = "CONFLICT" if len(values) > 1 else "CONTRADICTED"
                task_id = "resolve:" + canonical(list(claim.fact.key))
                self.tasks[task_id] = dict(id=task_id, kind="resolve_fact", reason=kind,
                                           fact_key=list(claim.fact.key),
                                           provenance=[{k: v for k, v in e.items() if k != "value_json"} for e in entries],
                                           instruction="Reconcile authoritative values; revoke/correct bad evidence or regenerate claims, then evaluate again.")
                self.fact_blockers[claim.id] = task_id
        for claim_id in manifest.order:
            claim = self.claim_by_id[claim_id]
            state = self._state(claim.support)
            if claim_id in self.fact_blockers:
                state = State(False, state.blockers | {self.fact_blockers[claim_id]})
            self.claims[claim_id] = state
        for answer in manifest.answers:
            self.answers[answer.id] = self._state(answer.support)
        for name in ("versions", "evidence", "facts", "tasks", "claims", "answers",
                     "claim_by_id", "answer_by_id", "fact_blockers"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    @staticmethod
    def refresh_id(ref: Evidence) -> str:
        return "refresh:" + canonical([ref.source, ref.version])

    def _state(self, expr: Expr) -> State:
        if expr.op == "evidence":
            valid = self.evidence[expr.evidence]["status"] == "FRESH"
            return State(valid, frozenset() if valid else frozenset({self.refresh_id(expr.evidence)}))
        if expr.op == "claim":
            return self.claims[expr.claim]
        states = [self._state(x) for x in expr.children]
        valid = all(x.valid for x in states) if expr.op == "all" else any(x.valid for x in states)
        return State(valid, frozenset() if valid else frozenset().union(*(x.blockers for x in states)))

    def report(self, answer: str | None = None) -> dict:
        if answer is not None and answer not in self.answers:
            raise ManifestError(f"unknown answer {answer!r}")
        selected = sorted(self.answers) if answer is None else [answer]
        def item(key: str, state: State) -> dict:
            return dict(id=key, status="VALID" if state.valid else "BLOCKED", blockers=sorted(state.blockers))
        return dict(schema_version=1, manifest_sha256=self.manifest.fingerprint, as_of=iso(self.as_of),
                    answers=[item(k, self.answers[k]) for k in selected],
                    claims=[item(k, self.claims[k]) for k in sorted(self.claims)],
                    evidence=[_thaw(self.evidence[k]) for k in sorted(self.evidence)],
                    tasks=[_thaw(self.tasks[k]) for k in sorted(self.tasks)])

    def _frontier(self, expr: Expr, claim_frontiers: dict, budget: _Budget,
                  *, witnesses: bool) -> list[frozenset[str]]:
        if expr.op == "claim":
            return claim_frontiers[expr.claim]
        if expr.op == "evidence":
            ref = expr.evidence
            fresh = self.evidence[ref]["status"] == "FRESH"
            if witnesses:
                return [frozenset({canonical([ref.source, ref.version])})] if fresh else []
            return [frozenset()] if fresh else [frozenset({self.refresh_id(ref)})]
        children = [self._frontier(child, claim_frontiers, budget, witnesses=witnesses) for child in expr.children]
        if expr.op == "any":
            return budget.minimal(x for child in children for x in child)
        result = [frozenset()]
        for child in children:
            result = budget.minimal(a | b for a, b in product(result, child))
        return result

    def _plan(self, answer: str, max_work: int, *, witnesses: bool) -> tuple[list[frozenset[str]], int]:
        if answer not in self.answers:
            raise ManifestError(f"unknown answer {answer!r}")
        if type(max_work) is not int or max_work < 1:
            raise ManifestError("max_work must be a positive integer")
        budget = _Budget(max_work)
        # Snapshot conflict detection is global, but conditional frontier
        # enumeration only needs the selected answer's transitive claim cone.
        # An unrelated exponential formula must not consume this query budget.
        required = {leaf.claim for leaf in self.answer_by_id[answer].support.leaves()}
        pending = list(required)
        while pending:
            claim_id = pending.pop()
            for leaf in self.claim_by_id[claim_id].support.leaves():
                if leaf.op == "claim" and leaf.claim not in required:
                    required.add(leaf.claim)
                    pending.append(leaf.claim)
        frontiers = {}
        for claim_id in self.manifest.order:
            if claim_id not in required:
                continue
            plans = self._frontier(self.claim_by_id[claim_id].support, frontiers, budget, witnesses=witnesses)
            blocker = self.fact_blockers.get(claim_id)
            if blocker:
                plans = [] if witnesses else [p | {blocker} for p in plans]
            frontiers[claim_id] = plans
        plans = self._frontier(self.answer_by_id[answer].support, frontiers, budget, witnesses=witnesses)
        return sorted(plans, key=lambda p: (len(p), sorted(p))), budget.used

    def plan(self, answer: str, max_work: int = 100_000) -> dict:
        """All subset-minimal conditional obligation sets, cheapest cardinality first.

        Shared tasks count once; locally cheapest alternatives are not discarded.
        An action is an obligation, not permission to mark evidence fresh blindly.
        """
        plans, work = self._plan(answer, max_work, witnesses=False)
        return dict(answer=answer, as_of=iso(self.as_of), manifest_sha256=self.manifest.fingerprint,
                    status="VALID" if self.answers[answer].valid else "BLOCKED",
                    exact=True, candidates_examined=work,
                    minimum_task_count=len(plans[0]) if plans else None,
                    plans=[dict(task_ids=sorted(p), tasks=[_thaw(self.tasks[t]) for t in sorted(p)]) for p in plans],
                    semantics="Conditional minimal obligations; execution can reveal changed facts. Re-evaluation is mandatory.")

    def witnesses(self, answer: str, max_work: int = 100_000) -> dict:
        plans, work = self._plan(answer, max_work, witnesses=True)
        return dict(answer=answer, as_of=iso(self.as_of), exact=True, candidates_examined=work,
                    witnesses=[[dict(zip(("source", "version"), __import__("json").loads(ref))) for ref in sorted(p)] for p in plans])


class _Budget:
    def __init__(self, maximum: int):
        self.maximum, self.used = maximum, 0

    def minimal(self, candidates) -> list[frozenset[str]]:
        result = []
        for candidate in candidates:
            self.used += 1
            if self.used > self.maximum:
                raise PlanningLimitError(f"exact frontier exceeds max_work={self.maximum}; simplify graph or increase bound")
            if any(existing <= candidate for existing in result):
                continue
            result = [existing for existing in result if not candidate < existing]
            result.append(candidate)
        return result


def compare(before: Snapshot, after: Snapshot) -> dict:
    """Exact observed answer invalidation, not merely the transitive dependency cone."""
    old, new = before.answers, after.answers
    common = old.keys() & new.keys()
    invalidated = sorted(k for k in common if old[k].valid and not new[k].valid)
    newly_valid = sorted(k for k in common if not old[k].valid and new[k].valid)
    changed_evidence = sorted(k for k in before.evidence.keys() | after.evidence.keys()
                              if before.evidence.get(k) != after.evidence.get(k)
                              or before.versions.get(k) != after.versions.get(k))
    return dict(before_sha256=before.manifest.fingerprint, after_sha256=after.manifest.fingerprint,
                before_as_of=iso(before.as_of), after_as_of=iso(after.as_of),
                invalidated_answers=invalidated, newly_valid_answers=newly_valid,
                added_answers=sorted(new.keys() - old.keys()), removed_answers=sorted(old.keys() - new.keys()),
                still_valid_answers=sorted(k for k in common if old[k].valid and new[k].valid),
                still_blocked_answers=sorted(k for k in common if not old[k].valid and not new[k].valid),
                changed_evidence=[ref.to_dict() for ref in changed_evidence])
