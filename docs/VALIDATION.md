# Local validation

Validated on 2026-10-12 in `E:\agent\resolveai`.

- Python: isolated `.venv`, versions in `backend/requirements.lock.txt`.
- Frontend: `npm run build` passes TypeScript checking and Vite production build.
- Backend: 22 ResolveAI regression tests pass using a temporary SQLite database. Database engine disposal is verified by clean test exit.
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
