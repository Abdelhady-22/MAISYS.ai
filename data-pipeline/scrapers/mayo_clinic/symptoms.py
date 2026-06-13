"""Mayo Clinic — Symptoms scraper (GCS output)."""

from __future__ import annotations

import pathlib
import sys

# Support direct execution (``python data-pipeline/scrapers/mayo_clinic/symptoms.py``),
# which Phase B's orchestrator uses, alongside ``-m`` / package import.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scrapers.mayo_clinic._engine import AreaConfig, run_area_cli  # noqa: E402

AREA = AreaConfig(
    sub_area="symptoms",
    base_url="https://www.mayoclinic.org",
    index_url="https://www.mayoclinic.org/symptoms/index?letter=",
    path_pattern=r"/symptoms/[^/]+/basics/",
    extractor="tabs",
)


def main(argv: list[str] | None = None) -> int:
    return run_area_cli(AREA, argv)


if __name__ == "__main__":
    raise SystemExit(main())
