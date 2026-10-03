# Security and trust model

Treat manifests, claims and source metadata as untrusted assertions until your ingestion process validates their origin. A current TTL does not mean true, a URI is not an authenticated publisher, and a SHA-256 fingerprint is not a signature. The library never fetches source URIs, executes expressions as code or calls an LLM. It cannot detect prompt injection in source content or prove that answer text matches declared claims.

Keep one trust domain per manifest. Include all relevant assertions for each scoped fact if you rely on conflict checks. Missing sources or intentionally omitted dependencies cannot be discovered from a manifest alone. Use immutable externally stored snapshots and permissions/signatures appropriate to your environment; the event helper is not an append-only trusted database or concurrency service.

The loader has byte/shape/depth limits, and exact planning fails at its work budget. These do not replace operating-system resource limits for hostile tenants. Atomic file output preserves existing bytes when replacement fails, but does not lock multiple writers or guarantee directory fsync durability on every platform. CLI paths are caller-provided; the program is not a filesystem sandbox.

`SnapshotCache` is an optional single-writer, in-memory SDK object. Every update
must supply its constructor's exact `trust_domain` label. This check prevents
accidental domain mixing; the caller still verifies origin and supplies all
relevant scoped facts. Passing the same label cannot turn a foreign or incomplete
manifest into trusted evidence. Use only validated immutable `Manifest` values;
constructing internal dataclasses directly is unsupported. Returned snapshots
and exported reports are detached from later updates and ordinary caller mutation.
Deliberate Python reflection and concurrent writers are outside this boundary.
No external cache state is persisted, authenticated, synchronized or cleaned up.

Report reproducible vulnerabilities through the repository's private GitHub security reporting channel when available. If unavailable, open an issue requesting a private contact without publishing exploit details or sensitive data. There is no guaranteed response time. Include version/commit, Python/OS, a minimized synthetic manifest and observed vs expected result. Do not submit production facts, credentials or personal traces.
