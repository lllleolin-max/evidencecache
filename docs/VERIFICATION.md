# Reproduction evidence

Observed locally on 2026-10-03: Windows, Python 3.14.3. Core release behavior is at `02832c11cc8fe68e0dba542a32e88668f65c09b7`; subsequent metadata/documentation and workflow-check additions do not change the decision engine. The final release commit is obtained with `git rev-parse HEAD`; independent review and remote CI status must be recorded separately at that final SHA.

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

Observed: wheel build/install succeeded; `pip check` returned `No broken requirements found.`; **39 tests passed**, including 60 independently enumerated random DAG instances, exact TTL and UTC-offset boundaries, revocation/replacement, uncited fact conflicts, input errors, isolated snapshots, query scoping and bounded frontier failure. Import path was `.venv/Lib/site-packages/evidencecache/__init__.py`; installed metadata reported `License-Expression: MIT` and `License-File: LICENSE`. The installed console entry point returned help with all eight commands.

On Ubuntu/macOS use `python3 -m venv .venv`, then `.venv/bin/python` and `.venv/bin/evidencecache`. Ubuntu and Python 3.11 are configured in `.github/workflows/ci.yml`; **remote CI has not been run or certified by this local verification**.

The complete workflow reports manifest fingerprint `d58b3a1b3635b2c057c96ff6ca069f33a8098a3fc630b8c33238c18ec986db74`, 5 sources, 3 claims and 3 answers. At `2026-01-02T00:00:00Z`, `alternative` and `steady` are valid, `conflict` is blocked, the retained witness is `g0000-mirror/v1`, and one conditional fact-resolution task is required. Publishing a replacement of status evidence invalidates **only `g0000-steady`**. An explicitly reviewed rebind plus revocation of the synthetic erroneous assertion restores all three answers in the SDK example. Duplicate event JSON returns exit 2 while preserving input and existing output bytes; planning exhaustion returns exit 3 and `exact: false` without partial plans.

The executable `python -m evidencecache benchmark --groups 100` is exercised by the workflow verifier. This uses **disclosed synthetic labels** and version-aware policy baselines; it does not measure production accuracy or execute Ragas/dbt:

| Policy | Valid / blocked | Unnecessary invalidations | Unsafe reuses under fixture labels |
|---|---:|---:|---:|
| evidencecache | 200 / 100 | 0 | 0 |
| Whole-corpus TTL | 0 / 300 | 200 | 0 |
| Flat per-source TTL | 100 / 200 | 100 | 100 |
| Without fact checks | 300 / 0 | 0 | 100 |
| Without alternative support | 100 / 200 | 100 | 0 |

The three review corrections are independently replayable without changing checkout files:

```sh
python tools/review_history.py --revision 5f80a13 --probe ingress
python tools/review_history.py --revision 45c08c3 --probe ingress
python tools/review_history.py --revision 45c08c3 --probe isolation
python tools/review_history.py --revision 4b8db95 --probe isolation
python tools/review_history.py --revision 4b8db95 --probe planning
python tools/review_history.py --revision 02832c1 --probe planning
```

The runner archives a trusted local Git revision into a temporary directory and imports its source. It observes corrected/uncorrected behavior, not self-awarded scores. Detailed before/after outputs, correction SHAs and limits are in `ITERATIONS.md`. No customers, adoption, revenue, production safety, competitor superiority or exclusive algorithm novelty are inferred from these runs.
