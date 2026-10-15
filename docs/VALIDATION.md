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


## v1.5.0 verification · 2026-10-14

- Backend: **43 passed** across the existing helpdesk suite and invitation API tests. Invitation coverage includes SHA-256-only persistence, manager-only operations, fixed support-agent role, case-insensitive login, revoke, expiry, replay, cross-workspace isolation and simultaneous acceptance.
- Schema: the invitation Alembic revision adds the invitation table and case-insensitive unique email index; local bootstrap checks for the expression index explicitly because SQLite does not reflect it reliably.
- Frontend: TypeScript/Vite production build passes. The new team page and invitation acceptance page are included in authored-module formatting checks.
- Browser: isolated temporary workspace; owner created a one-time invite, a second browser context accepted it with its own credentials, the fragment was removed before follow-up requests, the new account reported `SUPPORT_AGENT`, and the owner saw it in the assignment API. The 390px team page has no document overflow. Screenshots use a disposable database and synthetic `example.com` identities; the active bearer link was removed before capture.
- Repeatable browser entry point: `scripts/smoke-invitations.cjs`; the temporary services and database used for this run were stopped and removed after verification.
- Limits: invite links are manually delivered, are not email-verified, and are bearer credentials. No email delivery or identity-provider integration is configured.

The 43 passing backend tests are isolated development regressions; they do not validate PostgreSQL concurrency, production mail delivery or external identity verification.


## v1.6.0 · 2026-10-15 · Batch integration

The following SQLite development suites were executed in separate processes and disposable databases. They cover 48 pytest tests in total, including rich lifecycle scenarios; this is a regression count, not a production success rate.

| Suite | Result |
| --- | --- |
| test_resolveai.py | 39 passed |
| test_invitations.py | 4 passed |
| test_notifications.py | 1 passed |
| test_requester_followup.py | 1 passed |
| test_attachments.py | 1 passed |
| test_resolutions.py | 1 passed |
| test_knowledge_drafts.py | 1 passed |

The legacy resolve fixtures now submit the structured resolution resource. The long-history test clears only its fixture rate-limit state, and the notification test preserves valid requester reminders while checking that self-operations add none. Production rate limits and notification behavior were retained.

Frontend authored files were formatted and the TypeScript/Vite production build passed (1917 modules). Fresh and upgraded SQLite databases reached Alembic head `53df04c2178b`; foreign-key checks passed for the three new resolution, satisfaction and knowledge-draft tables.

Resolution coverage includes current assignee/administrator permissions, CAS conflicts, repeat requests, immutable resolution rounds, requester-only per-round scoring, transaction failures and legacy confirmation without invented snapshots. Knowledge-draft coverage includes author/workspace isolation, original-create replay after editing, rejection and resubmission, source-resolution freshness, failed publication rollback and actual retrieval after publishing.

The browser reproduction entry point is `scripts/smoke-resolution-loop.cjs`. It creates random temporary example.com accounts and synthetic VPN content; no real customer input is used. Browser validation passed: two resolution rounds, requester reopen, confirmation and 5/5 score, support-authored draft, administrator rejection, author revision, administrator publication as KD-00001 v1 and actual retrieval hit. Before publication no draft hit was returned. An internal-note fixture was absent from the public resolution, draft and retrieval. The 390px requester page had no horizontal overflow and both browser contexts had zero page errors. Real LLM, PostgreSQL and production recovery remain unverified.


The managed local services were restarted after integration. Web `5174` and API `8104` returned HTTP 200; both the root API and OpenAPI reported version `1.6.0`, including the new resolution and draft routes. Existing user/database data were preserved; only the independent test services and disposable database were removed.


## v1.7.0 · 2026-10-15 · Triage and team operations

This batch executed four isolated pytest suites in separate processes: `test_resolveai.py` (39 passed), `test_notifications.py` (1 passed), `test_triage.py` (1 passed) and `test_team_metrics.py` (1 passed). These 42 tests include rich multi-step development scenarios; the older v1.6 results above remain a separate historical record. CI also retains the previous independent workflow suites.

Triage coverage includes assignee/administrator permissions, tenant isolation, request replay after later transfer/completion, CAS conflicts, transaction failure, priority deadlines derived from the original creation time, preserved assignment and redacted event reasons with fixed notification summaries. Personal views cover strict filter fields, per-user scope, persistent reads, immutable-create replay, version conflicts, a 10-active-view quota and tombstone deletion.

Team metrics use a fixed UTC clock and exact synthetic records to verify boundary inclusion, current waiting/backlog state, shared SLA cutoffs, inactive assignee workload, resolution rounds versus distinct ticket counts, an independent rating-submission window, rating distribution and null averages, tenant separation and support-role restrictions.

Authored frontend formatting and the TypeScript/Vite production build passed (1920 modules). Fresh and upgrade SQLite migrations passed at head `c7e60b9124d8`, including foreign-key checks. The isolated two-account browser workflow passed: HIGH to URGENT priority update preserved creation time and assignment, produced the original-created-plus-one-hour overdue deadline, and recorded prior/new deadlines with fixed notifications. A personal view survived reload, applied from page two back to page one and cleared a focused ticket, remained private from the other account, and disappeared after deletion/reload. The team panel switched to 30 days and its actual downloaded JSON reported days=30. The synthetic workspace snapshot contained 12 active tickets (one URGENT, eleven unassigned); these are test records, not production scale. The 390px layout had no horizontal document overflow and there were zero browser page errors.


CI generates its default fixture password randomly for each workflow run via GITHUB_ENV; no fixed reusable demo password is stored in the workflow. Fixture databases and credentials remain isolated from deployed accounts.
