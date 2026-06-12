# services/research-service/

PDF upload + Paper RAG. The only service that accepts user-uploaded files.

## Required Reading

- `docs/technical-guides/part3.md` §13 — research-service spec
- `docs/technical-guides/part6.md` §1 — chunking (medical papers have structure: abstract, methods, results, discussion)
- `docs/technical-guides/part6.md` §2 — dual embedding
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- Accept PDF uploads (single or batch)
- Extract text with `pymupdf` (or `pdfplumber` fallback)
- Chunk with structure awareness (abstract, methods, results, discussion, references)
- Embed dual (MiniLM + PubMedBERT)
- Store in user-scoped Qdrant collection (`paper_rag_user_<user_id>`)
- Q&A over uploaded papers with citation back to specific paragraph + page
- Summarization (TL;DR, methods summary, key findings, limitations)
- Citation extraction & linking to PubMed when available

## File Upload Rules

- Max file size: 50 MB per PDF
- Max files per user: 100 (storage tier dependent — premium higher)
- PDFs only (validated by magic number, not extension)
- Files stored in `gs://maisys-data-{env}/user_uploads/{user_id}/{paper_id}/`
- Original PDF + extracted text + embeddings all version-tagged
- Encrypted at rest (cloud-native)

## Endpoints

- `POST /research/papers` — upload PDF (multipart)
- `GET /research/papers` — list user's papers
- `GET /research/papers/{id}` — paper metadata + extraction status
- `DELETE /research/papers/{id}`
- `POST /research/papers/{id}/qa` — Q&A on a paper
- `POST /research/papers/{id}/summarize` — generate summary
- `POST /research/qa` — Q&A across all user's papers
- `WS /ws/research/{request_id}` — extraction + Q&A progress

## Per-User Qdrant Collections

User papers are isolated. Each user gets a Qdrant collection `paper_rag_user_<user_id>` provisioned on first upload. Deleted on account deletion.

## Tables (per Part 5)

- `papers`
- `paper_extraction_status`
- `paper_summaries`
- `paper_qa_sessions`
- `paper_qa_messages`
- `paper_audit_log`

## Dependencies

- Postgres (own database `research`)
- Qdrant (per-user collections)
- shared/storage (`gs://maisys-data-*/user_uploads/`)
- shared/chunking, shared/embedding
- shared/llm_client
- shared/security (file validation, virus scan)
- translation-service

## What This Service Does NOT Do

- No paper recommendations from external sources (out of scope for v1)
- No co-authoring or paper drafting
- No medical advice derived from a single paper without explicit user request
