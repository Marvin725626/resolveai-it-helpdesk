# Local validation

Validated on 2026-10-12 in `E:\agent\resolveai`.

- Python: isolated `.venv`, versions in `backend/requirements.lock.txt`.
- Frontend: `npm run build` passes TypeScript checking and Vite production build.
- Backend: 34 ResolveAI regression tests pass using a temporary SQLite database. Database engine disposal is verified by clean test exit.
- Live API: six manually labelled scenarios run through the actual server; Recall@4 = 1.0, MRR = 1.0, escalation-decision accuracy = 1.0. This is a tiny offline smoke set, not production performance. Per-case results and actual latency are in locally generated `evaluation.local.json`.
- Browser: demo sign-in; VPN diagnosis with source `[VPN-001]`; simulated degraded service creates a ticket; UI can take and resolve the ticket; the desktop layout and 390px responsive layout render without page overflow.
- Service ports: frontend 5174 and backend 8104. Startup and stop scripts isolate processes by recorded PID and project command line.

Not validated: real provider function calling, semantic embeddings, Docker image execution, PostgreSQL pgvector integration or actual enterprise IT connectors. Docker daemon was unavailable and no model key was provided. Account and service fixtures are explicitly simulated.


## 2026-10-12 expansion verification

- Backend: `python -m pytest tests/test_resolveai.py -q` → **15 passed**. New checks cover metrics deltas, valid period bounds, authentication, empty-workspace isolation, Hong Kong midnight grouping, nearest-rank P95 and exclusion of failed runs from completed-run denominators.
- CSV: `npm run test:csv` verifies exact Unicode/quote/newline output, formula prefix neutralization and ordinary text.
- Frontend: `npm run build` passes TypeScript and production bundling.
- Live browser: sign-in; software and VPN diagnoses; automatic handoff; 7 / 30 day analytics; actual JSON and CSV downloads; combined keyword/status/priority filters; disabled export on no matches; 390px layout without document overflow; zero page exceptions.
- Screenshots are from that local browser session, not design mockups. Reproduction script: `scripts/smoke-browser.cjs`. Run it only against a development database because it creates demo runs and tickets.

This is still an offline development demonstration. Analytics values in screenshots describe development records, not real enterprise users or validated business improvements. All-time workspace ticket counts and current-user windowed run counts intentionally have different scopes, labelled in the interface.


## v1.1.0 workflow verification · 2026-10-12

- Backend: **22 passed**, including real event persistence and ordering, self-claim idempotency, redacted/idempotent notes, stale update rejection, preservation of resolution time on close, workspace isolation, deadline boundaries, late completion, persistent/revisable feedback, colleague ownership permissions and legacy-write bypass protection.
- Browser: actual sign-in and diagnoses; useful-feedback submission; self-claim; two persisted internal notes; wait/resume/resolve/close; nine resulting events; target-time filter; desktop and 390px ticket detail screenshots; JSON/CSV downloads; no uncaught page exceptions or document overflow.
- CSV formatting checks and TypeScript/Vite production build pass.
- Existing tables and the first project remain intact; startup creates only the new application-event table for local development. Historical tickets have no invented event backfill.

The operation log is application-level, not a tamper-proof audit product. Target times are explicit demo policy using calendar hours without business-hour calendars or waiting-state pauses. No background email/Slack reminders or real enterprise operations were performed.


## v1.2.0 verification · 2026-10-12

- Backend: 27 passing tests covering version conflicts, archive/restore, preserved run evidence, rollback after indexing failure, tenant/admin scope, preview without runs/tickets, knowledge export, owner-only recovery and three-minute deadline checks.
- Browser: real UTF-8 Markdown import; edit and reindex; stop retrieving archived sources; restore as a new version; actual JSON download; 390px editor without overflow.
- Recovery: intercepted and dropped the actual stream response only after the real server finished diagnosis. UI retrieved the same persisted result; ticket count increased exactly once. Reload recovered the stored pending ID without resubmitting diagnosis.
- New screenshots show actual developer sample sources and version events; repeated trial samples were archived with history preserved.

No durable graph checkpointing or production deployment claims are added. Knowledge export is not a full database backup. Existing real-model/PostgreSQL/Docker validation limitations remain.


## v1.3.0 verification · 2026-10-13

- Backend: 34 passing regressions, including 1005 isolated synthetic tickets; disjoint pages; mine/unassigned scope; literal wildcard characters; 1000-row export cap; summary-only responses; stable same-time history ordering; lazy full-result fetch; readiness without key disclosure; backup integrity and path/overwrite constraints.
- Offline evaluation: 16 / 16 labelled fixture checks passed in a disposable database; real_model_calls=false. The committed report records actual generation time, version, per-case checks and latency. CI runs the same strict evaluation.
- Browser: core diagnosis/feedback/handoff/notes/wait/resume/resolve/close; actual ticket/history pages; cross-page CSV; assignment/category filters; full result on demand; report download; readiness; 390px evaluation layout with no document overflow or uncaught page exceptions.
- Frontend: typecheck and production build; CSV formatting and formula handling; authored-module formatting. npm audit issues were remediated by a Vite patch, compatible dependency updates and removing an unnecessary affected plugin chain.

These are development fixtures and local browser operations. They do not establish real customer volume, production business impact, semantic faithfulness or verified external-model/enterprise-system integration.


## v1.4.0 verification · 2026-10-13

- Backend: **39 passed**. New coverage includes assignment/release with preserved status and deadline, redacted event data, replay without duplicate mutation (including after a later release), stale-version rejection, finished-ticket/invalid-input rejection, fresh support-user role checks, foreign workspace and inactive-target rejection.
- History: 237 synthetic notes plus the created event exist only in the disposable test database. Traversal starts with the latest 100 and prepends older cursor pages in exact sequence. Inserting a newer event after page one does not alter the older traversal; the terminal cursor and query bounds are checked.
- Browser: the core diagnosis/feedback/ticket lifecycle and paged queue/history/report suites pass. A new UI diagnosis creates a dedicated demo ticket; the administrator assigns it, the script waits for real server commit and then drops the response, and the UI retries the frozen request without creating a second event. The UI then releases the ticket while retaining its status. Desktop and 390px screenshots show actual records; no page exception or horizontal overflow was observed.
- Frontend: authored-module formatting and TypeScript/Vite production build pass. The existing page smoke now reads expected software version from package.json. Strict isolated offline evaluation is 16/16 for version 1.4.0.

The long-history fixture is backend API coverage, not a claim of 237 real staff operations. The live browser check uses the existing demonstration administrator; it does not create fictional staff members or connect to enterprise systems. New screenshots are resolveai-assignment.png and resolveai-assignment-mobile.png. Original v1.3 integration limitations remain.
