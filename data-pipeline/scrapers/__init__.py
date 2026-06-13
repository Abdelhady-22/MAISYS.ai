"""Cloud-native scrapers for the MAISYS data pipeline.

Each scraper adapts proven scraping logic to MAISYS conventions: it writes its
output to Google Cloud Storage (never local disk), emits a manifest, logs via
structlog, and is idempotent (skip-if-exists). They run on an ephemeral GCP VM in
Phase B (see ``DATA_PLAN.md`` §3.3) and take cloud URIs only.

Shared helpers live alongside the scraper packages:

* ``_logging`` — structlog console configuration.
* ``_storage`` — ``parse_gs_uri``, manifest models, and the ``GcsSink`` cloud I/O
  layer (per-page objects + aggregated file + manifest).
* ``_secrets`` — GCP Secret Manager resolution shim (env fallback, project
  discovery). Temporary until ``shared/security`` exists.
"""
