# services/export-service/

PDF generation for chat sessions, drug reports, lab interpretations, research summaries.

## Required Reading

- `docs/technical-guides/part2.md` §6 — export-service spec
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- Render structured data → PDF
- Bilingual layout (RTL-aware) — Arabic exports use RTL with appropriate font
- Tables, citations, code blocks all rendered cleanly
- Headers/footers with MAISYS branding + page numbers + disclaimer
- Watermark for educational-use notice
- Storage of generated PDFs in `gs://maisys-data-{env}/exports/{user_id}/`
- Signed-URL download with 24h expiry

## Endpoints

- `POST /export/chat-session/{session_id}` — chat → PDF
- `POST /export/drug-report` — drug results → PDF
- `POST /export/lab-interpretation/{interpretation_id}` — lab → PDF
- `POST /export/research-summary/{paper_id}` — paper summary → PDF
- `GET /export/{export_id}` — get status + download URL when ready
- `GET /export/{export_id}/download` — redirects to signed URL

## Stack

- Rendering: WeasyPrint (HTML + CSS → PDF, supports RTL)
- Templates: Jinja2 in `services/export-service/templates/`
- Fonts: Noto Sans (English), Noto Sans Arabic (Arabic) — bundled in container
- Storage: `shared/storage` → cloud bucket
- Queue: RabbitMQ — exports are async, frontend polls `GET /export/{id}` until ready

## Disclaimer Footer (Mandatory)

Every page footer includes (in the language of the export):

> *MAISYS is an educational platform. Information here is not medical advice. Consult a qualified clinician for medical decisions.*

This is hard-coded into all templates, not configurable. Removing it from a template is a security-equivalent change requiring explicit approval.

## Tables (per Part 5)

- `exports` (id, user_id, type, status, output_uri, created_at, expires_at)

## Dependencies

- Postgres (own database `export`, lightweight)
- RabbitMQ (async render queue)
- shared/storage (write to cloud bucket)
- translation-service (when source content needs translation before render)

## What This Service Does NOT Do

- No DOCX or other formats in v1 (PDF only)
- No editing of generated PDFs
- No long-term storage — exports expire after 30 days and are auto-deleted
