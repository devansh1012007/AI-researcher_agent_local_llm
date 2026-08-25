# Providers & Resilience

## Interfaces (spec #69)

```
providers/
  search/      duckduckgo | searxng          (SearchProvider)
  academic/    openalex | crossref | arxiv | semantic_scholar
  llm/         ollama | openai_compatible | llama_cpp | mock (ModelRouter roles)
  embeddings/  hashing | ollama | openai_compatible
```

Registration is configuration-driven (#70):

```yaml
search:
  web_provider: duckduckgo     # none => offline, no web registration at all
  academic_providers: [openalex, crossref, arxiv]
embeddings: {provider: hashing}
```

Unknown providers fall back to mock with a warning — graceful degradation is
a contract (#52).

## Failover chains (#53)

`platform/resilience.py::FailoverExecutor` runs an operation across an
ordered provider list: tripped breakers are skipped toward the fallback;
success/failure outcomes feed back into each provider's breaker.

## Circuit breakers (#54)

Per-provider CLOSED→OPEN→HALF_OPEN after N consecutive failures; OPEN fails
fast (no hammering broken services); one probe after cooldown.

## Rate limiting (#55)

Token buckets per provider/domain (`DomainRateLimits`, defaults 5 rps burst
10) with configurable overrides.

## Network hygiene (#56)

Timeouts everywhere, classified retries (4xx never retried like timeouts),
backoff+jitter, response size caps in fetching, global search/fetch caches.
