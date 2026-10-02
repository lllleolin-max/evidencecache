# Contributing

Create an isolated environment, run `python -m pip install -e .`, then `python -m unittest discover -s tests -v` and `python -m evidencecache benchmark --groups 20`. The runtime is standard-library Python 3.11+. Keep behavior portable on Windows and Ubuntu. Source code is in `src/evidencecache`; tests include an independent exhaustive planner oracle.

For a correctness change, add a minimal failing synthetic fixture/probe and explain the supported invariant it violated. Add the correction and relevant test, documenting format/exit-code changes. Do not silently widen truth/semantic guarantees. Changes to graph planning should be checked against exhaustive small instances as well as a bounded explosion case. New dependencies need a concrete workflow justification.

Please distinguish observed measurements from hypotheses in issues and pull requests. Benchmark baselines must disclose policies and fixtures. Do not use real confidential support policies or logs. All contributions are under the MIT license. There is no support SLA; this is a scoped local engine, not a managed service.
