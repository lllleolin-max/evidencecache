# Manifest v1 and public interfaces

`Manifest.from_dict`, `load(path)` and `loads(text)` are the supported constructors. Loaded models are frozen dataclasses with tuple members. Constructing internal dataclasses directly bypasses validation and is unsupported. `to_dict()` returns a detached serializable structure. IDs use `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}` and are unique within their namespace; version IDs are unique within a source.

Top-level keys are exactly `schema_version: 1`, `sources`, `claims`, and `answers`. Unknown fields fail, rather than silently misspelling a policy. Empty top-level arrays are allowed; support operators and version histories are nonempty. Generate a complete sample with `python -m evidencecache demo`.

```json
{
  "schema_version": 1,
  "sources": [{
    "id": "policy", "uri": "https://example.invalid/policy",
    "versions": [{
      "id": "r1", "observed_at": "2026-01-01T00:00:00Z", "ttl_seconds": 86400,
      "facts": [{"subject":"pro", "predicate":"retention_days", "scope":"eu", "value":30}]
    }]
  }],
  "claims": [{
    "id":"retention", "text":"EU Pro retention is 30 days.",
    "fact":{"subject":"pro", "predicate":"retention_days", "scope":"eu", "value":30},
    "support":{"evidence":{"source":"policy", "version":"r1"}}
  }],
  "answers": [{"id":"faq", "text":"30 days.", "support":{"claim":"retention"}}]
}
```

Version fields: required `id`, `observed_at`, `ttl_seconds`, `facts`; optional `revoked_at`, `digest` (`sha256:` and 64 lowercase hex digits). Digest is producer-supplied provenance, never a verified signature/content fetch. Times need seconds, up to six fractional digits and `Z`/numeric offset. Naive time, invalid dates, normalized overflow offsets such as `+00:60`, unknown offset `-00:00`, and datetime overflow fail. TTL is an integer from 0 to 315576000 seconds; zero is immediately expired. Revocation cannot precede observation. Simultaneous version observations are ambiguous and rejected.

At `as_of=t`, the newest version with observation `<=t` is current. Future history is ignored for active facts. Only a current, unrevoked version with `t < expires_at` contributes facts. Old versions never become current again when a newer one expires/revokes. These are event-time reconstructions of the supplied history, not a bitemporal record of what a user actually knew in the past. Preserve earlier files for that audit purpose.

Claim fields: required `id`, `text`, `support`; optional `fact`. Fact values are null, boolean, JSON-safe integer (`±(2^53−1)`) or string. Booleans and integers are distinct. Numbers with units/decimals must be canonical strings. Fact keys are exact, case-sensitive strings `(subject, predicate, scope)`; no unit conversion, synonym matching or Unicode normalization is inferred. A version can assert a key once. Scope must encode relevant geography, product tier and effective policy interval as determined by your adapter. Different scopes never conflict.

Support expressions have exactly one operator:

| Expression | Meaning |
|---|---|
| `{"evidence":{"source":"x","version":"r1"}}` | Pinned source version |
| `{"claim":"c1"}` | Another claim |
| `{"all":[...]}` | Every child must support the result |
| `{"any":[...]}` | At least one child supports the result |

Claims form a DAG; cycles, dangling claims and dangling evidence fail. For a claim with `fact`, every direct evidence leaf must contain that exact fact. Claim-to-claim edges are producer-declared inference; the engine does not prove a derived conclusion from premises. A claim without a fact still has evidence freshness constraints but cannot participate in fact conflict checks. Answers contain only claim leaves, nested with all/any. Their text is opaque display data; the producer must declare every dependency required to support it.

A fact-bearing claim is blocked when current fresh assertions for its key disagree, or when they only assert a different value. Every source in the manifest participates, including sources not cited by that answer. All listed sources are assumed relevant to the same trust domain. Curate manifests before combining unrelated tenants or source authorities.

`Snapshot(manifest, as_of)` computes all source, claim and answer states. `report(answer=None)` returns JSON-compatible decisions; blockers are the **union of diagnostic alternatives**, not a list of tasks all required. `plan(answer, max_work=100000)` enumerates every subset-minimal conditional obligation set, sorted by cardinality then lexical IDs. `minimum_task_count` is minimal task cardinality, not minimum monetary cost. Shared obligations count once. `witnesses` enumerates subset-minimal fresh evidence sets. `compare(before, after)` returns validity transitions and changed evidence. Changing answer text itself is not a source-triggered invalidation; regenerate the cache item when changing its definition.

Plans never promise that refreshing the listed sources will make an answer true or valid: new evidence may reveal additional conflicts. For expired evidence, revalidate against the actual source and add a fresh version. Replaced/revoked evidence requires new citations or answer regeneration. Conflict resolution requires an authoritative decision and corrected/revoked facts. Execute these steps in your integration, then evaluate the entire new manifest. No event marks an old immutable version fresh.

`apply_event(manifest, event)` returns a new fully validated manifest. Events:

```json
{"kind":"publish", "source":"policy", "version":{"id":"r2","observed_at":"2026-01-02T00:00:00Z","ttl_seconds":86400,"facts":[]}}
```

An optional `rebind_from` replaces explicit evidence citations for that source/version. Use it only after checking unchanged meaning/content. Fact mismatch aborts, but unstructured text cannot be checked. Publish IDs must be new. A revocation event is `{"kind":"revoke","source":"policy","version":"r1","at":"2026-01-02T00:00:00Z"}`. Repeating the same instant is idempotent; changing a recorded revocation is rejected.

CLI output is JSON on stdout. Domain errors are JSON on stderr. Exit codes: `0` successful computation (including blocked answers), `1` blocked when `evaluate --fail-on-blocked` is selected, `2` invalid input/I/O or argparse usage, `3` exact planning work exhausted. Argparse help/usage follows normal text behavior. `--as-of` is mandatory; there is no hidden clock. `apply` writes a new artifact using flush/fsync plus atomic replacement and refuses to replace its input manifest. Atomic visibility is not multiwriter coordination or full directory-durability on power loss.
