"""Disclosed synthetic fixtures. No customer data, retrieval or LLM calls."""
from __future__ import annotations

AS_OF = "2026-01-02T00:00:00Z"


def evidence(source: str, version: str = "v1") -> dict:
    return {"evidence": {"source": source, "version": version}}


def fixture(groups: int = 1) -> dict:
    result = dict(schema_version=1, sources=[], claims=[], answers=[])
    for i in range(groups):
        prefix = f"g{i:04d}"
        fact = dict(subject=prefix + ":plan", predicate="retention_days", scope="region:eu;tier:pro", value=30)
        def source(suffix, ttl, value=30):
            f = dict(fact, value=value)
            return dict(id=prefix + suffix, uri="https://example.invalid/policy/" + prefix + suffix,
                        versions=[dict(id="v1", observed_at="2026-01-01T00:00:00Z", ttl_seconds=ttl, facts=[f])])
        result["sources"].extend([source("-old", 86_400), source("-mirror", 172_800)])
        result["claims"].append(dict(id=prefix + "-retention", text="Pro EU retention is 30 days.", fact=fact,
                                      support={"any": [evidence(prefix + "-old"), evidence(prefix + "-mirror")]}))
        result["answers"].append(dict(id=prefix + "-alternative", text="EU Pro data is retained for 30 days.",
                                       support={"claim": prefix + "-retention"}))
        steady = source("-status", 172_800)
        steady["versions"][0]["facts"] = [dict(subject=prefix + ":service", predicate="status", scope="global", value="operational")]
        result["sources"].append(steady)
        result["claims"].append(dict(id=prefix + "-uptime", text="The service is operational.",
                                      fact=steady["versions"][0]["facts"][0], support=evidence(prefix + "-status")))
        result["answers"].append(dict(id=prefix + "-steady", text="The service is operational.", support={"claim": prefix + "-uptime"}))
        for suffix, value in (("-price", "20 USD"), ("-billing", "25 USD")):
            s = source(suffix, 172_800)
            s["versions"][0]["facts"] = [dict(subject=prefix + ":plan", predicate="monthly_price", scope="region:eu;tier:pro", value=value)]
            result["sources"].append(s)
        result["claims"].append(dict(id=prefix + "-cost", text="The monthly price is 20 USD.",
                                      fact=result["sources"][-2]["versions"][0]["facts"][0], support=evidence(prefix + "-price")))
        result["answers"].append(dict(id=prefix + "-conflict", text="The monthly price is 20 USD.", support={"claim": prefix + "-cost"}))
    return result
