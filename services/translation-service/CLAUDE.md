# services/translation-service/

Arabic ↔ English translation, medical-aware.

## Required Reading

- `docs/technical-guides/part2.md` §4 — translation-service (shared service)
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- Translate between Arabic and English
- Medical-term preservation (don't translate "warfarin" to its Arabic transliteration in the middle of an English sentence; keep generic names as-is)
- Bilingual term dictionary (drug names, conditions, anatomy)
- Per-module style (chatbot is conversational; lab is clinical-but-accessible)
- Caching of common phrases

## Endpoints

- `POST /translate` — translate text, with optional medical glossary lookup
- `POST /translate/batch` — translate array of texts (used by export-service for PDFs)
- `GET /translate/glossary/{term}` — look up bilingual medical term

## Strategy

- Default: LLM-based translation via shared/llm_client (cheap model)
- Glossary override: terms in `medical_glossary` table take priority over LLM output
- Cache: Redis hash, key = SHA(source_lang|target_lang|text), TTL 30 days

## Tables (per Part 5)

- `medical_glossary` (bilingual term pairs with metadata: category, do_not_translate flag)
- `translation_cache` (or just Redis — Postgres for audit only)

## Dependencies

- Postgres (own database `translation`, small — mainly glossary)
- Redis (cache)
- shared/llm_client

## What This Service Does NOT Do

- No language detection (callers must specify source language; if uncertain, callers pass `auto` and the service uses LLM detection then translation)
- No translation between Arabic↔Arabic dialects (MSA only)
- No transliteration (used to be a feature; cut from scope per Part 2)
