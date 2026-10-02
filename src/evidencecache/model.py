"""Validated, immutable manifest model. No network, clocks or model inference."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import re
from typing import Any

MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 10_000
MAX_DEPTH = 64
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z")


class ManifestError(ValueError):
    """An input violates the v1 manifest contract."""


def timestamp(value: Any, path: str = "as_of") -> datetime:
    if not isinstance(value, str) or not TIME.fullmatch(value):
        raise ManifestError(f"{path}: expected RFC3339 timestamp with seconds and explicit offset")
    if value.endswith("-00:00"):
        raise ManifestError(f"{path}: -00:00 denotes an unknown offset; supply a known offset")
    if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ManifestError(f"{path}: offset hours/minutes outside RFC3339 range")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ManifestError(f"{path}: invalid timestamp") from exc


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def obj(value: Any, required: set[str], optional: set[str], path: str) -> dict:
    if not isinstance(value, dict):
        raise ManifestError(f"{path}: expected object")
    if any(not isinstance(key, str) for key in value):
        raise ManifestError(f"{path}: object keys must be strings")
    missing, unknown = required - value.keys(), value.keys() - required - optional
    if missing or unknown:
        raise ManifestError(f"{path}: missing={sorted(missing)} unknown={sorted(unknown)}")
    return value


def seq(value: Any, path: str, *, nonempty: bool = False) -> list:
    if not isinstance(value, list) or len(value) > MAX_ITEMS or (nonempty and not value):
        raise ManifestError(f"{path}: expected {'nonempty ' if nonempty else ''}array with <= {MAX_ITEMS} items")
    return value


def string(value: Any, path: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ManifestError(f"{path}: expected nonempty string with <= {limit} characters")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ManifestError(f"{path}: unpaired Unicode surrogate")
    return value


def identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ManifestError(f"{path}: invalid identifier")
    return value


@dataclass(frozen=True, order=True)
class Fact:
    subject: str
    predicate: str
    scope: str
    value_json: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.subject, self.predicate, self.scope)

    def to_dict(self) -> dict:
        return dict(subject=self.subject, predicate=self.predicate, scope=self.scope,
                    value=json.loads(self.value_json))


def fact(value: Any, path: str) -> Fact:
    d = obj(value, {"subject", "predicate", "scope", "value"}, set(), path)
    v = d["value"]
    # Scalar fact values avoid pretending to implement semantic object comparison.
    if v is not None and type(v) not in (str, bool, int):
        raise ManifestError(f"{path}.value: use null, boolean, integer or string (decimals as strings)")
    if isinstance(v, str) and len(v) > 4096:
        raise ManifestError(f"{path}.value: string too long")
    if isinstance(v, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in v):
        raise ManifestError(f"{path}.value: unpaired Unicode surrogate")
    if type(v) is int and abs(v) > 2**53 - 1:
        raise ManifestError(f"{path}.value: integer outside interoperable JSON range")
    return Fact(*(string(d[k], f"{path}.{k}", 256) for k in ("subject", "predicate", "scope")), canonical(v))


@dataclass(frozen=True, order=True)
class Evidence:
    source: str
    version: str

    def to_dict(self) -> dict:
        return {"source": self.source, "version": self.version}


@dataclass(frozen=True)
class Expr:
    op: str
    children: tuple[Expr, ...] = ()
    evidence: Evidence | None = None
    claim: str | None = None

    def leaves(self) -> tuple[Expr, ...]:
        if self.op in ("evidence", "claim"):
            return (self,)
        return tuple(x for child in self.children for x in child.leaves())

    def to_dict(self) -> dict:
        if self.op == "evidence":
            return {"evidence": self.evidence.to_dict()}
        if self.op == "claim":
            return {"claim": self.claim}
        return {self.op: [child.to_dict() for child in self.children]}


def expression(value: Any, path: str, depth: int = 0) -> Expr:
    if depth > MAX_DEPTH:
        raise ManifestError(f"{path}: expression depth exceeds {MAX_DEPTH}")
    if not isinstance(value, dict) or len(value) != 1:
        raise ManifestError(f"{path}: exactly one of all, any, evidence, claim required")
    op = next(iter(value))
    if op in ("all", "any"):
        return Expr(op, tuple(expression(x, f"{path}.{op}[{i}]", depth + 1)
                              for i, x in enumerate(seq(value[op], path, nonempty=True))))
    if op == "evidence":
        d = obj(value[op], {"source", "version"}, set(), path)
        return Expr(op, evidence=Evidence(identifier(d["source"], path), identifier(d["version"], path)))
    if op == "claim":
        return Expr(op, claim=identifier(value[op], path))
    raise ManifestError(f"{path}: unknown expression operator {op!r}")


@dataclass(frozen=True)
class Version:
    id: str
    observed_at: datetime
    ttl_seconds: int
    facts: tuple[Fact, ...]
    revoked_at: datetime | None = None
    digest: str | None = None

    @property
    def expires_at(self) -> datetime:
        return self.observed_at + timedelta(seconds=self.ttl_seconds)

    def to_dict(self) -> dict:
        d = dict(id=self.id, observed_at=iso(self.observed_at), ttl_seconds=self.ttl_seconds,
                 facts=[f.to_dict() for f in self.facts])
        if self.revoked_at:
            d["revoked_at"] = iso(self.revoked_at)
        if self.digest:
            d["digest"] = self.digest
        return d


@dataclass(frozen=True)
class Source:
    id: str
    uri: str
    versions: tuple[Version, ...]

    def to_dict(self) -> dict:
        return dict(id=self.id, uri=self.uri, versions=[v.to_dict() for v in self.versions])


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    support: Expr
    fact: Fact | None = None

    def to_dict(self) -> dict:
        d = dict(id=self.id, text=self.text, support=self.support.to_dict())
        if self.fact:
            d["fact"] = self.fact.to_dict()
        return d


@dataclass(frozen=True)
class Answer:
    id: str
    text: str
    support: Expr

    def to_dict(self) -> dict:
        return dict(id=self.id, text=self.text, support=self.support.to_dict())


@dataclass(frozen=True)
class Manifest:
    sources: tuple[Source, ...]
    claims: tuple[Claim, ...]
    answers: tuple[Answer, ...]
    order: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any) -> Manifest:
        root = obj(value, {"schema_version", "sources", "claims", "answers"}, set(), "manifest")
        if type(root["schema_version"]) is not int or root["schema_version"] != 1:
            raise ManifestError("schema_version: only integer 1 is supported")
        sources = []
        for i, raw in enumerate(seq(root["sources"], "sources")):
            p = f"sources[{i}]"
            d = obj(raw, {"id", "uri", "versions"}, set(), p)
            versions = []
            for j, raw_v in enumerate(seq(d["versions"], p, nonempty=True)):
                q = f"{p}.versions[{j}]"
                v = obj(raw_v, {"id", "observed_at", "ttl_seconds", "facts"}, {"revoked_at", "digest"}, q)
                ttl = v["ttl_seconds"]
                if type(ttl) is not int or not 0 <= ttl <= 315_576_000:
                    raise ManifestError(f"{q}.ttl_seconds: expected integer in [0, 315576000]")
                observed = timestamp(v["observed_at"], q)
                revoked = timestamp(v["revoked_at"], q) if "revoked_at" in v else None
                if revoked and revoked < observed:
                    raise ManifestError(f"{q}: revocation precedes observation")
                facts = tuple(sorted(fact(f, q) for f in seq(v["facts"], q)))
                if len({f.key for f in facts}) != len(facts):
                    raise ManifestError(f"{q}: duplicate fact key in a version")
                digest = v.get("digest")
                if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
                    raise ManifestError(f"{q}.digest: expected sha256:<64 lowercase hex>")
                version = Version(identifier(v["id"], q), observed, ttl, facts, revoked, digest)
                try:
                    version.expires_at
                except OverflowError as exc:
                    raise ManifestError(f"{q}: expiration outside datetime range") from exc
                versions.append(version)
            if len({v.id for v in versions}) != len(versions) or len({v.observed_at for v in versions}) != len(versions):
                raise ManifestError(f"{p}: duplicate version ID or observation instant")
            sources.append(Source(identifier(d["id"], p), string(d["uri"], p), tuple(sorted(versions, key=lambda v: v.observed_at))))
        claims = []
        for i, raw in enumerate(seq(root["claims"], "claims")):
            p = f"claims[{i}]"
            d = obj(raw, {"id", "text", "support"}, {"fact"}, p)
            claims.append(Claim(identifier(d["id"], p), string(d["text"], p), expression(d["support"], p),
                                fact(d["fact"], p) if "fact" in d else None))
        answers = []
        for i, raw in enumerate(seq(root["answers"], "answers")):
            p = f"answers[{i}]"
            d = obj(raw, {"id", "text", "support"}, set(), p)
            support = expression(d["support"], p)
            if any(x.op != "claim" for x in support.leaves()):
                raise ManifestError(f"{p}: answer expressions must use claim leaves")
            answers.append(Answer(identifier(d["id"], p), string(d["text"], p), support))
        for name, items in (("source", sources), ("claim", claims), ("answer", answers)):
            if len({x.id for x in items}) != len(items):
                raise ManifestError(f"duplicate {name} ID")
        evidence = {Evidence(s.id, v.id): v for s in sources for v in s.versions}
        by_claim = {c.id: c for c in claims}
        deps = {}
        for item in [*claims, *answers]:
            for leaf in item.support.leaves():
                if leaf.op == "evidence" and leaf.evidence not in evidence:
                    raise ManifestError(f"{item.id}: dangling evidence {leaf.evidence}")
                if leaf.op == "claim" and leaf.claim not in by_claim:
                    raise ManifestError(f"{item.id}: dangling claim {leaf.claim}")
                if isinstance(item, Claim) and item.fact and leaf.op == "evidence" and item.fact not in evidence[leaf.evidence].facts:
                    raise ManifestError(f"{item.id}: evidence {leaf.evidence} does not assert the claim fact")
        for claim in claims:
            deps[claim.id] = {x.claim for x in claim.support.leaves() if x.op == "claim"}
        # Kahn's algorithm avoids recursion limits on long claim chains.
        followers = {c.id: [] for c in claims}
        for child, parents in deps.items():
            for parent in parents:
                followers[parent].append(child)
        pending = {key: len(val) for key, val in deps.items()}
        ready = sorted(key for key, degree in pending.items() if degree == 0)
        order = []
        while ready:
            key = ready.pop()
            order.append(key)
            for child in sorted(followers[key]):
                pending[child] -= 1
                if pending[child] == 0:
                    ready.append(child)
        if len(order) != len(claims):
            raise ManifestError("claim dependency cycle: " + ", ".join(sorted(k for k, v in pending.items() if v)[:10]))
        return cls(tuple(sorted(sources, key=lambda s: s.id)), tuple(sorted(claims, key=lambda c: c.id)),
                   tuple(sorted(answers, key=lambda a: a.id)), tuple(order))

    def to_dict(self) -> dict:
        return dict(schema_version=1, sources=[s.to_dict() for s in self.sources],
                    claims=[c.to_dict() for c in self.claims], answers=[a.to_dict() for a in self.answers])

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical(self.to_dict()).encode("utf-8")).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_json(text: str) -> Any:
    """Strict bounded JSON decoding shared by manifests and source events."""
    try:
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise ManifestError(f"JSON document exceeds {MAX_BYTES} bytes")
        return json.loads(text, object_pairs_hook=_pairs,
                          parse_constant=lambda s: (_ for _ in ()).throw(ManifestError(f"invalid JSON constant {s}")))
    except ManifestError:
        raise
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise ManifestError(f"invalid or excessively nested JSON: {exc}") from exc


def loads(text: str) -> Manifest:
    return Manifest.from_dict(parse_json(text))


def read_json(path: str | Path) -> Any:
    with Path(path).open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ManifestError(f"manifest exceeds {MAX_BYTES} bytes")
    try:
        return parse_json(content.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ManifestError("manifest must be UTF-8") from exc


def load(path: str | Path) -> Manifest:
    return Manifest.from_dict(read_json(path))
