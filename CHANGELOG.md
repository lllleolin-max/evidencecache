# Change log

## 0.2.0

- Add the optional process-local `SnapshotCache` SDK. Source dependencies, global
  fact-key users and temporal boundaries restrict lifecycle/state reevaluation.
  Uncited conflicts, reviewed version rebinds and backward time remain supported.
- Reuse immutable unaffected snapshot records. Graph/claim-definition changes
  fall back to full `Snapshot` evaluation; the CLI remains on the full path.
- Expose read-only `snapshot.work` evaluation counts separately from JSON reports.
  Include synthetic evaluation and fully validated event benchmarks, showing
  initial-index cost and slower small-input updates as well as the 300-branch case.
- Preserve the v1 manifest/report formats and bounded exact repair/witness planner.

## 0.1.1

Restore subset minimality after shared fact-resolution obligations. Historical
findings and verification remain in [docs/ITERATIONS.md](docs/ITERATIONS.md).
