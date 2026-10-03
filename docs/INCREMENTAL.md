# In-memory SDK updates

`SnapshotCache(manifest, as_of, *, trust_domain)` starts with the complete
`Snapshot` evaluation, then indexes direct source users, claim successors, answer
users, every declared claim's global fact key and all observation/expiry/revocation
instants. `snapshot` and `trust_domain` are read-only public properties.

- `advance(as_of, *, trust_domain)` crosses time boundaries in either direction.
- `apply_event(event, *, trust_domain, as_of=None)` uses the existing complete
  event validation; omitted time retains the current instant.
- `update(manifest, as_of, *, trust_domain)` accepts a new validated `Manifest`.
  Newly added, removed or edited sources participate in global fact checks.

An update reevaluates every version of each changed source or source with a
crossed time boundary. It replaces that source's fresh fact contributions, then
checks all fact-bearing claims for affected keys, including users outside its
direct citation cone. Direct source users and version-rebound claims are evaluated
in topological order. A changed claim state schedules its successors and answers.
Unchanged `State` objects and lifecycle rows are reused. Updated provenance and
version bindings are used by subsequent plans even if a validity state stays equal.
The candidate is committed only after evaluation succeeds; invalid events, times
and mismatched domain labels leave the old snapshot available.

Claim IDs, text, facts and dependency-expression shape must remain equal for
indexed updates; evidence version changes within that shape support reviewed
rebinds. Other graph/claim-definition edits build a full replacement and rebuild
indexes. This fallback preserves the existing complete manifest semantics. The
v1 wire formats are unchanged. Full `Snapshot` and all CLI operations retain
complete evaluation, and repair/witness antichains are recomputed per query with
the original candidate budget. Exhaustion still raises `PlanningLimitError`;
it never certifies a partial frontier as exact.

## Cost scope and measured contrast

`snapshot.work` counts actual source/version lifecycle evaluations, fact-claim
checks and claim/answer state evaluations. Incremental results also count source
and claim definition comparisons, crossed boundary entries, rebuilt boundary
entries and entries shallow-copied from the old snapshot's state mappings. These
are descriptive counters, not an exhaustive instruction count or a CPU deadline.
The latter mapping count excludes newly built definition/index maps. No values
are added to `report`, `plan` or `witnesses` JSON.

Ingress validation, source/claim comparisons and shallow dictionary copies remain
linear in the manifest/state size. A source change rebuilds the sorted temporal
calendar. Large shared fact keys still cost the number of affected claims times
their current fact assertions. The first cache snapshot allocates indexes in
addition to a full evaluation. Neither total update work nor memory is constant,
and relevant frontier enumeration can still be exponential. No persisted cache,
eviction policy, scheduler or multi-writer coordination is provided.

`python tools/benchmark_incremental.py` measures 1, 3 and 300 independent synthetic
answer branches, with one source publish. It reports seven timing samples per
case, Python-allocation peaks and lifetime process peak RSS. Update timing excludes
initial cache preparation; initial costs are reported separately. Both cache
update timings include comparisons, mapping copies and index maintenance. The
validated-event timing additionally includes `apply_event`'s full validation.
Planning, exports and input acquisition are outside these timing scopes.

Observed Windows/Python 3.14 ordinary-wheel results at `2d2652449bd0bdb8bd99c50a1fd2beb10d02771f`:

| Branches | Initial full / cache (ms) | Updated full / cache evaluation (ms) | Validated event full / cache (ms) |
|---|---:|---:|---:|
| 1 | 0.019 / 0.026 | 0.032 / 0.072 | 0.158 / 0.210 |
| 3 | 0.040 / 0.050 | 0.052 / 0.076 | 0.313 / 0.329 |
| 300 | 2.930 / 3.420 | 3.068 / 0.776 | 20.897 / 18.502 |

These are local synthetic medians, not production promises. Small inputs are
slower with a cache, and initial indexing costs more. The 300-branch update
evaluates 1 source/2 versions/1 claim/1 answer instead of 300/301/300/300, while
still comparing 300 source and claim definitions, rebuilding 602 boundaries and
shallow-copying 1500 old state-map entries. A graph edit or a widely shared fact
change can require substantially more work. Choose the full path for one-off or
small manifests and measure your own repeated-update workload.

## Verification and trust

Tests compare 100 fixed-seed sequences of 8 event/time steps with full snapshots:
lifecycle, global facts, blocker provenance, every state, report, plan and witness,
including candidate-budget failures. Targeted tests cover uncited new sources,
removal, exact temporal boundaries in both directions, zero TTL, supersession,
revocation, reviewed rebind, failed update isolation, ordinary input/export
mutation and a 300-branch reuse count. Existing independent exhaustive DAG and
shared-task tests remain unchanged. Differential equality is a check against the
full implementation, not independent proof that declared facts are true.

Keep one authenticated, curated trust domain per cache/manifest. The required
label only guards accidental mixing; origin authentication and source coverage
remain the caller's responsibility. Use `Manifest.from_dict`, `load` or `loads`
for ingress. Immutable snapshots can be retained by readers, but updates are
single-writer and do not provide thread/process locking or a hostile-code sandbox.
