# Beta Training Normalizers — Contract

This folder contains one normalizer per raw data source. Each normalizer converts a heterogeneous raw source into a uniform JSONL format suitable for fine-tuning the MAISYS Beta model.

## Required Reading

- `docs/technical-guides/part4.md` — Beta training data sources, target dataset shape
- `data-pipeline/CLAUDE.md` — cloud-only rules, idempotency, manifest emission

## Normalizer Contract

Every script in this folder MUST:

### Input

- A cloud URI pointing to the raw source (CSV, JSON, JSONL, Parquet, or directory of such)
- Example: `gs://maisys-data-dev/beta_training/raw_downloads/chatdoctor_github/HealthCareMagic-100k.json`

### Output

A single JSONL file written to:

```
gs://maisys-data-dev/beta_training/normalized/{source_name}.jsonl
```

Each line is a JSON object with this exact shape:

```json
{
  "instruction": "What are the side effects of warfarin?",
  "input": "",
  "output": "Common side effects of warfarin include...",
  "metadata": {
    "source": "chatdoctor",
    "source_record_id": "hm_42891",
    "language": "en",
    "category": "drug_information",
    "license": "research_only",
    "quality_score": 0.87
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `instruction` | string, required | The question or directive |
| `input` | string, may be empty | Additional context, e.g., a patient's history |
| `output` | string, required | The expected response |
| `metadata.source` | string, required | Identifier for the source (e.g., `chatdoctor`, `medalpaca_medical_meadow_medical_flashcards`) |
| `metadata.source_record_id` | string, required | Original record identifier for traceability |
| `metadata.language` | enum, required | `en`, `ar`, or `bilingual` |
| `metadata.category` | string, optional | Topical category, free-form but consistent within source |
| `metadata.license` | string, required | License classification: `permissive`, `research_only`, `restricted` |
| `metadata.quality_score` | float, 0–1, optional | If the source has quality signals (votes, peer review), normalize to 0–1 |

### CLI Interface

Every normalizer exposes the same CLI:

```
python -m data_pipeline.beta_training.normalizers.<source>_normalizer \
    --input gs://maisys-data-dev/beta_training/raw_downloads/<source>/<file> \
    --output gs://maisys-data-dev/beta_training/normalized/<source>.jsonl \
    --force                       # optional, re-runs even if output exists
```

### Manifest Emission

After successful run, write a manifest entry to:

```
gs://maisys-data-dev/manifests/normalized/<source>.json
```

Manifest format:

```json
{
  "source": "chatdoctor",
  "input_uri": "gs://...",
  "input_md5": "...",
  "output_uri": "gs://...",
  "output_md5": "...",
  "record_count": 100000,
  "language_distribution": {"en": 100000, "ar": 0},
  "started_at": "2026-04-12T10:00:00Z",
  "completed_at": "2026-04-12T10:14:23Z",
  "normalizer_version": "1.0.0"
}
```

### Idempotency

- Reading: compute input MD5, compare to manifest's `input_md5` — if match and output exists, skip (unless `--force`)
- Writing: write output to a temp object first (`<output>.tmp`), then rename atomically to final name

### Error Handling

- Records that fail to parse (malformed JSON, missing required fields, etc.) are written to `gs://maisys-data-dev/beta_training/quarantine/<source>/`
- A failed record never aborts the whole run unless > 10% of records fail
- Final manifest includes `error_count` and `quarantine_count`

### Logging

- Use `shared/logger`
- Bind `source`, `input_uri`, `run_id` at start
- INFO every 10,000 records
- ERROR for parse failures (with the offending record's source ID, not its content)

## Normalizers to Implement (per Part 4)

One normalizer per source. Approximate list:

- `chatdoctor_normalizer.py`
- `medalpaca_medical_meadow_normalizer.py` (handles all 9 medical_meadow subsets)
- `medqa_usmle_normalizer.py`
- `medmcqa_normalizer.py`
- `pubmedqa_normalizer.py` (pqa_artificial subset)
- `diseases_dataset_normalizer.py` (kamruzzaman-asif/Diseases_Dataset)
- `mtsamples_normalizer.py`
- `mimic_iii_demo_normalizer.py`
- `infermedica_scrape_normalizer.py`
- `endlessmedical_scrape_normalizer.py`
- `primekg_normalizer.py` (KG → instruction pairs)
- `mit_kg_normalizer.py` (KG → instruction pairs)
- `itachi9604_kg_normalizer.py` (KG → instruction pairs)
- `itachi9604_kaggle_normalizer.py`
- `mendeley_2023_normalizer.py`

## After Normalization

`data-pipeline/beta_training/merge_and_split.py` reads all `gs://maisys-data-dev/beta_training/normalized/*.jsonl`, applies quality filtering, dedup, and splits into train/val/test. That output feeds the LoRA fine-tuning pipeline in `data-pipeline/fine_tuning/`.

## Testing Normalizers

Each normalizer has paired tests in `data-pipeline/beta_training/normalizers/tests/`:

- Unit test with a fixture of 5–10 raw records → assert output JSONL has correct schema
- Test for handling malformed records → assert quarantine, not failure
- Test for idempotency → run twice, second run skips
- Test for `--force` → second run with `--force` recomputes

No live network calls in tests. Use local fixtures and `unittest.mock`.
