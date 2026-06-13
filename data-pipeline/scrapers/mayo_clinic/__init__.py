"""Mayo Clinic scrapers (4 sub-areas) adapted for GCS output.

Sub-areas (DATA_PLAN §2.1 #3-6): ``diseases_conditions``, ``symptoms``,
``tests_procedures``, ``drugs_supplements``. Each writes per-page objects and an
aggregated ``<sub-area>.json`` under ``raw/mayo_clinic/`` plus a manifest.

The proven Playwright + playwright-stealth scraping logic from the original
scrapers is preserved unchanged; only the I/O layer (local disk → GCS), logging
(→ structlog), CLI, and manifest emission were adapted.
"""
