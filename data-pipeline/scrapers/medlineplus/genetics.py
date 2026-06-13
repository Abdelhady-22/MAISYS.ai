"""MedlinePlus — genetics scraper (GCS output)."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scrapers.medlineplus._engine import GENETICS, run_area_cli  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    return run_area_cli(GENETICS, argv)


if __name__ == "__main__":
    raise SystemExit(main())
