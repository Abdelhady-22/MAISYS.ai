"""Canonical list of HuggingFace medical datasets for Beta training.

The inventory mirrors ``DATA_PLAN.md`` §2.2 (Beta training data) and §2.3
(knowledge-graph instruction pairs). Each entry is a :class:`DatasetSpec`; the
downloader (`download_huggingface_medical.py`) iterates this list, or a subset
selected on the CLI.

``name`` is the sanitized folder used under
``beta_training/raw_downloads/huggingface/<name>/`` in GCS. It is derived from
``dataset_id`` (and ``config``) when not given explicitly, so the list stays
DRY and the on-disk layout is deterministic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class DatasetSpec(BaseModel):
    """A single HuggingFace dataset to download.

    Attributes:
        dataset_id: The HuggingFace hub id, e.g. ``medalpaca/medical_meadow_medqa``.
        config: Optional dataset config/subset name (e.g. ``pqa_artificial``).
        split: Optional single split to fetch; ``None`` fetches every split.
        trust_remote_code: Pass through to ``datasets.load_dataset``; required by
            datasets that ship a loading script. Kept explicit and opt-in because
            it executes code from the hub.
        name: Sanitized folder name; auto-derived from ``dataset_id``/``config``
            when left blank.
        notes: Free-text provenance note.
    """

    dataset_id: str = Field(min_length=1)
    config: str | None = None
    split: str | None = None
    trust_remote_code: bool = False
    name: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def _fill_name(self) -> DatasetSpec:
        if not self.name:
            base = self.dataset_id.replace("/", "__")
            self.name = f"{base}__{self.config}" if self.config else base
        return self


# ── Canonical inventory ───────────────────────────────────────────────────
# Order is stable; the downloader preserves it for deterministic manifests.
DATASETS: list[DatasetSpec] = [
    # MedAlpaca "medical_meadow" family — plain data on the hub, no loader script.
    DatasetSpec(dataset_id="medalpaca/medical_meadow_medqa", notes="USMLE-style QA"),
    DatasetSpec(
        dataset_id="medalpaca/medical_meadow_medical_flashcards",
        notes="Medical flashcards",
    ),
    DatasetSpec(dataset_id="medalpaca/medical_meadow_wikidoc", notes="WikiDoc clinical"),
    DatasetSpec(
        dataset_id="medalpaca/medical_meadow_wikidoc_patient_information",
        notes="WikiDoc patient info",
    ),
    DatasetSpec(dataset_id="medalpaca/medical_meadow_cord19", notes="CORD-19 abstracts"),
    DatasetSpec(dataset_id="medalpaca/medical_meadow_health_advice", notes="PubMed health advice"),
    DatasetSpec(dataset_id="medalpaca/medical_meadow_mediqa", notes="MEDIQA"),
    DatasetSpec(dataset_id="medalpaca/medical_meadow_mmmlu", notes="MMMLU (enriched)"),
    DatasetSpec(dataset_id="medalpaca/medical_meadow_pubmed_causal", notes="PubMed causal claims"),
    # Standalone QA / MCQA sets.
    DatasetSpec(dataset_id="GBaker/MedQA-USMLE-4-options", notes="MedQA-USMLE 4-option"),
    DatasetSpec(
        dataset_id="openlifescienceai/medmcqa",
        trust_remote_code=True,
        notes="MedMCQA — ships a loading script",
    ),
    DatasetSpec(
        dataset_id="qiaojin/PubMedQA",
        config="pqa_artificial",
        trust_remote_code=True,
        notes="PubMedQA artificial subset — ships a loading script",
    ),
    # Knowledge-graph adjacent (DATA_PLAN §2.3).
    DatasetSpec(dataset_id="kamruzzaman-asif/Diseases_Dataset", notes="Diseases dataset"),
]


def available_identifiers() -> list[str]:
    """Return every selectable identifier (both hub id and sanitized name)."""
    ids: list[str] = []
    for spec in DATASETS:
        ids.append(spec.dataset_id)
        if spec.name != spec.dataset_id:
            ids.append(spec.name)
    return ids


def get_datasets(names: list[str] | None) -> list[DatasetSpec]:
    """Resolve a selection of dataset specs.

    Args:
        names: Identifiers to select, each matched against either ``dataset_id``
            or the sanitized ``name``. ``None`` (or empty) returns every dataset.

    Raises:
        ValueError: If any requested identifier is unknown.
    """
    if not names:
        return list(DATASETS)

    by_key: dict[str, DatasetSpec] = {}
    for spec in DATASETS:
        by_key[spec.dataset_id] = spec
        by_key[spec.name] = spec

    selected: list[DatasetSpec] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for requested in names:
        key = requested.strip()
        match = by_key.get(key)
        if match is None:
            unknown.append(requested)
            continue
        if match.dataset_id not in seen:
            seen.add(match.dataset_id)
            selected.append(match)

    if unknown:
        available = ", ".join(sorted(set(available_identifiers())))
        raise ValueError(f"unknown dataset(s): {', '.join(unknown)}. Available: {available}")
    return selected
