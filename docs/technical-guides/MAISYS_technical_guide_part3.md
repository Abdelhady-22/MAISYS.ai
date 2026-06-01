# MAISYS — Technical Development Guide
## Part 3: Agent Architecture · Production Reliability · All Module Services in Full Detail

---

## Table of Contents

1. [LangGraph Agent Architecture](#1-langgraph-agent-architecture)
2. [Multi-Agent Production Reliability](#2-multi-agent-production-reliability)
3. [Deterministic Orchestration Rules](#3-deterministic-orchestration-rules)
4. [Node Audit — Code vs Agent](#4-node-audit--code-vs-agent)
5. [Live Real-Time Agent Activity Display](#5-live-real-time-agent-activity-display)
6. [Live Visual Generation](#6-live-visual-generation)
7. [Visual Agents — All Services](#7-visual-agents--all-services)
8. [Real-Time Streaming — All Services](#8-real-time-streaming--all-services)
9. [chatbot-service — Full Detail](#9-chatbot-service--full-detail)
10. [drug-service — Full Detail](#10-drug-service--full-detail)
11. [symptom-service — Full Detail](#11-symptom-service--full-detail)
12. [lab-service — Full Detail](#12-lab-service--full-detail)
13. [research-service — Full Detail](#13-research-service--full-detail)

---

## 1. LangGraph Agent Architecture

### 1.1 What an Agent Is in MAISYS

An agent in MAISYS is a task-specific LangGraph StateGraph that handles a defined, bounded operation requiring multiple sequential or conditional steps. Agents are used only when the task genuinely requires: conditional branching that depends on runtime results (e.g. RAG sufficient? yes → generate, no → web search), multiple sequential steps with shared evolving state (e.g. normalize → retrieve → analyze → aggregate), or multi-step browser automation that cannot be expressed as a single function call.

Agents are not used for simple or deterministic operations. If a function call, a regex, an API call, or a rule check can handle the task reliably without LLM reasoning, it is implemented as a code function — not an agent. This keeps the system faster, cheaper, and more predictable. See Section 4 for the full node audit.

### 1.2 StateGraph Pattern

Every LangGraph agent defines a typed state object that flows through all nodes. The state is initialized at graph start with input parameters and grows as nodes add their results. Each node receives the full current state, performs its operation, and returns a dictionary of updated fields. The graph engine merges these updates into the state before advancing to the next node.

State fields carry: input parameters, retrieved content, intermediate results, error flags, retry counters, token usage, and the trace ID for observability. All state fields have explicit types — no untyped dicts.

### 1.3 Shared Tool Nodes

Common operations used by multiple agents are defined once and imported by any agent that needs them. These are not separate microservices — they are code modules that execute within the calling agent's process and make REST calls to shared services when needed.

**RAG retrieval tool:** Takes query text, collection name, optional section filter, top-k count. Returns ranked list of chunks with metadata. Used by drug lookup, interaction, dosage, comparison, pharmacokinetics, alternative, and paper chat agents.

**Web search tool:** Takes a search query string. Calls SerpAPI. Returns top result snippets with source URLs. Used by drug web search agent and paper discovery agent.

**Drugs.com scraper tool:** Takes list of drug names. Playwright navigates drugs.com/drug_interactions.html, enters each name, clicks Check Interactions, waits for results DOM, extracts structured interaction data via BeautifulSoup. Returns structured interaction records with source URL. Used exclusively by the Interaction Agent Tier 2 fallback.

**RxNorm tool:** Pure code — makes HTTP call to RxNorm REST API, returns normalization result. Called as a code function in the normalization service, not as an agent node.

**Translation tool:** REST call to translation-service. Returns translated text. Called as code in services that need it, not as an agent node.

**Infermedica tool:** Takes endpoint name and request body. Adds App-Id, App-Key, Interview-Id headers. Returns structured response. Used exclusively by symptom-service Alpha flow as direct service calls, not as agent nodes.

**PDF reader tool:** Takes file bytes and file type. Runs PyMuPDF or OCR pipeline. Returns extracted text with page structure. Called as a code function in ingestion pipelines.

### 1.4 Human-in-the-Loop

LangGraph interrupt() pauses the graph at a defined node and surfaces a structured payload to the calling service. The service sends the interrupt to the browser via WebSocket. The user's response resumes the graph via Command(resume=...).

MAISYS uses human-in-the-loop at exactly two points:

**Emergency triage interrupt:** When triage level is `emergency` or `emergency_ambulance`, the graph interrupts before generating any explanation. An emergency alert is shown. The session halts — no normal result is generated.

**Drug contraindication interrupt:** When the interaction agent identifies a `contraindicated` severity pair (these two drugs must never be co-administered), the graph interrupts to surface a red-banner warning. The user must acknowledge before full results are displayed.

No other interrupts exist. All other agent execution is fully autonomous. The user is kept informed by progress events but never needs to intervene.

### 1.5 Streaming Agent Events to WebSocket

All agents publish typed progress events to Redis pub/sub using `shared/progress/publisher.py` as they execute each node. The WebSocket handler subscribes to `progress:{session_id}` and forwards every event to the browser in real time. See Section 5 for the full live display system.

### 1.6 How Agents Call Shared Services (Microservices Context)

Agents in drug-service cannot import code from translation-service. When an agent needs translation, it calls the translation-service REST API via httpx async client inside the tool node. The tool node handles the HTTP call, timeout, retry, and error mapping internally. The agent state receives a clean result or an error field. Services are never directly imported across service boundaries.

---

## 2. Multi-Agent Production Reliability

### 2.1 Problem: Looping

**What goes wrong:** An agent node produces output that triggers the same node again. Without a hard stop, the graph runs indefinitely consuming tokens and time.

**MAISYS solution:**
Every LangGraph graph has a `max_iterations` integer set at graph construction. This is an absolute hard limit — the graph engine refuses to execute more nodes than this limit regardless of state. Additionally, every node that can be revisited (retry nodes, loop-back nodes) has a `visit_count` field in the state. If any node's visit count reaches 2, the graph immediately transitions to the terminal error node rather than executing the node again.

Loop detection is enforced at the graph level, not relying on any individual node to self-terminate. The graph engine is the authority on when to stop.

Max iterations per graph:

| Graph | Max Iterations |
|---|---|
| Drug Lookup | 6 |
| Interaction (per pair) | 5 |
| Dosage | 6 |
| Comparison | 8 |
| Pharmacokinetics | 5 |
| Alternative | 6 |
| Drug Acquisition | 10 |
| Web Search (Drugs.com) | 4 |
| Paper Discovery | 15 |
| Visual Orchestrator | 4 |

### 2.2 Problem: Error Propagation

**What goes wrong:** A node fails and throws an exception. The exception propagates up through the graph, crashes the orchestrator, and the user receives a generic 500 error with no partial results.

**MAISYS solution:**
Every node is wrapped in a try/except block internally. Nodes never throw exceptions to the graph engine. Instead, they return a state update with an `error` field:

```
{"error": {"node": "rag_retrieval", "type": "QdrantTimeout", "message": "...", "recoverable": true}}
```

The next node in the graph checks the `error` field before executing. If `recoverable: true`, the next node may be a retry node or a fallback node. If `recoverable: false`, the graph transitions to the terminal node which assembles whatever partial results exist and returns them with a clear error label.

The user never receives a blank screen. They receive either: the full result, a partial result with a note about what failed, or a clear error message explaining what went wrong and what they can do.

Error events are published to the WebSocket in real time so the user sees: "Web search failed — returning results from local knowledge base only."

### 2.3 Problem: Latency

**What goes wrong:** Agents that chain multiple LLM calls add seconds of latency per step. A 6-step chain becomes a 30-second wait.

**MAISYS solution — three strategies:**

**Per-node timeout:** Every node has a configured maximum execution time. If the node exceeds this time (LLM call hangs, Playwright navigation stalls, Qdrant search is slow), the node's async call is cancelled, an error state is set, and the graph advances to the fallback path. Timeouts per node type:

| Node Type | Timeout |
|---|---|
| RAG retrieval (Qdrant) | 8 seconds |
| Sufficiency evaluation (LLM) | 10 seconds |
| Drug RAG section search | 8 seconds |
| Drugs.com web scrape | 20 seconds |
| SerpAPI web search | 12 seconds |
| LLM generation (cloud) | 40 seconds |
| LLM generation (local vLLM) | 90 seconds |
| Playwright browser action | 15 seconds per action |
| OCR per page | 30 seconds |

**Graph-level timeout:** Even if individual nodes respect their timeouts, a graph can accumulate latency. Every graph has a `graph_timeout_seconds` that starts when the graph begins. If the graph has not reached its terminal node by this time, it is forcibly terminated and partial results are returned.

**Rule engine fast path:** Before any agent is invoked, a rule engine checks whether the request can be answered without running an agent at all. Rules include: if the drug was queried in the last 12 hours and the result is cached → return cached result immediately. If the drug has only one active ingredient and it is a simple profile lookup with all fields present in PostgreSQL → return from database directly. If the query matches an exact pattern that the rule engine recognizes as a simple lookup → return structured response without LLM. Only if no rule fires does the agent orchestrator activate.

### 2.4 Problem: Cost

**What goes wrong:** Agents make multiple LLM calls per request. High-traffic periods consume unexpected token volumes and spike API costs.

**MAISYS solution:**
A token budget is set at graph initialization. Each node that makes an LLM call logs the token count to the running budget total in the graph state. If the running total exceeds the budget, subsequent LLM nodes are instructed to switch to the configured local fallback model (BioGPT, BioMedLM) for the remainder of the graph execution. The response quality may be slightly lower but the cost is contained.

Budget thresholds per graph (approximate tokens):

| Graph | Token Budget |
|---|---|
| Drug Lookup | 3,000 |
| Interaction (per pair) | 2,000 |
| Comparison (per drug) | 4,000 |
| Pharmacokinetics | 2,500 |
| Paper Discovery | 5,000 |
| Visual (chart generation) | 2,000 |

Budget overruns are logged and reported in the model-router-service metrics. The admin can see which features are consuming the most tokens and adjust accordingly (switch model, adjust prompts, enable more caching).

### 2.5 Problem: Unreliable Tool Usage

**What goes wrong:** A tool node receives malformed input, calls an external API that returns unexpected output, or returns a result that a downstream node cannot process — silently corrupting the result.

**MAISYS solution — three layers:**

**Input validation:** Every tool node validates its inputs against a Pydantic schema before making any external call. If inputs are invalid (drug name is empty, session ID is missing, search query is too long), the node returns an error state immediately without making the external call.

**Output validation:** Every tool node validates its output before updating the graph state. Qdrant results must be a list of Chunk objects. SerpAPI results must have at least one organic result with a link field. Drugs.com scrape results must contain at least one interaction record. If output validation fails, the tool node treats it as a recoverable error and triggers the retry or fallback path.

**Retry with exponential backoff:** Tool nodes that make external HTTP calls (SerpAPI, Qdrant, Drugs.com) retry on transient failures (network error, 429 rate limit, 503 service unavailable). Maximum 2 retries per tool call. Backoff: 1 second after first failure, 3 seconds after second failure. After 2 failed retries, the node returns a recoverable error state for the graph to handle.

### 2.6 Problem: Bad Observability

**What goes wrong:** An agent fails silently. Nobody knows which node failed, how long it took, how many tokens it used, or whether the fallback path was taken.

**MAISYS solution:**
Every agent execution generates a trace. A `trace_id` UUID is created at graph start and stored in the graph state. Every node emits a structured log event at start and completion including: trace_id, node name, agent name, session_id, duration_ms, token_count (if LLM call), tool_name (if tool call), output_summary (first 100 chars of output), error details (if any).

All trace events are written to:
- structlog → Loki (searchable logs)
- WebSocket pub/sub → frontend Agent Activity panel (real-time)
- PostgreSQL `agent_trace_log` table (stored for 30 days for debugging)

The admin panel shows a trace viewer: select any session, view the complete agent execution tree with timing per node, which fallback paths were taken, token costs per node, and any errors with their context. This is similar to LangSmith traces but stored internally.

---

## 3. Deterministic Orchestration Rules

These rules apply to every LangGraph graph across all services without exception.

### 3.1 Structured Output — Every LLM Node

Every LLM call inside an agent must use structured JSON output. The LLM is never asked to produce free text that a downstream node then tries to parse. The system prompt instructs the LLM to respond only with a JSON object matching a specific Pydantic schema. The response is immediately parsed with Pydantic.

If parsing fails → the node sends a corrective retry prompt: "Your previous response was not valid JSON. You must respond with only a JSON object matching this exact schema: {schema_str}. Do not add any explanation or preamble." Maximum 2 retry attempts. If both retries fail to produce valid JSON → the node returns an error state with `recoverable: false`.

Free-text generation (the actual response the user reads) happens only in the final generation step of the service layer after the agent has completed — not inside agent nodes. Agent nodes produce structured data. The service layer uses that structured data to prompt the primary LLM for user-facing text generation with streaming.

### 3.2 Stop Conditions — Explicit, Never Implicit

Every graph that contains a loop must have explicit stop conditions defined at graph construction time. Stop conditions are checked as the first operation of any node that can be the entry point of a loop. If any stop condition is true, the node immediately transitions to the terminal node without executing its main logic.

General stop conditions applied to all graphs:
- `state.iterations >= max_iterations` → terminal
- `state.elapsed_seconds >= graph_timeout` → terminal with partial results
- `state.error.recoverable == false` → terminal with error result
- `state.token_budget_exceeded == true` → switch to local model or terminal

Feature-specific stop conditions (symptom checker example):
- `infermedica_response.should_stop == true` → finalization
- `state.turns >= 8` → finalization
- `state.top_condition_probability >= 0.85` → finalization
- `state.probability_gap >= 0.50` → finalization

### 3.3 State Immutability Between Nodes

Once a field is written to the graph state by a node, downstream nodes treat it as immutable unless they are specifically the node responsible for updating that field. This prevents nodes from accidentally overwriting each other's results. Nodes only declare the specific fields they update in their return dictionary — they cannot overwrite fields they did not receive as their responsibility.

### 3.4 Idempotent Nodes

Every node is designed to be idempotent: if the same node is called twice with the same input state, it produces the same result. This is achieved by:
- Checking if the node's output fields are already populated in state before executing (skip if already done)
- Using deterministic operations (same query → same Qdrant search → same ranked results, given the knowledge base has not changed)
- For LLM calls: setting temperature to 0 for all structured output generation inside agents, ensuring consistent results

---

## 4. Node Audit — Code vs Agent

This section defines which operations in MAISYS are implemented as pure code functions and which are implemented as LangGraph agent nodes. The rule: if the operation is deterministic (same input always produces same operation, no conditional branching based on runtime content), it is code. If the operation requires LLM reasoning to decide what to do next, or has conditional branching that depends on retrieved content, it is an agent node.

### 4.1 Converted to Code Functions

These were previously considered as agent nodes but are now pure service functions, utility functions, or repository calls:

| Operation | Implementation | Location |
|---|---|---|
| RxNorm API call + normalization | Service function | `drug-service/services/normalization_service.py` |
| Drug pair combination generation | Utility function | `drug-service/utils/drug_pair_generator.py` |
| Brand/generic conversion | Service function (RxNorm call) | `drug-service/services/normalization_service.py` |
| Symptom stop condition check | Utility function | `symptom-service/utils/stop_condition.py` |
| Evidence list builder | Service function | `symptom-service/services/session_service.py` |
| Language detection | Utility function | `shared/chunking/token_counter.py` |
| File type detection (magic bytes) | Security utility | `shared/security/file_validator.py` |
| Stage 1 lab parsing (regex + scispaCy) | Service function | `lab-service/nlp/scispacy_parser.py` |
| Sufficiency chunk count gate | Utility function | `shared/embedding/similarity.py` |
| Session state read/write | Repository function | per-service `cache_repo.py` |
| Citation extraction from chunks | Utility function | per-service `utils/citation_mapper.py` |
| Conversation summary trigger check | Service function | `chatbot-service/services/window_service.py` |
| PDF page count check | Utility function | `shared/security/file_validator.py` |
| Triage level → color + action mapping | Service function | `symptom-service/services/triage_service.py` |

### 4.2 Remaining Agents

These are the agents that remain as LangGraph StateGraphs because they require conditional branching based on runtime content, multi-step state with dependent operations, or external automation:

| Agent | Service | Why Agent |
|---|---|---|
| Drug Lookup Agent | drug-service | RAG → sufficiency check (LLM) → conditional: generate OR web search |
| Interaction Agent (per pair) | drug-service | RAG → sufficiency → conditional: Drugs.com scrape OR SerpAPI OR generate |
| Dosage Agent | drug-service | RAG → sufficiency → conditional calc paths (weight/eGFR/hepatic) → generate |
| Comparison Agent | drug-service | Parallel retrieval for N drugs → merge → synthesize — state-dependent |
| Pharmacokinetics Agent | drug-service | RAG → sufficiency → CYP cross-reference → conditional generate |
| Alternative Agent | drug-service | Class ID from RAG → class-wide search → rank — sequential dependent |
| Drug Acquisition Agent | drug-service | Search → scrape → extract → chunk → embed → upsert — 6 dependent steps |
| Web Search Agent (Drugs.com) | drug-service | Multi-step Playwright: navigate → enter names → click → wait → extract |
| Paper Discovery Agent | research-service | Keyword extract → API search → web supplement → rank → download (with failure branching) → ingest |
| Visual Orchestrator + Chart Agent | all services | Content detection → agent selection → HTML generation → validation |
| Visual Orchestrator + Infographic Agent | all services | Same conditional pipeline |
| Visual Orchestrator + Diagram Agent | all services | Same conditional pipeline |

### 4.3 Benefit of This Audit

Removing 14 unnecessary agent nodes from the system: reduces average latency per request by 2–8 seconds (no agent graph startup overhead for deterministic operations), reduces token costs (no LLM call for operations that do not need LLM reasoning), improves reliability (pure code does not fail unpredictably), and simplifies debugging (code functions have straightforward stack traces vs agent traces).

---

## 5. Live Real-Time Agent Activity Display

### 5.1 WebSocket Event Types

Every agent execution publishes a stream of typed events to `progress:{session_id}` in Redis. The WebSocket handler forwards every event to the browser immediately. Events have this structure:

```
agent_start:
{
  "event": "agent_start",
  "agent_name": "InteractionAgent",
  "graph_name": "drug_interaction",
  "pair": "warfarin + aspirin",
  "trace_id": "uuid",
  "session_id": "uuid"
}

node_start:
{
  "event": "node_start",
  "agent_name": "InteractionAgent",
  "node_name": "rag_retrieval",
  "input_summary": "Searching DRUG INTERACTIONS section for warfarin, aspirin"
}

node_complete:
{
  "event": "node_complete",
  "agent_name": "InteractionAgent",
  "node_name": "rag_retrieval",
  "duration_ms": 312,
  "output_summary": "5 chunks retrieved from drug RAG",
  "tokens_used": 0
}

node_skipped:
{
  "event": "node_skipped",
  "agent_name": "InteractionAgent",
  "node_name": "web_search",
  "reason": "RAG sufficiency passed — web search not needed"
}

node_error:
{
  "event": "node_error",
  "agent_name": "InteractionAgent",
  "node_name": "rag_retrieval",
  "error_type": "QdrantTimeout",
  "error_message": "Search exceeded 8 second timeout",
  "will_retry": true,
  "retry_count": 1
}

tool_call:
{
  "event": "tool_call",
  "tool_name": "drugs_com_scraper",
  "input_summary": "Navigating Drugs.com interaction checker: warfarin + aspirin"
}

tool_result:
{
  "event": "tool_result",
  "tool_name": "drugs_com_scraper",
  "success": true,
  "output_summary": "1 major interaction found",
  "duration_ms": 4200
}

agent_complete:
{
  "event": "agent_complete",
  "agent_name": "InteractionAgent",
  "pair": "warfarin + aspirin",
  "total_duration_ms": 5100,
  "total_tokens": 840,
  "result_summary": "Major interaction: increased bleeding risk",
  "source_tier": "web"
}
```

### 5.2 Frontend Agent Activity Panel

The frontend renders a live collapsible "Agent Activity" panel during any agent-powered operation. The panel appears automatically when the first `agent_start` event arrives and closes when the last `agent_complete` event arrives.

**Panel elements:**
- Each agent shown as a row with its name and target (e.g. "Interaction Agent — warfarin + aspirin")
- Each node shown as an inline step within the agent row
- Node states: pulsing blue dot (running), green checkmark + duration (complete), grey dash (skipped by rule engine), red X + retry count (error/retrying), orange icon (fallback path taken)
- Tool calls shown as indented sub-steps within the node they belong to
- When Drugs.com scraping is triggered: "🌐 Fetching from Drugs.com..." appears as a tool step with live timing
- Token count shown per agent on completion
- Total elapsed time shown per agent

**For multi-pair drug interaction (6 pairs):** Six agent rows appear, each advancing through their own node pipeline independently and concurrently. The user sees all 6 running in parallel with their own progress indicators.

**Panel behavior:** Collapsible (user can hide it). Persists in a collapsed "Summary" state after all agents complete, showing: total agents run, total tokens used, whether any fallbacks were triggered, and which tiers were used (local RAG / web).

This gives users full transparency into what the system is doing on their behalf — no black box.

---

## 6. Live Visual Generation

### 6.1 Visual Generation Starts in Parallel

Visual generation does not wait for the main LLM response to finish streaming. As soon as the visual orchestrator detects a trigger in the incoming response tokens (the orchestrator scans tokens as they stream), it immediately starts the visual agent in a separate async task. The chart LLM generates the HTML while the main response is still streaming its last sentences.

**Sequence visible to user:**
```
[0.0s]  Main response starts streaming — text appears word by word
[0.3s]  Orchestrator detects "comparison" + numeric data in streaming tokens
[0.3s]  Visual agent starts in background async task
[2.1s]  Main response finishes streaming
[2.3s]  WebSocket event: visual_ready — HTML payload arrives
[2.3s]  Chart iframe appears below the completed response
```

The chart or infographic appears within 0.2–0.5 seconds after the main text completes — effectively simultaneous from the user's perspective.

### 6.2 Visual Ready WebSocket Event

When the chart LLM finishes generating the HTML, the visual agent publishes a `visual_ready` WebSocket event:

```
{
  "event": "visual_ready",
  "visual_type": "chart",
  "chart_subtype": "bar",
  "title": "Drug Interaction Severity Overview",
  "html_content": "<html>...(full self-contained HTML)...</html>",
  "visual_id": "uuid",
  "session_id": "uuid"
}
```

The frontend receives this event and renders the HTML immediately in a sandboxed iframe below the response. No page reload, no additional HTTP request — the HTML arrives through the already-open WebSocket connection.

### 6.3 Visual Validation Before Delivery

Before publishing the `visual_ready` event, the visual agent validates the generated HTML:
- HTML must contain exactly one `<canvas>` element (for charts) or one `<svg>` root (for diagrams) or at least 3 `.card` elements (for infographics)
- HTML must not contain external script tags pointing to domains other than cdnjs.cloudflare.com
- HTML string must be parseable by BeautifulSoup without errors

If validation fails: chart LLM retries with a corrective prompt. Maximum 2 retries. If both retries fail: the visual event is not published, the response is returned without a visual, and a `visual_failed` event is published (displayed in the Agent Activity panel as an error — the user is not bothered by a broken visual).

### 6.4 Chart LLM — Open Source Models

The Chart LLM uses code-generation models specialized for producing HTML/JS/CSS. Open-source models are first-class options — not fallbacks.

| Model | Type | HuggingFace / Provider | Notes |
|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct | Local (vLLM) | `Qwen/Qwen2.5-Coder-7B-Instruct` | Excellent HTML/JS generation, 7B efficient |
| DeepSeek-Coder-V2-Lite-Instruct | Local (vLLM) | `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct` | 16B MoE (memory-efficient), strong output |
| CodeLlama-7b-Instruct | Local (vLLM) | `meta-llama/CodeLlama-7b-Instruct-hf` | Widely supported, reliable HTML generation |
| WizardCoder-Python-7B | Local (vLLM) | `WizardLM/WizardCoder-Python-7B-V1.0` | Code-focused, strong structured output |
| GPT-4o | Cloud | `gpt-4o` | Highest quality, use when precision matters |
| Claude 3.5 Sonnet | Cloud | `anthropic/claude-3-5-sonnet-20241022` | Strong code generation, long context |

Admin selects active chart LLM via model-router-service with role `chart`. Switching from cloud to local (Qwen2.5-Coder) saves significant cost since chart generation is frequent across all services.

---

## 7. Visual Agents — All Services

### 7.1 Overview

Three visual agents (Chart, Infographic, Diagram) are shared library modules available to all five module services. They run in-process within each service — not separate microservices. The chart LLM can be any cloud or open-source code-generation model (see Section 6.4).

### 7.2 Visual Orchestrator

Runs automatically as a background async task as the main LLM response streams. Scans incoming response tokens for visual trigger patterns. When a trigger is detected, the corresponding agent is started immediately in a concurrent async task.

**Detection rules — Chart Agent triggers:**
- Response contains a table with at least 2 columns of numeric data
- Response mentions specific values for multiple patient groups (dosage comparison, lab values vs ranges)
- Response contains drug interaction severity for multiple pairs
- Response contains statistics or prevalence rates for multiple conditions
- Response contains "compared to" or "versus" alongside numeric data
- Response contains pharmacokinetic parameters for one or more drugs

**Detection rules — Infographic Agent triggers:**
- Response contains 4+ key medical facts about one topic as a structured list
- Response describes one drug's complete key properties (class, mechanism, indications, side effects)
- Response explains one lab test comprehensively (what it is, what it measures, normal range, what abnormal means)
- Response summarizes one medical condition as an educational overview

**Detection rules — Diagram Agent triggers:**
- Response describes a mechanism of action (drug → receptor → effect chain)
- Response describes a timeline (disease progression, treatment schedule, symptom onset sequence)
- Response describes body system or organ involvement
- Response describes a multi-step process (how a test is performed, drug absorption and metabolism pathway)

**Multiple triggers:** Chart Agent takes priority for numeric comparisons. Infographic for single-topic facts. Diagram for processes and mechanisms. Only one agent runs per response.

**No trigger:** No visual generated. This is the most common case for simple factual responses.

### 7.3 Chart Agent

Generates interactive Chart.js charts embedded in self-contained HTML. Chart LLM receives the numeric data portions of the response and a system prompt specifying: generate one Chart.js chart in complete standalone HTML, use Chart.js CDN only, no external resources, appropriate medical color palette (green for normal/safe, amber for caution, red for warning/critical), include clear labels and legend.

Chart types: bar (most common — severity distribution, values vs ranges, dosage comparison), line (PK concentration-time curves, trends), radar (multi-dimensional drug comparison).

### 7.4 Infographic Agent

Generates CSS card-based summaries. Chart LLM receives the key facts from the response and instructions to generate self-contained HTML with styled cards. Each card: title, body text, optional color accent based on medical significance. Color coding: green (positive/normal), amber (caution), red (warning).

### 7.5 Diagram Agent

Generates SVG-based diagrams embedded in HTML. Chart LLM identifies the best diagram type for the content and generates it as inline SVG. Must use only web-safe fonts and pure SVG geometry — no external resources. Diagrams include: mechanism chains (horizontal with arrows), timelines (horizontal with date/stage markers), body system involvement (simplified anatomy), process flowcharts.

---

## 8. Real-Time Streaming — All Services

Every module service streams LLM-generated text token by token to the browser via WebSocket. This is not optional for any service — it is a platform requirement. The user never waits for a complete response to appear. Text builds word by word.

### 8.1 chatbot-service

Main response streams token by token from the primary LLM. Enhancement layer runs before streaming starts (adds 3–8 seconds of processing that the user sees as the "Enhancing with medical context..." progress stage). After enhancement: streaming begins immediately.

### 8.2 drug-service

Every LLM-generated drug explanation streams token by token. For multi-pair interaction analysis: each pair result streams as it becomes available — the user sees pair 1 explanation streaming, then pair 2, then pair 3 (or multiple streaming concurrently if the UI supports parallel display). The overall risk summary streams last.

Dosage calculator explanation streams. Comparison table narrative streams. Pharmacokinetics summary streams. All 12 features produce streamed output.

### 8.3 symptom-service

Rephrased follow-up questions stream token by token (typically short — 1–2 sentences — but streaming still improves perceived responsiveness). Final condition explanation streams. Triage summary streams. Background info from Medical RAG streams.

### 8.4 lab-service

Per-test explanations stream as they generate. Because explanations are generated concurrently (5 at a time), the user sees multiple explanations streaming simultaneously — explanation for Hemoglobin, WBC, and Glucose building at the same time. Each explanation streams into its own card in the UI.

Overall report summary streams. Urgency assessment streams.

### 8.5 research-service

Paper chat responses stream token by token. Summaries stream as they generate. Q&A generation streams each question-answer pair as it is produced. Comparison narrative streams. All NLP tool outputs stream.

---

## 9. chatbot-service — Full Detail

### 9.1 Three-LLM Architecture

**Medical LLM (primary):** Generates the final user-facing response. Receives enhanced context (validated and ranked by the enhancement LLM), conversation history, health profile, and user query. May be cloud or local depending on admin configuration.

**Medical LLM enhancement layer (secondary):** Receives raw retrieved RAG chunks and the user query. Performs three operations: removes irrelevant chunks, ranks remaining chunks by relevance, and generates a brief retrieval summary explaining why these chunks are relevant. The primary LLM receives this pre-processed context. Always a fast, lower-cost model. Never the primary LLM model — this keeps the enhancement step cheap.

**Chart LLM (visual):** Generates HTML/JS/CSS for all three visual agents. Always configured via model-router-service role `chart`. Can be cloud or open-source (see Section 6.4).

### 9.2 Complete Message Pipeline

**Step 1 — Validation:** API Gateway validates JWT. Route handler validates request body with Pydantic.

**Step 2 — Emergency pre-check:** safety-service called synchronously. Emergency detected → return emergency WebSocket event, halt pipeline.

**Step 3 — Input processing (by type):**
- Text: use directly
- Voice: STT service call → transcript → treat as text
- Image: vision LLM → description text + image context tag
- File (PDF/DOCX): text extraction → chunk → embed → upsert to session namespace in Qdrant

**Step 4 — Translation:** If Arabic, translate to English via translation-service.

**Step 5 — RAG retrieval:** Parallel asyncio.gather: Medical RAG search + Drug RAG search (conditional on query content) + session file namespace search (if files uploaded). Merge, deduplicate, rank, take top 8 chunks.

**Step 6 — Sufficiency evaluation:** Chunk count gate (code). If passes → proceed. If fails → SerpAPI web search with Medical RAG-appropriate query.

**Step 7 — Enhancement layer:** Fast model processes chunks + query → returns filtered ranked chunks + retrieval summary.

**Step 8 — Conversation history:** Load last 10 messages full + rolling summary of earlier messages from database.

**Step 9 — Health profile injection:** If health profile exists, format and prepend to system prompt.

**Step 10 — KV cache check:** If system prompt hash matches a cached `past_key_values` entry (local LLM) or the system prompt was already sent to cloud provider within cache TTL → use cached prefix.

**Step 11 — Primary LLM streaming:** Response streams token by token via WebSocket.

**Step 12 — Visual orchestrator (parallel):** Starts concurrently with Step 11. Scans streaming tokens for visual triggers. If triggered → visual agent starts immediately.

**Step 13 — Citation extraction:** After streaming completes, extract citations from chunk metadata. Publish citations WebSocket event.

**Step 14 — Safety wrap:** Disclaimer and profile-aware warnings appended. Published as WebSocket event.

**Step 15 — Database save:** User message and assistant response saved to PostgreSQL. Rolling summary triggered if needed (async).

**Step 16 — TTS (if voice mode):** Response text converted to audio. Audio streamed to browser.

### 9.3 KV Cache

**Local LLM KV cache:** `shared/llm_client/kv_cache_manager.py` stores `past_key_values` tensors keyed by SHA-256 hash of the system prompt. Maximum 8 entries in memory per service instance. Saves 20–40% GPU computation per request for large local models.

**Cloud prefix caching:** Anthropic system prompt marked with `cache_control: ephemeral` → 25% input token cost on hit, 5-minute validity. OpenAI automatic for prompts >1024 tokens → 50% cost on hit.

**Semantic cache:** Redis caches complete LLM responses keyed by query embedding hash. Threshold: 0.92 cosine similarity. TTL: 6 hours medical, 12 hours drug, 24 hours reference content.

### 9.4 Sliding Window Conversation Memory

Last 10 messages kept in full. Older messages compressed into a rolling summary (max 300 tokens). Summary updated every 5 new messages by extending the existing summary — never re-summarizing from scratch. Summary captures: medical topics discussed, questions asked, key information provided, drugs or conditions mentioned, unresolved follow-ups. Token budget: 300 summary + max 2000 recent messages. If recent messages exceed 2000 tokens, trim oldest first (keeping minimum 4 messages).

### 9.5 Vision Model Pipeline

Image input: validated (MIME type, magic bytes, size, dimensions) → base64 encoded → vision LLM call with medical context prompt. Vision LLM returns structured text description. This text feeds into the main pipeline as additional context.

Scanned PDF detection: if PyMuPDF returns < 50 meaningful characters per page across first 3 pages → classify as scanned → pages rendered as images → vision LLM analyzes each page.

Documents (PDF/DOCX) sent to text extraction, never to vision model. Only actual image files and scanned PDFs use the vision path.

### 9.6 File Upload to Session RAG

User uploads PDF or DOCX: text extracted → chunked (400-token target, 80-token overlap) → dual embedded (MiniLM + PubMedBERT) → upserted to session-specific Qdrant namespace. All subsequent messages search this namespace in addition to main RAG. Source labeled "Uploaded Document" in citations. Content persists for session lifetime.

### 9.7 Share URL

Generates unique token with configurable expiry (default 7 days). Read-only for recipients — full conversation viewable, no new messages. Revocable by session owner at any time.

### 9.8 Export

TXT/DOCX/PDF via export-service. Includes: all messages with timestamps, all citations, embedded visual PNGs (Playwright renders HTML → PNG for export), disclaimer footer. Arabic sessions: RTL layout, Noto Sans Arabic font.

---

## 10. drug-service — Full Detail

### 10.1 Service Purpose

Comprehensive drug information hub handling 12 features. All features share the RxNorm normalization pipeline, two-tier RAG retrieval, and LangGraph agent orchestration. Visual agents auto-trigger on structured data.

### 10.2 KV Cache

Same KV cache architecture as chatbot-service — applied to all LLM calls within drug-service. Local `past_key_values` for local LLMs. Cloud prefix caching for Anthropic and OpenAI. Semantic cache for complete drug feature responses in Redis.

### 10.3 RxNorm Normalization Pipeline (Code — Not Agent)

Pure service function in `normalization_service.py`. Called before any feature executes. Steps:

1. RxNorm REST API `/rxcui.json?name={name}&search=1` for each drug name
2. Canonical name via `/rxcui/{rxcui}/property.json?propName=RxNorm Name`
3. Active ingredient decomposition via `/rxcui/{rxcui}/related.json?tty=IN` for combination drugs
4. Deduplication: same RxCUI from two different input names → merge + flag warning
5. scispaCy NER fallback: if RxNorm returns nothing → extract entity + fuzzy match against drug name index
6. RxNorm API down fallback: Redis cache (24h TTL) → scispaCy + fuzzy match

Output: list of drug objects with `original_name`, `canonical_name`, `rxcui`, `active_ingredients`, `duplicate_flag`.

### 10.4 The 12 Features

**Drug Profile Lookup:** Drug Lookup Agent. No section filter — all sections. Top 8 chunks from all four Drug RAG sources. LLM generates structured profile: names, class, mechanism, indications, side effects, contraindications, dosage summary, forms, storage. Infographic auto-triggers: drug profile card.

**Brand ↔ Generic Conversion:** Pure code — RxNorm normalization result. No RAG, no LLM. Cached 24h.

**Drug Class Browser:** Drug Lookup Agent with class-level query (no drug name filter). Returns all drugs in class found in RAG. LLM organizes results into class overview, shared mechanism, drug table with distinguishing notes. Chart auto-triggers: comparison chart of class members.

**Drug-Drug Interaction Checker:** All unique pairs generated by code. One Interaction Agent instance per pair, all running concurrently (asyncio.gather, semaphore 5). Per pair, three-tier retrieval:

**Tier 0 — DDIMDL Structured Lookup (PostgreSQL, sub-100ms):** Before any RAG or web search, the agent does an exact-match query on `ddimdl_interactions` using the DrugBank IDs resolved from RxNorm normalization. Query checks both orderings: `(id1=A AND id2=B) OR (id1=B AND id2=A)`. If found: return interaction text immediately → LLM generates plain-language explanation and severity classification from the interaction text → source label: `📊 Structured Database (DrugBank 5.1.3)` → cache in Redis 12h → skip Tier 1 and Tier 2.

**Tier 1 — Drug RAG (Qdrant):** If no DDIMDL match, search with `section_name: DRUG INTERACTIONS` filter. This now includes both Drugs.com chunks and DDIMDL embeddings. Sufficiency: chunk_count ≥ 3 AND confidence ≥ 0.75. If sufficient: LLM generates response → source label: `✅ Local Knowledge Base`.

**Tier 2 — Drugs.com Live Scrape (Playwright agent):** If RAG insufficient, agent navigates drugs.com/drug_interactions.html, enters drug names one by one, clicks Check Interactions, waits for results DOM, extracts with BeautifulSoup → LLM generates response → source label: `🌐 Drugs.com`.

After all pairs complete: code aggregates overall risk. Chart auto-triggers: severity distribution bar chart.

**Drug-Food Interaction Checker:** Interaction Agent. RAG filter: `DRUG INTERACTIONS` + food keyword. Web search fallback.

**Drug-Disease Contraindication Checker:** Interaction Agent. RAG filter: `CONTRAINDICATIONS`. Distinguishes absolute vs relative. Suggests alternatives.

**Pregnancy and Breastfeeding Safety:** Interaction Agent. RAG filter: `USE IN SPECIFIC POPULATIONS`. FDA category, trimester guidance, breastfeeding safety. Infographic auto-triggers: pregnancy safety card.

**Dosage Calculator:** Dosage Agent. RAG filter: `DOSAGE AND ADMINISTRATION`. Extracts standard adult dose. If weight provided: mg/kg calculation (code). If eGFR provided: renal adjustment table lookup (code). If Child-Pugh: hepatic adjustment (code). Maximum daily dose prominently stated. Mandatory disclaimer appended.

**Drug Alternative Finder:** Alternative Agent. Class identification from RAG → class-wide search → ranked alternatives with mechanism comparison, relative efficacy, key differences, availability notes. Infographic auto-triggers.

**Drug Comparison:** Comparison Agent. Drug Lookup Agent for each drug concurrently. Builds side-by-side table: class, mechanism, indications, dosing, side effects, interactions, CYP, cost tier. **DDIMDL molecular enrichment:** if both drugs are found in `ddimdl_drug_features`, their SMILES strings and shared protein targets are included in the comparison prompt. The LLM notes structural similarity (shared SMILES substructures) or structural distinction, and flags shared protein targets as evidence of related mechanism of action. Clinical preference summary. Chart auto-triggers: radar chart across dimensions.

**Pharmacokinetics Viewer:** Pharmacokinetics Agent. RAG filter: `PHARMACOKINETICS`. Structured PK parameters: bioavailability, Tmax, Vd, protein binding, CYP enzymes, half-life, elimination route. **DDIMDL molecular enrichment:** if drug is found in `ddimdl_drug_features`, its enzyme field (pipe-separated UniProt IDs) is cross-referenced against the CYP enzyme mapping: P08684→CYP3A4, P10635→CYP2D6, P11712→CYP2C9, P05177→CYP1A2, P33261→CYP2C19, P10632→CYP2C8, Q06520→CYP2A6. Matched CYP enzymes are added to the LLM prompt as structured molecular data: "Molecular data indicates this drug is metabolized by: CYP3A4, CYP2D6." This supplements RAG content with authoritative DrugBank molecular information. CYP interaction identification. Structured table + plain summary. Chart auto-triggers: PK parameter bar chart.

**Off-Label Use Explorer:** Drug Lookup Agent. No section filter. Identifies off-label uses in retrieved content. Evidence level per use: case reports / observational / RCTs / guidelines. Regulatory status noted. Physician supervision disclaimer.

### 10.5 Interaction Agent — Drugs.com Live Flow (Exact Steps)

When Drug RAG is insufficient for a drug-drug pair:

1. Playwright headless Chromium launches
2. Navigate to `https://www.drugs.com/drug_interactions.html`
3. For each drug name: locate the interaction checker text input field, type the drug name, wait for autocomplete dropdown to appear (max 3 seconds), select the top autocomplete suggestion or press Enter if no dropdown appears
4. After all names entered: locate and click the "Check Interactions" button
5. Wait for the interaction results panel to appear in the DOM (max 15 seconds timeout)
6. Extract HTML of the results panel
7. BeautifulSoup parses: for each interaction block, extract severity badge text, drug pair names, interaction description paragraphs, clinical significance text, recommendation text
8. Assemble structured result: `{drug_a, drug_b, severity, mechanism, clinical_significance, recommendation}`
9. Pass to medical LLM for formatting into standard MAISYS interaction response with plain-language explanation
10. Source label: "🌐 Drugs.com", citation URL: `https://www.drugs.com/drug_interactions.html`
11. Cache in Redis: key `web_interaction:{rxcui_a}:{rxcui_b}`, TTL 6 hours

### 10.6 Drug Data Acquisition Agent

When a user queries a drug with zero Drug RAG results: agent activates asynchronously. Searches Drugs.com for the drug name, navigates to its page, extracts full content (Playwright + BeautifulSoup), chunks using general drug chunking strategy, embeds (dual embedding), upserts to Qdrant drug collections, writes basic PostgreSQL record. On completion: service retries the RAG search for the current session. Drug URL added to retry pipeline for full PDF scraping.

---

## 11. symptom-service — Full Detail

### 11.1 Note on GP Reviewer

GP = **General Practitioner** — a licensed medical doctor. The GP review system has qualified physicians review and validate Beta training data before it enters the fine-tuning pipeline. This ensures every training record has been verified by a clinician. GP reviewers are medical professionals with `gp_reviewer` role in the system — they are not researchers, students, or automated validators.

### 11.2 Alpha Mode — Complete Session Flow

All stop-condition checking, evidence building, and language detection are pure code functions — not agents. Only the LLM tasks (rephrase, parse, explain, triage summary) use the LLM, and these are direct LLM calls in the service layer — not agents.

**Session start:** UUID generated as Interview-Id. Initial form: age, sex, chief complaint, language.

**Emergency pre-check (code):** safety-service scans chief complaint. Emergency → halt immediately.

**Translation (code, if Arabic):** translation-service call. English text for Infermedica.

**Infermedica /parse (service function):** httpx POST to `https://api.infermedica.com/v3/parse`. Returns symptom ID mentions.

**scispaCy fallback (code):** if /parse returns zero mentions → NER on text → `/symptoms?phrase=` search for each extracted entity.

**Evidence list build (code):** convert mentions to evidence array. Store in Redis session state.

**First /diagnosis call (service function):** returns top conditions + first clinical question.

**LLM Task 1 — Question rephrase:** Direct LLM call. Clinical question → natural language. Translate back to Arabic if needed.

**User submits answer.**

**LLM Task 2 — Answer parse:** Direct LLM call. User free text → present/absent/unknown. Conservative: ambiguous → unknown.

**Evidence update (code):** append new evidence item. Increment turn counter. Save to Redis.

**Stop condition check (code, 4 gates):**
1. Infermedica `should_stop: true`
2. `turns >= 8`
3. Top condition probability `>= 0.85`
4. Probability gap first–second `>= 0.50`

Any gate true → finalization. None true → next /diagnosis call.

**Finalization — /triage (service function):** Returns triage level.
Emergency triage → LangGraph interrupt: emergency alert surfaced. Session halts.

**Finalization — /conditions/{id} (service function, 3 concurrent calls):** Full condition details for top 3.

**Medical RAG enrichment (concurrent, service function):** Medical RAG searched for background info on top condition. Filter: `content_type: disease_condition`. 3–4 chunks.

**LLM Task 3 — Results explanation (streaming):** Conditions + Infermedica details + RAG chunks → LLM generates plain-language explanation. Streams token by token.

**LLM Task 4 — Triage summary (streaming):** What urgency level means + what to do next + warning signs. Streams.

**Safety wrap (code):** Disclaimer appended. Profile warnings if applicable.

**Save to PostgreSQL (code):** Session + results records.

**Visual orchestrator:** If explanation contains structured condition data → Infographic Agent generates condition overview cards.

### 11.3 Beta Mode

Access requires all three consent gates completed (checked at route middleware — 403 before service code if any gate missing):
- Gate 1: Explicit consent screen acknowledgment + timestamp
- Gate 2: Account settings Beta participation toggle ON + timestamp
- Gate 3: Onboarding flow 3-step completion + timestamp

Beta disclaimer shown at start of every session. Cannot be dismissed.

**Beta session flow:** Emergency check → fine-tuned LLM via vLLM (system prompt: medical assessment assistant with safety reminders) → conversational loop (up to 6 turns) → final assessment + triage estimate → Beta warning banner on every response.

**Anonymization (before any storage, as code function):**
- user_id → SHA-256 hash (irreversible)
- PII removal: regex (phone, email, names) + medical NER (distinguishes drug names from person names)
- Date shifted ±30 days
- Location references below city level removed

Anonymized record → `beta_review_queue` table with `gp_reviewed: false`.

**GP Review Actions:** Approve (add to training as-is), Correct and Approve (GP corrects labels, corrected version added), Reject (exclude), Flag for Discussion. Only Approved and Correct+Approved records enter the training dataset.

---

## 12. lab-service — Full Detail

### 12.1 Accepted File Types

PDF (digital and scanned), JPG, PNG, WEBP, and **DOCX**. All file types go through the same six-layer security validation before processing.

### 12.2 File Routing (Code — Not Agent)

Four processing paths determined by code logic:

**Path A — Digital PDF (selectable text):**
PyMuPDF attempts text extraction. If extracted text across first 3 pages > 100 meaningful characters → proceed with text extraction. All pages extracted with `[Page N]` markers.

**Path B — Scanned PDF:**
If PyMuPDF returns < 100 chars in first 3 pages → classify as scanned. Each page rendered as image. OCR engine applied per page (PaddleOCR → Mistral → LightOn → vision LLM fallback chain). Results assembled in page order.

**Path C — Image file (JPG, PNG, WEBP):**
Vision LLM receives base64-encoded image with specialized lab report extraction prompt: "Extract every test name, result value, unit, and reference range visible in this lab report image. If you see abnormal flags (H/L/HIGH/LOW/CRITICAL), record them. Return as structured list." Vision LLM output treated as extracted text and passed to parsing pipeline.

**Path D — DOCX file:**
python-docx opens the file. Two parallel extractions:
- Table extraction: `document.tables` → each Word table extracted row by row. Header row detected (first row, or rows with bold/heading style). Each data row formatted as `Header: Value` pairs matching the universal table format used across all sources.
- Paragraph extraction: all non-empty paragraphs in document order. Paragraphs matching lab result patterns (text containing numbers + medical units) flagged for parsing.

Both outputs merged → passed to hybrid parsing pipeline.

**Progress events by path:**
Path A: "Extracting text from your lab report..."
Path B: "Analyzing scanned document — this may take a moment..."
Path C: "Analyzing lab report image..."
Path D: "Reading lab report document..."

### 12.3 Hybrid Parsing Pipeline (Two Stages — Code + LLM)

**Stage 1 — Rule-based pre-parser (code):**
Regex patterns detect common lab report line formats (table-structured, inline colon-separated, column-aligned). scispaCy NER identifies medical entity types: test names, measurement units, anatomical qualifiers. Output: candidate list of `{test_name, value, unit, reference_range_low, reference_range_high, flag, section_panel}` — some fields may be null.

**Stage 2 — LLM structured validator:**
Medical LLM receives raw extracted text + Stage 1 candidate list. Instruction: review raw text vs candidates, correct misidentified values, add missed tests, remove false positives (headers/notes parsed as tests), return validated JSON array. Output: `[{"test_name": "Hemoglobin", "value": "14.2", "unit": "g/dL", "reference_range": "12.0-16.0", "status": "normal", "section": "CBC"}, ...]`

Progress: "Found {n} tests — generating explanations..."

### 12.4 Concurrent Explanation Generation

All per-test LLM explanations generated concurrently (asyncio.gather, semaphore 5). Each explanation streams token by token into its own test card in the UI.

**For each test, LLM generates (streaming):**
1. What this test measures (1 sentence)
2. What the result means (1–2 sentences, contextualized to normal/high/low/critical)
3. For abnormal: possible causes and what it may indicate
4. Factors that can affect the result
5. Urgency guidance for this individual test

Medical RAG enrichment: top 3 chunks from Medical RAG for this test name (filter: `content_type: lab_test`). If RAG returns nothing → LLM proceeds with its own knowledge. No failure, no fallback needed.

**Per-test progress events:**
"Explaining test 1 of 24: Hemoglobin..."
"Explaining test 5 of 24: White Blood Cell Count..."
(updates after each group of 5 completes)

### 12.5 Overall Report Summary (Streaming)

After all per-test explanations complete: medical LLM generates holistic summary (streams token by token): count normal vs abnormal, most significant abnormal findings, overall urgency level (`none` / `routine` / `soon` / `urgent`), 3–4 synthesizing sentences.

Urgency is conservative — when in doubt, higher urgency level recommended.

### 12.6 Automatic Visuals

Chart Agent always auto-triggers for lab results: Chart.js bar chart of all test values relative to reference ranges. Bars color-coded green/orange/red. Tests grouped by lab panel with tab navigation. Appears live via WebSocket visual_ready event.

Infographic Agent always auto-triggers: summary cards for each abnormal test. Card contains: test name, value + unit, status badge, reference range, most important plain-language fact.

### 12.7 Follow-Up Chat Workspace

Same pipeline as chatbot-service main message pipeline:
- Emergency check → RAG retrieval (Medical RAG) → enhancement layer → primary LLM streaming → citations → visual orchestrator → safety wrap
- Full session context: all extracted test results and explanations available as context
- STT/TTS voice support
- Vision LLM in chat (for follow-up image uploads)
- Visual agents auto-trigger
- KV cache for repeated questions about the same report

---

## 13. research-service — Full Detail

### 13.1 Session Structure

Each research session is a workspace. Contains: papers (uploaded or discovered), paper chat history, NLP tool outputs, per-session Paper RAG Qdrant collection. Sessions have titles, are persistent, and can be shared read-only.

### 13.2 Paper Chat — Full Feature Parity with Chatbot

Research paper chat is a full-featured conversational interface with the same capabilities as chatbot-service:

**KV cache:** Same local `past_key_values` caching and cloud prefix caching as chatbot-service. System prompt for paper chat (instructions + paper context injections) is identical on every turn → strong cache hit rate.

**STT/TTS:** Voice input and voice output in paper chat. Same STT/TTS providers and selector as chatbot-service.

**Vision LLM in chat:** User can upload an image while chatting (e.g. screenshot of a figure from a paper not in the workspace, or a chart from a paper being discussed). Vision LLM analyzes it and incorporates into the response. Same Playwright scanned-page detection for uploaded paper PDFs.

**Sliding window conversation memory:** Same 10-message full window + rolling summary (max 300 tokens) pattern. Summary captures which papers have been discussed, which sections were cited, which questions were answered, open research questions.

**Visual agents:** Chart, Infographic, Diagram agents auto-trigger in paper chat responses. Research responses frequently contain statistical comparisons (chart), study summaries (infographic), and methodology flowcharts (diagram).

**Health profile injection:** If user has a health profile, it is injected into the system prompt: "Based on your profile (diabetic patient, 45 years old), consider the clinical relevance of these findings for someone like you." Adds personalization to how findings are explained.

**Export of chat history:** TXT/DOCX/PDF export of the full paper chat conversation, including citations, via export-service.

**Share URL:** Research sessions shareable as read-only (full chat history + paper workspace visible to recipient, no new messages).

**Streaming:** All responses stream token by token.

### 13.3 Paper Chat Pipeline

**Step 1 — Validation + emergency check:** Standard.

**Step 2 — Query scope detection (code):** Determines which papers to search. If user mentions a paper title or author → filter to that paper's collection. If query is general → search all papers in session.

**Step 3 — Paper RAG retrieval:** Dual embedding search on `papers_{session_id}_minilm` and `papers_{session_id}_pubmedbert`. Optional filters: specific paper_id, specific section. Merge, deduplicate, rank, top 5 chunks.

**Step 4 — Sufficiency check:** If < 2 chunks returned → respond with "I don't have enough content from the selected papers to answer this. Would you like to upload the full paper or add more context?"

**Step 5 — KV cache check.**

**Step 6 — Streaming LLM response with inline citations.**

**Step 7 — Visual orchestrator (parallel).**

**Step 8 — Save + safety wrap.**

### 13.4 Paper Discovery Agent (LangGraph)

Runs as background job via RabbitMQ. WebSocket progress events throughout. Max iterations: 15. Graph timeout: 300 seconds.

**Node 1 — Keyword Extraction (LLM):**
Receives user's natural language description. Returns: 4–8 precise academic search terms, primary research domain, structured Semantic Scholar query string. Structured JSON output required.

**Node 2 — Semantic Scholar Search (code):**
httpx GET to Semantic Scholar API. Returns up to 20 paper records: title, authors, abstract, year, citation count, open-access PDF URL (if available), DOI.

**Node 3 — Web Search Supplement (conditional code):**
If Semantic Scholar returns < 5 results → SerpAPI search targeting Google Scholar, arXiv, PubMed. Additional results merged with Semantic Scholar results. Deduplication by DOI.

**Node 4 — Relevance Ranking (LLM):**
LLM reviews all found papers, scores each 1–10 for relevance to user's described topic. Structured JSON output: ranked list with relevance scores and brief explanations. Top-scored papers presented to user.

**Node 5 — Download Attempt (code, per selected paper):**
For each paper user selected: attempt httpx GET to open-access PDF URL (if available) or DOI resolver. 120-second download timeout.

If download succeeds → paper goes to ingestion pipeline (Steps 1–8 in paper ingestion).

If download fails → paper added to "Pending Upload" list. Stored in `papers` table with `source: pending_upload`, `status: awaiting_file`. Full metadata preserved: title, authors, abstract, DOI, journal, year, publisher page URL, ResearchGate link (if found via web search).

**Node 6 — Discovery Report (LLM + code):**
Report generated: total found, successfully added (with titles), requiring manual download (with titles, abstracts, links, per-paper Upload button), failed entirely.

For pending papers: UI shows each paper card with metadata + direct link to where it can be found + "Upload PDF" button. When user clicks button and uploads the PDF, it enters the standard paper ingestion pipeline and is automatically linked to that paper's existing slot in the session.

### 13.5 Paper Ingestion Pipeline

**Step 1 — File validation:** Six-layer security check.

**Step 2 — Text extraction (code):** PyMuPDF for digital PDF. OCR chain for scanned. Vision LLM for pages with sparse text or embedded figures. python-docx for DOCX uploads.

**Step 3 — Section detection (code):** Font size heuristics + common academic section name matching + numbered section patterns.

**Step 4 — Table extraction (code):** pdfplumber lattice mode → stream mode fallback. Camelot for complex tables.

**Step 5 — Chunking (code):** Paper chunker: 400–600 token target, 80-token overlap, section-primary + semantic-secondary. Section name prepended to each chunk. Tables as single chunks with caption prepended.

**Step 6 — Dual embedding (concurrent code):** MiniLM + PubMedBERT simultaneously via asyncio.gather.

**Step 7 — Qdrant upsert (code):** To `papers_{session_id}_minilm` and `papers_{session_id}_pubmedbert`. Collections created on first upsert if they don't exist.

**Step 8 — PostgreSQL record (code):** Paper metadata written to `papers` table.

**Progress events:** "Processing paper: {title}..." → "Extracting text (page {n} of {total})..." → "Indexing {chunk_count} sections..." → "Paper added to your workspace."

### 13.6 Specialized NLP Tools — Two Modes

**Mode selection:** `TOOL_MODE` environment variable or model-router-service config. Per-tool, per-service configuration.

**Summarization:**
Model Mode: `sshleifer/distilbart-cnn-12-6`. Text chunked to fit context, each chunk summarized, summaries combined and summarized. Fast, no API cost.
LLM Mode: Medical LLM via LiteLLM. Structured academic summary: research question, methodology, key findings, conclusions, limitations, clinical relevance. Streamed.

**Q&A Generation:**
Model Mode: `google/t5-small`. Generates factual question-answer pairs from paper text.
LLM Mode: Medical LLM. Three difficulty levels: comprehension, analysis, application to clinical practice. Streamed pair by pair.

**Translation EN→AR / AR→EN:**
Model Mode: `Helsinki-NLP/opus-mt-en-ar` or `Helsinki-NLP/opus-mt-ar-en`. Fast, local, no API cost. Good for standard academic text.
LLM Mode: Medical LLM. Context-aware, preserves medical terminology precision. Better Arabic grammar for complex sentences.

Translation output stored in `paper_translations` table — not regenerated on re-access.

**Comparison (always LLM Mode):**
Requires reasoning across multiple documents. Local ML models not capable. Medical LLM queries Paper RAG for equivalent sections across all selected papers concurrently (asyncio.gather). Generates structured comparison table + narrative synthesis. Streamed.

### 13.7 Concurrent Processing in research-service

**Multiple papers uploaded simultaneously:** asyncio.gather with semaphore 3. Progress for each paper reported independently and concurrently in the WebSocket stream.

**OCR on large papers:** Pages split into groups of 10. Each group OCR'd concurrently. Results assembled in page order.

**Simultaneous NLP tools:** If user requests summarization + translation + Q&A generation at once → all three LLM calls run concurrently via asyncio.gather. Three separate streaming outputs delivered to three separate UI sections simultaneously.

**Per-paper comparison retrieval:** When comparing N papers, RAG searches for each paper's equivalent section run concurrently. Results for all papers arrive in parallel and are assembled into the comparison table.

---

*MAISYS Technical Guide — Part 3: Agent Architecture · Production Reliability · All Module Services in Full Detail*
