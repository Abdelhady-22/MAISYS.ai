"""MedlinePlus scrapers (5 sub-areas) adapted for GCS output.

Sub-areas (DATA_PLAN §2.1 #7-11): ``health_topics``, ``drugs``, ``lab_tests``,
``encyclopedia``, ``genetics``. Each writes per-page objects and an aggregated
``<sub-area>.json`` under ``raw/medlineplus/`` plus a manifest.

The proven ``requests``-based fetching and content-cleaning logic is preserved;
only the I/O layer (local disk → GCS), logging (→ structlog), CLI, politeness
(honest UA + robots.txt), and manifest emission were adapted. The HTTP fetch is
injectable so tests run without network.
"""
