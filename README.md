# evidencecache

**Know which cached answers still have valid evidence—and what to check next.**

`evidencecache` is a deterministic Python SDK and CLI for knowledge application owners. It evaluates pinned source versions, expiring evidence, structured fact conflicts, and AND/OR claim dependencies. An expired citation does not discard an answer that has a valid alternative. Two fresh sources disagreeing on the same declared fact block reuse and expose their provenance.

No model calls, retrieval service or account is required. Python 3.11+; runtime uses the standard library. MIT licensed. This is an inspectable pilot library, with no claimed production adoption or revenue.

```text
source versions → AND/OR claims → cached answers
       │                 │              │
       └── TTL + active fact conflicts ──┤
                                        ├── valid evidence witnesses
                                        └── minimal conditional refresh tasks
```

## Try the complete workflow

Install from a source checkout with Python 3.11+:

```sh
git clone https://github.com/lllleolin-max/evidencecache.git
cd evidencecache
```

Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m evidencecache demo --output demo.json
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe -m evidencecache demo --output demo.json
```

In the remaining examples, `python` means this environment's interpreter:
`.venv/bin/python` on Linux/macOS or `.venv\Scripts\python.exe` on Windows.
The runtime uses the standard library; source installation may download build
dependencies. No PyPI release is required for these instructions.

Validate the generated local manifest, then evaluate at a fixed snapshot:

```sh
python -m evidencecache validate demo.json
python -m evidencecache evaluate demo.json --as-of 2026-01-02T00:00:00Z
```

`demo` writes `demo.json`; subsequent commands read it and print JSON on stdout.
The three commands exit `0`, including the evaluation that reports a blocked
answer: the default is a report, not a CI rejection. Use `--fail-on-blocked` to
make a blocked answer fail a gate:

```sh
python -m evidencecache evaluate demo.json --as-of 2026-01-02T00:00:00Z --fail-on-blocked
```

This fixture exits `1`. Invalid input exits `2`; an exact-planning work limit
exits `3`. Handled errors are JSON on stderr. Re-running `demo --output demo.json`
replaces that demo file, so choose a separate output path for saved audit snapshots.

Expected decisions in the synthetic EU support-policy fixture:

| Answer | Decision at the explicit snapshot | Why |
|---|---|---|
| `g0000-alternative` | `VALID`, zero refresh tasks | Primary policy expires exactly now; a fresh mirror supports the same fact |
| `g0000-steady` | `VALID` | Independent service-status evidence remains fresh |
| `g0000-conflict` | `BLOCKED`, `resolve_fact` task | Current pricing and billing sources assert different prices in the same scope |

Continue from a decision to its supporting evidence and conditional repair tasks:

```sh
python -m evidencecache witness demo.json --as-of 2026-01-02T00:00:00Z --answer g0000-alternative
python -m evidencecache plan demo.json --as-of 2026-01-02T00:00:00Z --answer g0000-conflict
python examples/workflow.py
```

`examples/workflow.py` executes cache gating → plan → new version → compare → reviewed rebind → re-evaluate, and revokes a demonstrably erroneous fixture assertion to resolve a conflict. Output is JSON. `tools/verify_workflow.py` also runs the installed CLI in subprocesses, checks exit codes and artifact preservation, and verifies all five synthetic policy/ablation results. `examples/publish-status.json` works with:

```sh
python -m evidencecache apply demo.json examples/publish-status.json --output next.json
python -m evidencecache compare demo.json next.json --as-of 2026-01-02T00:00:00Z
```

Only `g0000-steady` becomes invalid. A source replacement never silently rebinds its old citations.

Optional verification and comparison commands:

```sh
python tools/verify_workflow.py
python -m evidencecache benchmark --groups 100
python -m unittest discover -s tests -v
```

## Embed the gate

```python
from evidencecache import Snapshot, load

manifest = load("demo.json")
snapshot = Snapshot(manifest, "2026-01-02T00:00:00Z")
answer_id = "g0000-alternative"
if snapshot.answers[answer_id].valid:
    print(snapshot.witnesses(answer_id))  # minimal supporting version sets
else:
    print(snapshot.plan(answer_id))       # subset-minimal conditional task sets
```

Integrate after retrieval/claim extraction and before cache reuse. The producer declares support and fact scope; the library checks those declarations. It cannot establish text entailment, source trustworthiness, undisclosed disagreements or real-world truth. TTL is an explicit freshness policy, not a probability of correctness. A refresh plan is conditional: obtain evidence, review changed facts, then evaluate again. See [format and API](docs/FORMAT.md).

### Repeated SDK updates in memory

Version 0.2 adds `SnapshotCache` for a single writer in one declared trust domain:

```python
from evidencecache import SnapshotCache, load

cache = SnapshotCache(load("demo.json"), "2026-01-02T00:00:00Z",
                      trust_domain="curated-support-policy")
before = cache.snapshot
after = cache.advance("2026-01-03T00:00:00Z",
                      trust_domain="curated-support-policy")
# before remains an immutable snapshot. Plans and witnesses use after's data.
print(after.report())
```

`cache.apply_event(event, trust_domain=..., as_of=...)` applies a fully validated
publish/revoke event, including reviewed rebinds. `cache.update(manifest, as_of,
trust_domain=...)` accepts a new validated immutable manifest. A new source can
block an answer through a global fact conflict even when no claim cites it.
Observation, revocation and half-open expiry boundaries are reevaluated when time
moves forward or backward. Graph/claim-definition edits use full evaluation.
Run `python examples/incremental.py` for publish, reviewed rebind and exact expiry.

The cache reuses unaffected lifecycle rows and claim/answer states. Validation,
definition comparison, shallow mapping copies and time-index maintenance still
perform linear work; planning is recomputed with the existing exactness budget.
The CLI keeps full `Snapshot` behavior. There is no persisted cache or lock for
multiple writers. The domain label prevents accidental mixing, and does not
authenticate input. Use `Snapshot(manifest, as_of)` for one-off evaluation and as
the complete reference. [Measured costs and limits](docs/INCREMENTAL.md).

## What changes the decision?

`benchmark --groups 100` generates 500 synthetic sources and 300 answers. The independently declared fixture labels identify 200 reusable answers and 100 blocked by known structured conflicts. It runs two deliberately simple, **version-aware** TTL baselines and two mechanism ablations; it does not run Ragas or dbt.

| Policy | Unnecessary invalidations | Unsafe reuses under fixture labels |
|---|---:|---:|
| Whole-corpus TTL gate | 200 | 0 |
| Flat per-source TTL gate | 100 | 100 |
| evidencecache | 0 | 0 |
| Without fact checks | 0 | 100 |
| Without alternative support | 100 | 0 |

These are scenario counts, not production accuracy or speed measurements. The mechanism also handles shared tasks: `(A OR B) AND (B OR C)` has minimal refresh sets `{B}` and `{A,C}`. It keeps both; choosing a locally cheapest branch can lose the global optimum. The test suite checks random DAGs against a separate exhaustive oracle.

Ragas already provides RAG quality metrics; dbt already provides freshness and dependency-aware orchestration. This project combines answer-specific pinned evidence, structured conflicts and minimal conditional repair sets in a small local protocol. That is the demonstrated distinction, with no claim of exclusive novelty. [Primary-source comparison and benchmark methodology](docs/COMPARISON.md) · [Commercial rationale](docs/COMMERCIAL.md).

## Boundaries and reproducibility

- Explicit UTC/offset `as_of`; validity interval `[observed_at, observed_at + ttl)`. Newest observed source version supersedes older versions, even if the new one is expired or revoked.
- Conflicts compare exact `(subject, predicate, scope)` keys and typed scalar values. Decimals/units should be canonical strings. No semantic contradiction detector or source ranking is implied.
- Exact repair sets can grow exponentially. A work limit fails explicitly (exit `3`) rather than returning an incomplete set as minimal. Reports remain available without planning.
- Files are local. The library fetches no URIs and executes no manifest code. Fingerprints identify content, not authenticity. Keep snapshots and apply external access controls.
- GitHub Actions is configured for Ubuntu/Windows with Python 3.11/3.14. Checked-in workflow configuration is not evidence that remote CI has run.

[Architecture](docs/ARCHITECTURE.md) · [Review/change log](docs/ITERATIONS.md) · [Reproduction evidence](docs/VERIFICATION.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [License](LICENSE)

## 中文说明

**用证据决定缓存答案是否还能复用，并给出最小的后续核验任务集合。**

本项目适用于维护政策、产品配置、客服知识等 RAG 应用的工程团队。输入是本地 JSON：来源版本历史、明确时区的观测时间、TTL、结构化事实、主张以及答案之间的 AND/OR 支持关系。来源替换、撤销和过期会影响引用该版本的答案；仍有有效备用证据的答案可以保留。相同主体、属性和适用范围出现不同的当前值时，会返回带来源信息的冲突任务。

上面的安装和 CLI 命令可直接运行。Windows 使用 `py -3`。演示的三条答案分别展示“备用证据仍有效”“独立来源不受影响”“来源都新鲜但事实冲突”。`python examples/workflow.py` 演示完整的来源更新、影响比较、人工确认后重新绑定以及再次核验流程；`python tools/verify_workflow.py` 在临时目录运行已安装 CLI，核对错误退出码、输入保护和五种策略的结果。`benchmark` 对比全库 TTL、平面来源 TTL 和功能消融，所有数据均为公开的合成样例。

这是声明式证据约束检查，不会自动理解自然语言矛盾，不证明事实真实，也不替代 Ragas 的质量评测或 dbt 的数据编排。最小刷新集合表示条件性核验义务，执行后必须重新评估。库不会访问来源 URL；内容指纹不等同于签名。实际客户、收入和付费意愿均未知。
