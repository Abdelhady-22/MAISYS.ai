"""Cloud storage operations for the MAISYS data pipeline.

Contains the one-time laptop-to-GCS upload bridge (``upload_local_to_gcs``)
and, later, the cross-cloud sync and checksum-verification scripts. Every
module here except ``upload_local_to_gcs`` operates on cloud URIs only.
"""
