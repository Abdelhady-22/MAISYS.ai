"""Cloud-data → Postgres / Qdrant ingesters.

Every ingester here implements the contract documented in
``data-pipeline/CLAUDE.md``:

* Input is one or more cloud URIs (``gs://`` / ``s3://`` / azure).
* Per-file idempotency via SHA-256 marker stored in the target store.
* Progress events published to Redis pub/sub on
  ``ingestion.<source>``.
* ``--force`` flag forces a re-run.
"""
