"""Run from the repository after installation: python examples/workflow.py."""
import json

from evidencecache import Manifest, Snapshot, apply_event, compare
from evidencecache.fixtures import AS_OF, fixture

manifest = Manifest.from_dict(fixture())
before = Snapshot(manifest, AS_OF)
version = dict(id="v2", observed_at=AS_OF, ttl_seconds=86400,
               facts=[dict(subject="g0000:service", predicate="status", scope="global", value="operational")])
event = dict(kind="publish", source="g0000-status", version=version)
changed = apply_event(manifest, event)
impact = compare(before, Snapshot(changed, AS_OF))
assert impact["invalidated_answers"] == ["g0000-steady"]
# A producer checked unchanged structured content before explicitly rebinding.
rebound = apply_event(manifest, dict(event, rebind_from="v1"))
# In this synthetic scenario, billing was confirmed erroneous by the producer.
resolved = apply_event(rebound, dict(kind="revoke", source="g0000-billing", version="v1", at=AS_OF))
after = Snapshot(resolved, AS_OF)
assert all(s.valid for s in after.answers.values())
print(json.dumps(dict(initial=before.report()["answers"], conflict_plan=before.plan("g0000-conflict"),
                      source_update_impact=impact, resolved=after.report()["answers"],
                      preserved_witness=after.witnesses("g0000-alternative")), indent=2))
