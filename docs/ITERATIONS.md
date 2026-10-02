# Review → correction → verification log

This log records builder self-review at exact commits. It is not an independent score or adoption claim. Environment: Windows, Python 3.14.3 (`py -3`). Ubuntu/Python 3.11 support is configured in CI and is not claimed remotely verified here.

Initial implementation: immutable v1 manifest, temporal/source lifecycle evaluation, structured conflicts, AND/OR DAG, exact bounded repair/witness antichains, CLI, SDK, synthetic policy benchmark and 26 passing tests. Subsequent entries record actual review findings and substantive corrections after this baseline.

## Round 1 — reject ambiguous time and malformed event ingress

Before: `5f80a13ba8be0a82b41cc31c97954fd49076fc70`.
Correction: `45c08c3e5974bd7d2d80718fca9f7c6bfd3f04b1`.

The prior builder's recorded correction was independently reconstructed on 2026-10-03 using Git archives, without checking out or rewriting history. `python tools/review_history.py --revision 5f80a13 --probe ingress` observes `+00:60` accepted and normalized to `2026-01-01 23:00:00+00:00`, unknown `-00:00` treated as UTC, and a list-valued event source raising uncaught `TypeError`. At `45c08c3`, the identical probe returns `ManifestError` for all three cases. The actual diff also adds duplicate-key event decoding, surrogate/mixed-key rejection and validation before reading a published version's fields.

Verification at the correction: `py -3 -m pip install -e .` succeeded; `py -3 -m unittest discover -s tests -v` ran **30 tests, OK** (26 baseline + 4 ingress tests, observed 0.640 s). Test cases cover malformed event nonmutation and preservation of an existing output on invalid duplicate-key JSON. This is a genuine ingress correction, not a counted packaging/documentation round. Known boundary: timestamps remain an explicit supported RFC3339 subset (no leap seconds); no bitemporal ingestion log is inferred.

## Round 2 — isolate snapshots from caller report annotations

Before: `45c08c3e5974bd7d2d80718fca9f7c6bfd3f04b1`.
Correction: `4b8db95d7900fe053277417ab9e566667f98e38e`.

Self-review found report/plan records aliasing internal mutable state. `py -3 tools/review_history.py --revision 45c08c3 --probe isolation` prints `later_evidence_status: FORGED` and `later_task_reason: FORGED` after annotating returned JSON. New regression tests run before correction: 4 tests, 12 assertion failures across 3 tests (9 mapping-mutation subtests, nested state mutability and two detached-export checks); manifest detachment was already correct. The pre-change test originals were serialized copies, avoiding a shared-reference false pass.

The correction freezes Snapshot attributes, recursively exposes read-only mappings/tuples, and returns fresh ordinary JSON structures for report/task exports. It includes deep provenance/fact-key isolation, not only a shallow dictionary copy. It preserves the immutable manifest and existing SDK read access. `py -3 -m unittest discover -s tests -v` ran **34 tests, OK** (observed 0.635 s); `git diff --check` passed. Boundary: Python's deliberate reflection can bypass normal object immutability; this is protection against ordinary SDK mutation, not a hostile-process sandbox.

At the committed correction, `py -3 tools/review_history.py --revision 4b8db95 --probe isolation` prints `later_evidence_status: FRESH`, `later_task_reason: CONFLICT`; original snapshot decisions remain intact after returned report annotations.

## Round 3 — keep selected-answer planning independent of unrelated frontiers

Before: `4b8db95d7900fe053277417ab9e566667f98e38e`.
After SHA is recorded once committed in the next log update.

Self-review found `_plan` enumerating all claims, even ones not referenced by the requested answer. The one-citation answer in `tools/review_history.py --revision 4b8db95 --probe planning` is beside an unrelated conjunction of 12 disjoint pairs (4096 minimal sets). Both expired-source repair planning and fresh-source witness planning raise `PlanningLimitError` at `max_work=100`. Five new regression tests run before correction: **4 errors, 1 pass**; the errors include a transitive diamond query and low-budget conflict query besides the two unrelated exponential cases.

The correction iteratively discovers the answer's transitive claim cone and computes only those frontiers in the existing topological order. Full snapshot evaluation and uncited structured-fact conflict detection remain global. Tests also request the genuinely expensive answer and require explicit `PlanningLimitError`, so the correction does not silently suppress legitimate frontier complexity. `py -3 -m unittest discover -s tests -v` ran **39 tests, OK** (observed 0.611 s), including the 60-seed independent exhaustive Boolean oracle; `git diff --check` passed. Boundary: relevant frontiers can still be exponential; candidate counting is not a hard CPU or memory deadline.
