# Local validation

Validated on 2026-10-11 in `E:\agent\resolveai`.

- Python: isolated `.venv`, versions in `backend/requirements.lock.txt`.
- Frontend: `npm run build` passes TypeScript checking and Vite production build.
- Backend: 13 ResolveAI regression tests pass using a temporary SQLite database. Database engine disposal is verified by clean test exit.
- Live API: six manually labelled scenarios run through the actual server; Recall@4 = 1.0, MRR = 1.0, escalation-decision accuracy = 1.0. This is a tiny offline smoke set, not production performance. Per-case results and actual latency are in locally generated `evaluation.local.json`.
- Browser: demo sign-in; VPN diagnosis with source `[VPN-001]`; simulated degraded service creates a ticket; UI can take and resolve the ticket; the desktop layout and 390px responsive layout render without page overflow.
- Service ports: frontend 5174 and backend 8104. Startup and stop scripts isolate processes by recorded PID and project command line.

Not validated: real provider function calling, semantic embeddings, Docker image execution, PostgreSQL pgvector integration or actual enterprise IT connectors. Docker daemon was unavailable and no model key was provided. Account and service fixtures are explicitly simulated.
