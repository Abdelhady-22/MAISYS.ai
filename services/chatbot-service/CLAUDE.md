# services/chatbot-service/

Conversational medical Q&A grounded in Mayo Clinic + MedlinePlus.

## Required Reading

- `docs/technical-guides/part3.md` §9 — chatbot-service spec, multi-turn flow, citation enforcement
- `docs/technical-guides/part6.md` §3 — agent pattern (LangGraph)
- `docs/technical-guides/part6.md` §4 — RAG retrieval flow
- `docs/technical-guides/part5.md` (chatbot schema) — chat sessions, messages, citations tables
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- Multi-turn medical conversations in Arabic and English
- Retrieval from Medical RAG (Qdrant collection: `medical_rag`)
- Citation generation — every claim cites Mayo Clinic, MedlinePlus, or another authoritative source
- Emergency detection via safety-service
- Conversation history persistence
- Session export to PDF (delegates to export-service)
- Streaming responses via WebSocket

## Endpoints

- `POST /chatbot/sessions` — start new session
- `GET /chatbot/sessions` — list user's sessions
- `GET /chatbot/sessions/{id}` — full session with messages
- `DELETE /chatbot/sessions/{id}` — delete session
- `POST /chatbot/sessions/{id}/messages` — send message, get streamed response (HTTP) or trigger WebSocket stream
- `WS /ws/chatbot/{session_id}` — streaming response channel

## Agent Architecture (LangGraph)

Per Part 6 §3:

```
[User message]
    → [Safety pre-check (safety-service)]
        → If emergency → emergency response + stop
    → [Intent classifier]
    → [Medical RAG retrieval] (dual embedding: MiniLM + PubMedBERT)
    → [Context builder] (recent messages + retrieved chunks)
    → [LLM generation] (with citations enforced)
    → [Safety post-check]
    → [Stream to client]
```

## Citation Rule (Non-Negotiable)

Every factual claim about a condition, treatment, or drug must cite at least one retrieved source. The generation prompt explicitly requires `[ref:<chunk_id>]` markers in output. A post-processor verifies every fact-claim sentence has a marker. Sentences without markers are flagged and the response is regenerated up to 2 times before falling back to "I don't have enough information from authoritative sources."

## Tables (per Part 5)

- `chat_sessions`
- `chat_messages`
- `chat_message_citations`
- `chat_message_feedback`

## Dependencies

- Postgres (own database `chatbot`)
- Redis (KV cache for LLM responses, progress pub/sub)
- Qdrant (Medical RAG collection)
- shared/llm_client
- shared/embedding (dual embedder)
- safety-service (HTTP)
- translation-service (for bilingual responses)
- export-service (for PDF export)
- notification-service (for proactive follow-ups, if enabled)

## What This Service Does NOT Do

- No drug interactions — that's drug-service. Chatbot defers drug-specific questions or calls drug-service via HTTP.
- No symptom triage — that's symptom-service.
- No lab interpretation — that's lab-service.
- No diagnosis. Ever. The system is education-only.
