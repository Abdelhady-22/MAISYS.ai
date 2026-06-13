"""Mayo Clinic — Tests & Procedures scraper (GCS output)."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scrapers.mayo_clinic._engine import AreaConfig, run_area_cli  # noqa: E402

AREA = AreaConfig(
    sub_area="tests_procedures",
    base_url="https://www.mayoclinic.org",
    index_url="https://www.mayoclinic.org/tests-procedures/index?letter=",
    path_pattern=r"/tests-procedures/[^/]+/(?:about/)?(?:pac|pyc)-\d+",
    extractor="tabs",
)


def main(argv: list[str] | None = None) -> int:
    return run_area_cli(AREA, argv)


if __name__ == "__main__":
    raise SystemExit(main())
