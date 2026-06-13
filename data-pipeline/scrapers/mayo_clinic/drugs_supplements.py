"""Mayo Clinic — Drugs & Supplements scraper (GCS output).

Drug pages have no tabs; uses the section-based ``drug`` extractor.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scrapers.mayo_clinic._engine import AreaConfig, run_area_cli  # noqa: E402

AREA = AreaConfig(
    sub_area="drugs_supplements",
    base_url="https://www.mayoclinic.org",
    index_url="https://www.mayoclinic.org/drugs-supplements/drug-list?letter=",
    path_pattern=r"/drugs-supplements/[^/]+/description/drg-\d+",
    extractor="drug",
)


def main(argv: list[str] | None = None) -> int:
    return run_area_cli(AREA, argv)


if __name__ == "__main__":
    raise SystemExit(main())
