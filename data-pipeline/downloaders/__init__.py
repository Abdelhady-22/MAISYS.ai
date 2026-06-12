"""External dataset downloaders for the MAISYS Beta-training pipeline.

These scripts run on an ephemeral GCP VM in Phase B (see ``DATA_PLAN.md`` §3.3)
and write their output directly to GCS. They never persist data on a developer
laptop and take cloud URIs only.
"""
