# ResolveAI architecture

```mermaid
flowchart LR
 UI[React support workbench] --> API[FastAPI + inherited JWT / workspace identity]
 API --> Router[Rule query router]
 Router --> Retrieval[BM25 or Postgres full-text + dense retrieval]
 Retrieval --> Fusion[RRF + lexical coverage reranking]
 Fusion --> Judge[Evidence gate]
 Judge -->|Insufficient, attempts < 2| Retrieval
 Judge -->|Ready or attempts exhausted| Tools[Allowlisted read-only tools]
 Tools --> Answer[SOP excerpt or OpenAI-compatible generation]
 Answer -->|Needs human help| Ticket[Persist evidence + diagnostics in ticket]
 Answer --> Finish[Persist run and trace]
 Ticket --> Finish
 Finish --> UI
```

## Boundaries

- `app/helpdesk/models.py`: isolated knowledge chunks and persistent run records, using inherited tenant/user IDs.
- `retrieval.py`: deterministic local hashing or remote embeddings; SQLite fallback for local demos; PostgreSQL pgvector cosine query and GIN full-text search, fused using RRF. Sparse ranking on SQLite is BM25. Reranking is lexical coverage, not a trained cross encoder.
- `workflow.py`: real LangGraph StateGraph with bounded retrieval retry, evidence gating, tool execution, grounded answer and ticket escalation. Query routing is rule based in both modes.
- `tools.py`: offline rules select tools in mock mode; OpenAI-compatible function calling selects tools in real model mode. The server validates the allowlist and fixes employee identity from JWT. Account and service states remain simulated in both modes. Historical tickets are real records from the isolated workspace, limited to the authenticated employee.
- `api.py`: durable request IDs prevent repeated tickets for a retried completed request, tenant/user isolation, SSE emits completed graph steps as they happen, and only commits ticket and final run together. The stream is graph progress, not artificial token-by-token output.

## Limitations

This is a local development MVP. It does not reset accounts, grant permissions, execute shell commands, restart services, connect to real enterprise identity systems, or claim production readiness. Evidence gating checks keyword overlap and citations; it is not a semantic faithfulness proof. Model answers can still be incorrect. Evaluation uses six tiny manually labelled fixtures, not a representative dataset.

The graph has no durable LangGraph checkpointer; durable final run records use SQLAlchemy. Process termination after reserving a run can leave its status at `running`; submit with a new request ID after fixing the failure. Database bootstrap uses inherited `create_all`; schema changes need planned migrations before shared deployment. PostgreSQL integration requires a live pgvector database and separate validation.


## Operational observation (2026-10-12)

`GET /helpdesk/analytics?days=7` requires the authenticated support role. It queries only the current tenant/user's persisted runs in a 1–90 day Hong Kong calendar window, excludes future records, then computes daily counts, categories, completion-based rates and nearest-rank P95. Ticket statuses are grouped in SQL for the current tenant across all time. No questions, descriptions or tool payloads are returned in the metric response.

`AnalyticsPanel.tsx` offers 7/30/90-day presets, data tables and metric JSON export. Ticket keyword/status/priority filters operate on the existing latest-100 list; `csv.ts` exports only summary columns and handles spreadsheet formula prefixes. Larger volumes need server-side pagination and grouped metric queries; this implementation targets the documented local MVP scale.


## Ticket collaboration and feedback (v1.1.0)

`ticket_ops.py` centralizes ticket ownership, legal status transitions, conditional SQL updates and demo resolution targets. `HelpdeskTicketEvent` is a separate table: integer primary sequence establishes ordering, a unique UUID gives note-request deduplication, and tenant/ticket/author bind every operation to actual identity. State changes and their events commit together. Inherited ticket writes are blocked for Helpdesk-created tickets so they cannot bypass this workflow.

`TicketOps.tsx` loads detail only when expanded, displays persisted author/time information and submits internal notes with a retained request UUID across retry. Queue badges and CSV use API-calculated target times. Close preserves resolution time; reopen clears the current completion time but retains the original target.

Run feedback is a current-user-only update to a completed run's JSON result. It preserves evidence/trace and stores the latest helpful/unhelpful response. Analytics reports actual response counts separately from evidence-gate rates; it does not infer satisfaction from lack of escalation.

For shared deployment, add versioned database migrations, supported concurrency testing against PostgreSQL and operational retention controls. Current app events can still be changed by database administrators and are not a compliance-grade immutable log.
