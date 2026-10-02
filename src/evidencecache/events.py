"""Pure, validated source version/revocation events for a cache integration."""
from __future__ import annotations

from copy import deepcopy

from .model import Manifest, ManifestError, obj, timestamp


def apply_event(manifest: Manifest, event: dict) -> Manifest:
    """Apply a source event, preserving the input and revalidating the entire DAG.

    publish events optionally rebind one older version after caller validation.
    A changed structured fact fails rebind validation: regenerate claims instead.
    """
    if not isinstance(event, dict) or event.get("kind") not in ("publish", "revoke"):
        raise ManifestError("event.kind must be publish or revoke")
    data = deepcopy(manifest.to_dict())
    sources = {s["id"]: s for s in data["sources"]}
    if event["kind"] == "publish":
        obj(event, {"kind", "source", "version"}, {"rebind_from"}, "event")
    else:
        obj(event, {"kind", "source", "version", "at"}, set(), "event")
    if event["source"] not in sources:
        raise ManifestError(f"unknown event source {event['source']!r}")
    source = sources[event["source"]]
    versions = {v["id"]: v for v in source["versions"]}
    if event["kind"] == "revoke":
        if event["version"] not in versions:
            raise ManifestError("cannot revoke unknown version")
        version = versions[event["version"]]
        if "revoked_at" in version:
            if timestamp(version["revoked_at"]) != timestamp(event["at"]):
                raise ManifestError("revocation is immutable; conflicting revocation instant")
        version["revoked_at"] = event["at"]
    else:
        source["versions"].append(event["version"])
        if "rebind_from" in event:
            if event["rebind_from"] not in versions:
                raise ManifestError("cannot rebind unknown version")
            def rebind(expr):
                if "evidence" in expr:
                    ref = expr["evidence"]
                    if ref["source"] == source["id"] and ref["version"] == event["rebind_from"]:
                        ref["version"] = event["version"]["id"]
                for op in ("all", "any"):
                    for child in expr.get(op, []):
                        rebind(child)
            for claim in data["claims"]:
                rebind(claim["support"])
    return Manifest.from_dict(data)
