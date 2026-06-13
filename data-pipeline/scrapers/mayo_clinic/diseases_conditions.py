"""Mayo Clinic — Diseases & Conditions scraper (GCS output)."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scrapers.mayo_clinic._engine import AreaConfig, run_area_cli  # noqa: E402

AREA = AreaConfig(
    sub_area="diseases_conditions",
    base_url="https://www.mayoclinic.org",
    index_url="https://www.mayoclinic.org/diseases-conditions/index?letter=",
    path_pattern=r"/diseases-conditions/[^/]+/symptoms-causes/syc-\d+",
    extractor="tabs",
)


def main(argv: list[str] | None = None) -> int:
    return run_area_cli(AREA, argv)


if __name__ == "__main__":
    raise SystemExit(main())
