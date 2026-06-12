# monitoring/ — Observability Stack

Prometheus + Grafana + Loki, deployed alongside services in each cloud.

## Required Reading

- `docs/technical-guides/part4.md` §11 — monitoring spec, 5 dashboards, alert rules

## Folder Structure

```
monitoring/
├── prometheus/
│   ├── prometheus.yml             scrape configs + recording rules
│   └── alert_rules.yml            alert definitions
├── grafana/
│   ├── dashboards/                JSON dashboard definitions (5 total per Part 4 §11)
│   └── datasources/               Prometheus + Loki datasource configs
└── loki/
    └── loki-config.yaml
```

## Dashboards

Five dashboards, one per concern (per Part 4 §11):

1. **Service health** — uptime, error rate, latency p50/p95/p99 per service
2. **LLM costs** — tokens in/out per model per hour, $ per request, cache hit rate
3. **RAG quality** — retrieval latency, hit rate, citation coverage
4. **Beta safety metrics** — emergency FNR, triage accuracy, hallucination flags
5. **Infrastructure** — node CPU/memory/disk, pod restarts, network errors

Dashboard JSON committed here. Grafana auto-provisions them at startup.

## Alerts

- Page on: service down, error rate > 5% over 5 min, emergency FNR > 0%
- Slack notification: latency p95 > SLO, budget threshold crossed
- Ticket created: pod crash loop, persistent failed jobs

## Rules

1. **Every service exposes `/metrics`** in Prometheus format. Implemented via FastAPI middleware in `shared/`.
2. **Every log line is structured JSON.** Use `shared/logger` (structlog). Loki indexes by service, env, request_id, user_id.
3. **No PII in logs or metrics.** Patient symptoms, drug names, lab values are all PII-adjacent — log IDs and types, not content.
4. **Dashboards are reproducible.** JSON in this folder, not "I made changes in the Grafana UI."
