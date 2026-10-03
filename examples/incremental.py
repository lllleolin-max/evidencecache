"""Offline memory-cache integration; all facts are synthetic declared assertions."""
import json

from evidencecache import Manifest, Snapshot, SnapshotCache
from evidencecache.fixtures import AS_OF, fixture

DOMAIN = "synthetic-support-policy"
data = fixture()
cache = SnapshotCache(Manifest.from_dict(data), AS_OF, trust_domain=DOMAIN)
before = cache.snapshot
source = next(source for source in data["sources"] if source["id"] == "g0000-status")
event = dict(kind="publish", source=source["id"], version=dict(id="v2", observed_at=AS_OF,
    ttl_seconds=86400, facts=source["versions"][0]["facts"]))
blocked = cache.apply_event(event, trust_domain=DOMAIN)
assert before.answers["g0000-steady"].valid and not blocked.answers["g0000-steady"].valid
event["version"].update(id="v3", observed_at="2026-01-02T01:00:00Z")
event["rebind_from"] = "v1"
reviewed = cache.apply_event(event, as_of="2026-01-02T01:00:00Z", trust_domain=DOMAIN)
assert reviewed.answers["g0000-steady"].valid
later = cache.advance("2026-01-03T01:00:00Z", trust_domain=DOMAIN)
assert not later.answers["g0000-steady"].valid
for snapshot in (blocked, reviewed, later):
    full = Snapshot(snapshot.manifest, snapshot.as_of.isoformat())
    assert snapshot.report() == full.report()
    assert snapshot.plan("g0000-steady") == full.plan("g0000-steady")
    assert snapshot.witnesses("g0000-steady") == full.witnesses("g0000-steady")
print(json.dumps(dict(trust_domain=DOMAIN, before_valid=True, publish_valid=False,
    reviewed_valid=True, exact_expiry_valid=False, full_equivalence=True,
    publish_work=dict(blocked.work), reviewed_work=dict(reviewed.work), expiry_work=dict(later.work)), indent=2))
