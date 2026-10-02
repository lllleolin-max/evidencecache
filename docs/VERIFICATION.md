# Reproduction evidence

Observed locally on 2026-10-03: Windows, Python 3.14.3, package **0.1.1**. Core corrected behavior is at `efa06521d41617da3d3cb7ed8e33b10cfca82d56`. The previous candidate `eb58cc7c5951a08747fdb2b2c605daf971c3ba2c` failed independent review because shared fact obligations could produce a nonminimal set with `exact:true`; round 4 in `ITERATIONS.md` documents the actual correction. The final release commit is obtained with `git rev-parse HEAD`; a new independent score and remote CI status must be recorded separately at that final SHA. Successful builder-run probes do not award a passing score.

The package was built and installed as a **noneditable wheel into a fresh venv**, not merely imported from the working source tree:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe examples/workflow.py
.\.venv\Scripts\python.exe tools/verify_workflow.py
.\.venv\Scripts\evidencecache.exe --help
```

Observed: noneditable 0.1.1 wheel build/install succeeded; `pip check` returned `No broken requirements found.`; **47 tests passed**, including 60 lifecycle-only random DAG instances and 100 mixed fact-obligation DAGs with 800 answer queries checked by an exhaustive input-based Boolean solver. Coverage includes exact TTL and UTC-offset boundaries, revocation/replacement, uncited typed conflicts, input errors, isolated snapshots, query scoping, shared-obligation minimality and bounded frontier failure. Import path was `.venv/Lib/site-packages/evidencecache/__init__.py`; installed metadata/version confirmed 0.1.1. SPDX license metadata is unchanged from the previously verified MIT/LICENSE wheel. The console entry point exposes all eight commands.

The builder additionally ran the **unchanged reviewer-owned** `evidencecache_conflict_frontier_probe.py` and `evidencecache_independent_probes.py` against the installed 0.1.1 wheel: the minimal shared-fact case returned only `{R}` with no strict supersets; **6 API probes passed, and all 120 independent truth-table DAG cases matched**. The old wheel had mismatches at seeds 66 and 119. These reviewer-owned scripts live outside this repository and were not edited or incorporated as builder-authored review evidence. Final independent rescoring remains a separate gate.

On Ubuntu/macOS use `python3 -m venv .venv`, then `.venv/bin/python` and `.venv/bin/evidencecache`. Ubuntu and Python 3.11 are configured in `.github/workflows/ci.yml`; **remote CI has not been run or certified by this local verification**.

The complete workflow reports manifest fingerprint `d58b3a1b3635b2c057c96ff6ca069f33a8098a3fc630b8c33238c18ec986db74`, 5 sources, 3 claims and 3 answers. At `2026-01-02T00:00:00Z`, `alternative` and `steady` are valid, `conflict` is blocked, the retained witness is `g0000-mirror/v1`, and one conditional fact-resolution task is required. Publishing a replacement of status evidence invalidates **only `g0000-steady`**. An explicitly reviewed rebind plus revocation of the synthetic erroneous assertion restores all three answers in the SDK example. Duplicate event JSON returns exit 2 while preserving input and existing output bytes; planning exhaustion returns exit 3 and `exact: false` without partial plans. The verifier also executes an installed-CLI nested claim/shared-fact regression and requires exactly one minimal resolution set, rather than a resolution-plus-refresh superset.

The executable `python -m evidencecache benchmark --groups 100` is exercised by the workflow verifier. This uses **disclosed synthetic labels** and version-aware policy baselines; it does not measure production accuracy or execute Ragas/dbt:

| Policy | Valid / blocked | Unnecessary invalidations | Unsafe reuses under fixture labels |
|---|---:|---:|---:|
| evidencecache | 200 / 100 | 0 | 0 |
| Whole-corpus TTL | 0 / 300 | 200 | 0 |
| Flat per-source TTL | 100 / 200 | 100 | 100 |
| Without fact checks | 300 / 0 | 0 | 100 |
| Without alternative support | 100 / 200 | 100 | 0 |

All four review corrections are replayable without changing checkout files:

```sh
python tools/review_history.py --revision 5f80a13 --probe ingress
python tools/review_history.py --revision 45c08c3 --probe ingress
python tools/review_history.py --revision 45c08c3 --probe isolation
python tools/review_history.py --revision 4b8db95 --probe isolation
python tools/review_history.py --revision 4b8db95 --probe planning
python tools/review_history.py --revision 02832c1 --probe planning
python tools/review_history.py --revision eb58cc7 --probe fact_frontier
python tools/review_history.py --revision efa0652 --probe fact_frontier
```

The runner archives a trusted local Git revision into a temporary directory and imports its source. It observes corrected/uncorrected behavior, not self-awarded scores. Detailed before/after outputs, correction SHAs and limits are in `ITERATIONS.md`. No customers, adoption, revenue, production safety, competitor superiority or exclusive algorithm novelty are inferred from these runs.
