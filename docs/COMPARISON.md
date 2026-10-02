# Prior art and executable contrasts

Primary sources checked 2026-10-03. These are documented capabilities, not exhaustive competitor audits:

| Source | Capability credited | Relationship to this project |
|---|---|---|
| [Ragas metrics](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/) and [faithfulness](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/faithfulness/) | RAG evaluation includes context precision/recall, response relevance and faithfulness; metrics evaluate distinct application-quality dimensions | Use such evaluation to assess grounding/quality. evidencecache assumes declared claim evidence and evaluates its lifecycle and scoped structured disagreements; it does not reproduce a semantic faithfulness model |
| [dbt freshness configuration](https://docs.getdbt.com/reference/resource-configs/freshness) and [source freshness](https://docs.getdbt.com/docs/deploy/source-freshness) | dbt supports freshness thresholds, timestamp/metadata queries and orchestration. Current documentation also covers model freshness and upstream any/all behavior | Freshness and dependency-aware decisions already exist. This library's useful combination is pinned answer evidence alternatives plus scoped fact conflicts and exact conditional obligation antichains, not invention of dependency graphs or TTL |

Nothing on these pages establishes that either ecosystem lacks an equivalent extension. No competitor software is benchmarked; no speed, cost or accuracy superiority is claimed.

Run `python -m evidencecache benchmark --groups 100`. `fixtures.py` publicly defines every synthetic record; no random or proprietary data is hidden. Each group has five sources, three claims and three answers: an expired primary with fresh equal mirror, an independent fresh service status, and two fresh conflicting price assertions. Expected labels are declared by scenario and checked against the engine before returning results. `--groups` repeats disjoint groups (1–1000); it measures decisions, not realistic workload diversity or time complexity.

Baselines are deliberately specific, executable policies:

1. **Whole-corpus TTL gate:** flatten every transitive cited source-version reference; if any is not fresh/current/unrevoked, invalidate all answers. This corresponds to a cache generation gated by its earliest stale dependency. It is conservative but intentionally coarse.
2. **Flat per-source TTL:** each answer is valid only if every transitive citation is fresh/current/unrevoked. This honors source lifecycle, so the contrast does not depend on an artificially weak replacement implementation. It has no alternate-support or structured-conflict semantics.
3. **Without fact checks:** identical engine with claim fact declarations removed. TTL and alternatives remain; known fixture conflicts are missed.
4. **Without alternative support:** replace each fixture OR with AND. Conflicts remain; valid alternative answers are discarded.

Report `unnecessary_invalidations` and `unsafe_reuses` against the explicitly known synthetic labels. These terms do not imply measured production safety. A source replacement is also applied to `g0000-status` at the snapshot: exactly `g0000-steady` loses valid support, while other valid answers retain it. The benchmark exposes the changed versions and complete answer sets for inspection.

The adversarial planner case `(s0 OR s1) AND (s1 OR s2)` returns `{s1}` and `{s0,s2}`. A separate test solver enumerates all source subsets on 60 generated DAGs with varied current/stale sources. This is falsifiable algorithmic evidence beyond repeated scenario labels. Limitations: fact extraction, cache hit distribution, retrieval cost, semantic quality and operational adoption are unmeasured.
